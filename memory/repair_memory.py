"""
memory/repair_memory.py
------------------------
Persistent cross-session repair memory for AutoDev.

Supersedes core/bug_memory.py with richer data, model effectiveness tracking,
per-language isolation, confidence weighting, and patch template retrieval.

Key improvements over bug_memory.py:
  - Per-language namespacing (Python fixes don't bleed into Java lookups)
  - Model effectiveness tracking (which model fixed which error class)
  - Confidence-weighted retrieval (highest-confidence fix wins over latest)
  - Success-count boosting (frequently-successful fixes rank higher)
  - Patch template storage with variable substitution hooks
  - Atomic write (tmp + rename) for crash safety
  - Backward-compatible shim for code that imports core.bug_memory

Storage format: JSON at memory/repair_memory.json
Schema version: 2 (version field in root dict)

Usage:
    memory = RepairMemory()

    # Retrieve best known fix
    fix = memory.retrieve_best(
        error_type="ZeroDivisionError",
        function_signature="def average(nums):",
        language="python",
    )
    if fix:
        # Use fix.fixed_code as a patch hint for the LLM prompt

    # Record a successful fix
    memory.record_success(
        error_type="ZeroDivisionError",
        function_signature="def average(nums):",
        language="python",
        bug_code=original_code,
        fixed_code=patched_code,
        model_name="deepseek-coder:6.7b",
        confidence=87.5,
    )

    # Get per-model effectiveness stats
    stats = memory.get_model_stats()
    # {"deepseek-coder:6.7b": {"attempts": 12, "successes": 9, "rate": 0.75}, ...}
"""

import json
import os
import hashlib
from datetime import datetime
from typing import Optional, Dict, List, Any
from dataclasses import dataclass, field, asdict


# ---------------------------------------------------------------------------
# Schema version
# ---------------------------------------------------------------------------
SCHEMA_VERSION = 2
DEFAULT_MEMORY_PATH = os.path.join(
    os.path.dirname(__file__), "repair_memory.json"
)


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class RepairRecord:
    """A single stored repair record."""
    error_type: str          # e.g. "ZeroDivisionError", "NullPointerException"
    language: str            # "python", "java", "cpp"
    function_signature: str  # First line of the buggy function
    bug_hash: str            # MD5 of bug_code for dedup
    bug_code: str            # The original buggy code snippet
    fixed_code: str          # The successful fix
    model_name: str          # Which model produced this fix
    confidence: float        # Confidence score at time of repair (0-100)
    success_count: int       # How many times this exact fix succeeded
    timestamp: str           # ISO timestamp of first success
    last_used: str           # ISO timestamp of most recent use

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "RepairRecord":
        # Provide defaults for fields added in schema v2
        return cls(
            error_type=d.get("error_type", ""),
            language=d.get("language", "python"),
            function_signature=d.get("function_signature", ""),
            bug_hash=d.get("bug_hash", ""),
            bug_code=d.get("bug_code", ""),
            fixed_code=d.get("fixed_code", ""),
            model_name=d.get("model_name", "unknown"),
            confidence=float(d.get("confidence", 0.0)),
            success_count=int(d.get("success_count", 1)),
            timestamp=d.get("timestamp", datetime.now().isoformat()),
            last_used=d.get("last_used", datetime.now().isoformat()),
        )


@dataclass
class ModelStat:
    """Per-model effectiveness statistics."""
    model_name: str
    attempts: int
    successes: int
    total_confidence: float

    @property
    def success_rate(self) -> float:
        return self.successes / self.attempts if self.attempts > 0 else 0.0

    @property
    def avg_confidence(self) -> float:
        return self.total_confidence / self.successes if self.successes > 0 else 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "model_name": self.model_name,
            "attempts": self.attempts,
            "successes": self.successes,
            "success_rate": round(self.success_rate, 3),
            "avg_confidence": round(self.avg_confidence, 1),
        }


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

