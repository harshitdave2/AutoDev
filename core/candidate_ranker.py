"""
core/candidate_ranker.py
-------------------------
Multi-factor candidate ranking for AutoDev patch candidates.

When the AI generates 3 fix candidates, the naive approach of always picking
candidate_0 leaves quality on the table. This module scores all candidates
before any is applied, so the best-ranked candidate is tried first.

Scoring factors (additive, higher = better):
  syntax_score      (0 or 1)   — Does the candidate parse cleanly?
  similarity_score  (0.0–1.0)  — Token similarity to original (conservative = safer)
  safety_score      (0 or 1)   — No cross-language contamination
  semantic_score    (0–5)      — PatchValidator semantic checks passed

Usage:
    ranked = CandidateRanker.rank(candidates, original_code, language, verbose=True)
    # ranked[0] is the best candidate
"""

import ast
import re
import difflib
from typing import List, Tuple

from core.patch_validator import PatchValidator
from core.java_semantic_validator import JavaSemanticValidator


# ---------------------------------------------------------------------------
# Score record
# ---------------------------------------------------------------------------

class CandidateScore:
    """
    Holds the multi-factor score for a single patch candidate.

    Attributes:
        candidate    : The raw candidate source string.
        total        : Composite score (higher = better).
        syntax       : 1 if the candidate parses cleanly, 0 otherwise.
        similarity   : SequenceMatcher token ratio vs original (0.0–1.0).
        safety       : 1 if no cross-language contamination, 0 otherwise.
        semantic     : Number of semantic validator checks passed (0–5).
        reject_reason: Non-empty if the candidate was hard-rejected.
    """

    def __init__(
        self,
        candidate: str,
        syntax: float,
        similarity: float,
        safety: float,
        semantic: float,
        reject_reason: str = "",
    ):
        self.candidate = candidate
        self.syntax = syntax
        self.similarity = similarity
        self.safety = safety
        self.semantic = semantic
        self.reject_reason = reject_reason
        # Total is a weighted sum; weights chosen to prioritise correctness
        # over conservatism (similarity is a tie-breaker, not primary signal)
        self.total = (
            syntax * 3.0          # Hard requirement — syntactically broken patches score very low
            + safety * 2.0        # Language safety is critical
            + semantic * 0.5      # Each semantic check contributes 0–2.5
            + similarity * 1.0    # Conservative diff preferred as tie-breaker
        )

    def __repr__(self) -> str:
        return (
            f"CandidateScore(total={self.total:.2f}, syntax={self.syntax}, "
            f"safety={self.safety}, semantic={self.semantic:.1f}, "
            f"similarity={self.similarity:.2f}"
            + (f", REJECTED={self.reject_reason}" if self.reject_reason else "")
            + ")"
        )


# ---------------------------------------------------------------------------
# Ranker
# ---------------------------------------------------------------------------