class RepairMemory:
    """
    Persistent, confidence-weighted repair memory store.

    Thread safety: uses atomic file writes (tmp + os.replace).
    Not safe for concurrent multi-process access without external locking.
    """

    def __init__(self, filepath: str = DEFAULT_MEMORY_PATH):
        self.filepath = filepath
        self._records: List[RepairRecord] = []
        self._model_stats: Dict[str, ModelStat] = {}
        self._load()

    # -----------------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------------

    def retrieve_best(
        self,
        error_type: str,
        function_signature: str,
        language: str,
    ) -> Optional[RepairRecord]:
        """
        Retrieve the highest-confidence historical fix for a given error context.

        Matching criteria (in order of strictness):
          1. Exact match: error_type + language + function_signature
          2. Partial match: error_type + language (any signature)

        Among matches, the record with the highest composite score wins:
          score = confidence * 0.6 + success_count * 0.4 * 10
          (capped at 100 to avoid runaway counts dominating)

        Args:
            error_type         : Error class name (e.g. "ZeroDivisionError").
            function_signature : First line of the function with the bug.
            language           : "python", "java", or "cpp".

        Returns:
            The best RepairRecord, or None if no match found.
        """
        if not self._records:
            return None

        lang = language.lower()
        err = error_type.lower()
        sig = function_signature.strip()

        # Exact matches (error + language + signature)
        exact = [
            r for r in self._records
            if r.error_type.lower() == err
            and r.language.lower() == lang
            and r.function_signature.strip() == sig
        ]

        if exact:
            return self._best_record(exact)

        # Partial matches (error + language, any signature)
        partial = [
            r for r in self._records
            if r.error_type.lower() == err
            and r.language.lower() == lang
        ]

        if partial:
            return self._best_record(partial)

        return None

    def record_success(
        self,
        error_type: str,
        function_signature: str,
        language: str,
        bug_code: str,
        fixed_code: str,
        model_name: str = "unknown",
        confidence: float = 0.0,
    ) -> None:
        """
        Record a successful repair. Updates an existing record if one exists
        for the same bug (same bug_hash), otherwise creates a new record.

        Also updates per-model statistics.

        Args:
            error_type         : Error class (e.g. "IndexError").
            function_signature : First line of the repaired function.
            language           : "python", "java", "cpp".
            bug_code           : Original buggy source snippet.
            fixed_code         : The successfully applied fix.
            model_name         : Model that produced the fix.
            confidence         : ConfidenceEngine score (0-100).
        """
        bug_hash = self._hash(bug_code)
        now = datetime.now().isoformat()

        # Check for existing record with same bug hash
        existing = next(
            (r for r in self._records if r.bug_hash == bug_hash), None
        )

        if existing:
            # Update existing record
            existing.success_count += 1
            existing.last_used = now
            # Update to higher-confidence fix if this one is better
            if confidence > existing.confidence:
                existing.confidence = confidence
                existing.fixed_code = fixed_code
                existing.model_name = model_name
        else:
            # Create new record
            self._records.append(RepairRecord(
                error_type=error_type,
                language=language.lower(),
                function_signature=function_signature.strip(),
                bug_hash=bug_hash,
                bug_code=bug_code,
                fixed_code=fixed_code,
                model_name=model_name,
                confidence=confidence,
                success_count=1,
                timestamp=now,
                last_used=now,
            ))

        # Update model stats
        self._update_model_stat(model_name, success=True, confidence=confidence)

        self._save()

    def record_attempt(self, model_name: str, success: bool) -> None:
        """
        Record a model attempt (for tracking model effectiveness).
        Call this even on failed attempts to maintain accurate success rates.
        """
        self._update_model_stat(model_name, success=success, confidence=0.0)
        # Don't save on every failed attempt — save on success only
        if success:
            self._save()

    def get_model_stats(self) -> Dict[str, Dict[str, Any]]:
        """
        Return per-model effectiveness statistics.

        Returns:
            Dict mapping model_name -> {"attempts", "successes", "success_rate", "avg_confidence"}
        """
        return {
            name: stat.to_dict()
            for name, stat in self._model_stats.items()
        }

    def get_best_model(self) -> Optional[str]:
        """
        Return the name of the model with the highest success rate
        among those with at least 3 attempts.

        Returns:
            Model name string, or None if no data available.
        """
        qualified = [
            stat for stat in self._model_stats.values()
            if stat.attempts >= 3
        ]
        if not qualified:
            return None
        return max(qualified, key=lambda s: s.success_rate).model_name

    def get_summary(self) -> Dict[str, Any]:
        """Return a high-level summary of the memory store."""
        languages = {}
        for r in self._records:
            languages[r.language] = languages.get(r.language, 0) + 1
        return {
            "total_records": len(self._records),
            "by_language": languages,
            "model_count": len(self._model_stats),
            "best_model": self.get_best_model(),
        }

    def build_memory_hint(
        self,
        error_type: str,
        function_signature: str,
        language: str,
    ) -> str:
        """
        Build a short text hint for inclusion in the LLM prompt, showing the
        system has seen this bug pattern before and what worked.

        Returns:
            A formatted string suitable for injection into the prompt, or ""
            if no relevant memory exists.
        """
        record = self.retrieve_best(error_type, function_signature, language)
        if not record:
            return ""

        return (
            f"\n[Repair Memory] Similar bug seen before:\n"
            f"  Error: {record.error_type} | Language: {record.language}\n"
            f"  Success count: {record.success_count} | "
            f"Confidence: {record.confidence:.1f}% | "
            f"Model: {record.model_name}\n"
            f"  Previously successful fix:\n{record.fixed_code[:500]}\n"
        )

    # -----------------------------------------------------------------------
    # Internal helpers
    # -----------------------------------------------------------------------

    def _load(self) -> None:
        """Load memory from JSON file. Handles missing/corrupt files safely."""
        if not os.path.exists(self.filepath):
            self._records = []
            self._model_stats = {}
            return

        try:
            with open(self.filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, IOError, OSError) as e:
            print(f"[RepairMemory] Warning: Could not load {self.filepath}: {e}")
            self._records = []
            self._model_stats = {}
            return

        # Handle both schema versions
        if isinstance(data, list):
            # Schema v1 (old bug_memory.py format — list of records)
            self._records = []
            for item in data:
                try:
                    self._records.append(RepairRecord.from_dict(item))
                except Exception:
                    pass
            self._model_stats = {}
        elif isinstance(data, dict):
            # Schema v2
            records_raw = data.get("records", [])
            self._records = []
            for item in records_raw:
                try:
                    self._records.append(RepairRecord.from_dict(item))
                except Exception:
                    pass
            # Load model stats
            stats_raw = data.get("model_stats", {})
            self._model_stats = {}
            for name, s in stats_raw.items():
                self._model_stats[name] = ModelStat(
                    model_name=name,
                    attempts=int(s.get("attempts", 0)),
                    successes=int(s.get("successes", 0)),
                    total_confidence=float(s.get("total_confidence", 0.0)),
                )
        else:
            self._records = []
            self._model_stats = {}

    def _save(self) -> None:
        """Atomically save memory to JSON file using tmp + os.replace."""
        data = {
            "schema_version": SCHEMA_VERSION,
            "updated": datetime.now().isoformat(),
            "records": [r.to_dict() for r in self._records],
            "model_stats": {
                name: {
                    "attempts": stat.attempts,
                    "successes": stat.successes,
                    "total_confidence": stat.total_confidence,
                }
                for name, stat in self._model_stats.items()
            },
        }
        tmp_path = self.filepath + ".tmp"
        try:
            os.makedirs(os.path.dirname(self.filepath), exist_ok=True)
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            os.replace(tmp_path, self.filepath)
        except (IOError, OSError) as e:
            print(f"[RepairMemory] Warning: Could not save {self.filepath}: {e}")
            try:
                os.remove(tmp_path)
            except OSError:
                pass

    def _update_model_stat(
        self, model_name: str, success: bool, confidence: float
    ) -> None:
        """Update or create a ModelStat entry."""
        if model_name not in self._model_stats:
            self._model_stats[model_name] = ModelStat(
                model_name=model_name,
                attempts=0,
                successes=0,
                total_confidence=0.0,
            )
        stat = self._model_stats[model_name]
        stat.attempts += 1
        if success:
            stat.successes += 1
            stat.total_confidence += confidence

    @staticmethod
    def _best_record(records: List[RepairRecord]) -> RepairRecord:
        """Return the record with the highest composite score."""
        def composite(r: RepairRecord) -> float:
            # Confidence: 0-100, weight 0.6
            # Success count: diminishing returns, weight 0.4
            count_score = min(100.0, r.success_count * 10.0)
            return r.confidence * 0.6 + count_score * 0.4

        return max(records, key=composite)

    @staticmethod
    def _hash(text: str) -> str:
        """Compute MD5 hash of text for deduplication."""
        return hashlib.md5(text.encode("utf-8", errors="replace")).hexdigest()


# ---------------------------------------------------------------------------
# Backward-compatibility shim
# The old core/bug_memory.BugMemory is still used in agent/agent.py.
# This shim allows new code to import from memory.repair_memory while old
# code continues using core.bug_memory without changes.
# ---------------------------------------------------------------------------

class BugMemoryShim:
    """
    Shim that exposes the original BugMemory interface backed by RepairMemory.
    Allows agent.py to be updated gradually without breaking changes.
    """

    def __init__(self, filepath: str = "autodev_memory.json"):
        # Use legacy path for backward compat
        self._memory = RepairMemory(filepath=filepath)

    def store_fix(
        self,
        error_type: str,
        file_hash: str,
        function_signature: str,
        bug_code: str,
        fixed_code: str,
    ) -> None:
        self._memory.record_success(
            error_type=error_type,
            function_signature=function_signature,
            language="python",  # Legacy shim assumes Python
            bug_code=bug_code,
            fixed_code=fixed_code,
            model_name="unknown",
            confidence=0.0,
        )

    def retrieve_fix(
        self, error_type: str, function_signature: str
    ) -> Optional[str]:
        record = self._memory.retrieve_best(
            error_type=error_type,
            function_signature=function_signature,
            language="python",
        )
        return record.fixed_code if record else None