class CandidateRanker:
    """
    Scores and ranks a list of patch candidates for a given language.
    """

    # Semantic checks to run, in order.
    # Each check is a (method_name, weight) pair.
    # Weight = number of points awarded if the check PASSES.
    _SEMANTIC_CHECKS: List[Tuple[str, float]] = [
        ("check_division_safety", 1.0),
        ("check_return_paths", 1.0),
        ("check_loop_bounds", 1.0),
        ("check_none_dereference", 1.0),
        ("check_cross_language_contamination", 1.0),
    ]

    @classmethod
    def rank(
        cls,
        candidates: List[str],
        original_code: str,
        language: str,
        verbose: bool = False,
        fast: bool = False,
    ) -> List[str]:
        """
        Score and rank all candidates. Return the sorted list (best first).

        In fast mode:
          - Single candidate: returned immediately without scoring.
          - Multiple candidates: only syntax + safety checks run (no SequenceMatcher).

        Candidates that are hard-rejected (cross-language, syntax error on
        a parseable language) are moved to the end of the list but not
        dropped — the caller may still want to attempt them as a last resort.

        Args:
            candidates   : List of candidate source strings.
            original_code: The original (buggy) source code for comparison.
            language     : "python", "java", or "cpp".
            verbose      : If True, print the score table to stdout.
            fast         : If True, use lightweight ranking (skip SequenceMatcher).

        Returns:
            Sorted list of candidate strings (best first).
        """
        if not candidates:
            return candidates

        # Fast path: only one candidate — skip scoring entirely
        if fast and len(candidates) == 1:
            print("[CandidateRanker] fast mode: single candidate, skipping ranking")
            return candidates

        # Fast path: multiple candidates — run only syntax + safety
        if fast:
            print(f"[CandidateRanker] fast mode: {len(candidates)} candidates, lightweight ranking")
            return cls._rank_fast(candidates, language)

        scores: List[CandidateScore] = []

        for idx, candidate in enumerate(candidates):
            score = cls._score_candidate(candidate, original_code, language, idx)
            scores.append(score)

        # Sort: valid candidates first (no reject_reason), then by total desc
        scores.sort(key=lambda s: (bool(s.reject_reason), -s.total))

        if verbose:
            cls._print_table(scores, language)

        return [s.candidate for s in scores]

    @classmethod
    def _rank_fast(cls, candidates: List[str], language: str) -> List[str]:
        """
        Lightweight ranking: syntax score + cross-language safety only.
        No SequenceMatcher — O(n) instead of O(n² * len) for speed.
        """
        def _fast_score(c: str) -> float:
            syntax = cls._score_syntax(c, language)
            ok, _ = PatchValidator.check_cross_language_contamination(c, language)
            safety = 1.0 if ok else 0.0
            return syntax * 3.0 + safety * 2.0

        return sorted(candidates, key=_fast_score, reverse=True)

    @classmethod
    def _score_candidate(
        cls,
        candidate: str,
        original: str,
        language: str,
        idx: int,
    ) -> CandidateScore:
        """Compute the multi-factor score for a single candidate."""

        reject_reason = ""

        # ---- Syntax score ----
        syntax = cls._score_syntax(candidate, language)
        if syntax == 0.0 and language == "python":
            # Python syntax errors are a hard failure
            reject_reason = "SyntaxError"
        elif syntax == 0.0 and language == "java":
            # Java structural syntax failure is also a hard rejection
            reject_reason = "Java structural syntax failure"

        # ---- Cross-language safety ----
        ok, reason = PatchValidator.check_cross_language_contamination(candidate, language)
        safety = 1.0 if ok else 0.0
        if not ok and not reject_reason:
            reject_reason = reason

        # ---- Structural similarity ----
        similarity = cls._score_similarity(original, candidate)

        # ---- Semantic score (passes original for Java javac gate) ----
        semantic = cls._score_semantic(candidate, language, original)

        # ---- Identity penalty: patch identical to original = 0 everything ----
        if original.strip() and candidate.strip() == original.strip():
            reject_reason = reject_reason or "Identical to original — no fix applied"
            syntax = 0.0
            similarity = 0.0
            safety = 0.0
            semantic = 0.0

        return CandidateScore(
            candidate=candidate,
            syntax=syntax,
            similarity=similarity,
            safety=safety,
            semantic=semantic,
            reject_reason=reject_reason,
        )

    @staticmethod
    def _score_syntax(candidate: str, language: str) -> float:
        """Return 1.0 if candidate is syntactically valid, 0.0 otherwise."""
        if not candidate or not candidate.strip():
            return 0.0

        if language == "python":
            try:
                ast.parse(candidate)
                return 1.0
            except SyntaxError:
                return 0.0

        elif language == "java":
            # Structural syntax: balanced braces, has class declaration
            opens = candidate.count("{")
            closes = candidate.count("}")
            if opens != closes:
                return 0.5  # Likely truncated but not hopeless
            if "class " not in candidate:
                return 0.0
            return 1.0

        elif language == "cpp":
            # Structural syntax: has #include and balanced braces
            opens = candidate.count("{")
            closes = candidate.count("}")
            if opens != closes:
                return 0.5
            if "#include" not in candidate and re.search(r'\bmain\s*\(', candidate):
                return 0.8  # Has main but no include — suspicious
            return 1.0

        return 1.0  # Unknown language — assume OK

    @staticmethod
    def _score_similarity(original: str, candidate: str) -> float:
        """
        Token-level SequenceMatcher similarity score (0.0–1.0).
        A moderate similarity (0.5–0.85) is optimal — high enough to
        be conservative, low enough to have actually fixed something.
        Penalize extremes:
          - Very low (<0.3): likely a hallucinated rewrite
          - Identical (1.0): no fix applied
        """
        if not original or not candidate:
            return 0.0

        orig_tokens = original.split()
        patch_tokens = candidate.split()

        if not orig_tokens or not patch_tokens:
            return 0.0

        raw_ratio = difflib.SequenceMatcher(None, orig_tokens, patch_tokens).ratio()

        # Penalize extremes
        if raw_ratio >= 1.0:
            return 0.0   # Identical → no fix
        if raw_ratio < 0.30:
            return raw_ratio * 0.5  # Heavy penalty for large rewrites

        return raw_ratio

    @classmethod
    def _score_semantic(cls, candidate: str, language: str, original: str = "") -> float:
        """
        Run all semantic checks and return a score equal to the number
        of checks that PASSED (0–5).

        For Java, routes through JavaSemanticValidator which includes
        structural checks + an optional javac compile gate.
        """
        if language == "java":
            try:
                return JavaSemanticValidator.score(candidate, original)
            except Exception as e:
                print(f"[JavaValidator] Error during scoring: {e}")
                return 2.5  # Neutral fallback

        passed = 0.0
        for method_name, weight in cls._SEMANTIC_CHECKS:
            method = getattr(PatchValidator, method_name, None)
            if method is None:
                continue
            try:
                ok, _ = method(candidate, language)
                if ok:
                    passed += weight
            except Exception:
                # If a check crashes, give neutral score (don't penalize)
                passed += weight * 0.5

        return passed

    @staticmethod
    def _print_table(scores: List[CandidateScore], language: str) -> None:
        """Print a formatted candidate ranking table to stdout."""
        print(f"\n[CandidateRanker] Ranking {len(scores)} candidates for {language.upper()}:")
        print(f"  {'#':<3} {'Total':>6} {'Syntax':>7} {'Safety':>7} {'Semantic':>9} "
              f"{'Similarity':>11} {'Status'}")
        print(f"  {'-'*65}")
        for i, s in enumerate(scores):
            status = f"REJECTED: {s.reject_reason}" if s.reject_reason else "OK"
            print(
                f"  {i:<3} {s.total:>6.2f} {s.syntax:>7.1f} {s.safety:>7.1f} "
                f"{s.semantic:>9.1f} {s.similarity:>11.3f}  {status}"
            )
        print()
