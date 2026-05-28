"""
core/behavior_fingerprint.py
-----------------------------
Behavioral output fingerprinting for AutoDev.

Extracts a structured, comparable signature from a program's stdout so that
the retry manager can determine whether a patch actually changed the program's
behavior — not just its syntax.

A patch that produces IDENTICAL output to the buggy program is ineffective
and must be rejected, even if it compiled and ran without errors.

Usage:
    before_sig = BehaviorFingerprint.capture(initial_stdout)
    after_sig  = BehaviorFingerprint.capture(patched_stdout)
    delta      = BehaviorFingerprint.delta(before_sig, after_sig)

    if delta == 0.0:
        # patch changed nothing — skip this candidate
        ...
    elif delta > 0.0:
        # behavior changed — likely a real fix
        ...
"""

import re
import math
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Fingerprint structure
# ---------------------------------------------------------------------------

class OutputFingerprint:
    """
    Immutable snapshot of a program's observable output characteristics.

    Fields:
        raw           : The original stdout string (stored for equality checks).
        line_count    : Total number of non-empty output lines.
        char_count    : Total character count of stripped output.
        numbers       : Sorted list of all numeric values found in output.
        lists         : List of Python list-like structures found in output.
        is_empty      : True if stdout is blank/whitespace only.
        is_all_none   : True if every line is literally "None".
        has_nan       : True if "NaN" or "nan" appears in output.
        has_inf       : True if "inf" or "Infinity" appears in output.
        is_monotone_inc : True if all extracted numbers are non-decreasing.
        is_monotone_dec : True if all extracted numbers are non-increasing.
        is_uniform      : True if all extracted numbers are identical.
        error_keywords  : Set of error-related keywords present in output.
        first_line      : The first non-empty output line (for quick checks).
        last_line       : The last non-empty output line.
    """

    def __init__(
        self,
        raw: str,
        line_count: int,
        char_count: int,
        numbers: List[float],
        lists: List[list],
        is_empty: bool,
        is_all_none: bool,
        has_nan: bool,
        has_inf: bool,
        is_monotone_inc: bool,
        is_monotone_dec: bool,
        is_uniform: bool,
        error_keywords: set,
        first_line: str,
        last_line: str,
    ):
        self.raw = raw
        self.line_count = line_count
        self.char_count = char_count
        self.numbers = numbers
        self.lists = lists
        self.is_empty = is_empty
        self.is_all_none = is_all_none
        self.has_nan = has_nan
        self.has_inf = has_inf
        self.is_monotone_inc = is_monotone_inc
        self.is_monotone_dec = is_monotone_dec
        self.is_uniform = is_uniform
        self.error_keywords = error_keywords
        self.first_line = first_line
        self.last_line = last_line

    def is_suspicious(self) -> bool:
        """
        Returns True if this fingerprint represents output that indicates
        a logical bug is still present (None flood, uniform output, NaN/Inf,
        empty when non-empty expected, error keyword present).
        """
        return (
            self.is_empty
            or self.is_all_none
            or self.has_nan
            or self.has_inf
            or self.is_uniform
            or bool(self.error_keywords)
        )

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to a dict for logging/debugging."""
        return {
            "line_count": self.line_count,
            "char_count": self.char_count,
            "num_count": len(self.numbers),
            "numbers_sample": self.numbers[:10],
            "is_empty": self.is_empty,
            "is_all_none": self.is_all_none,
            "has_nan": self.has_nan,
            "has_inf": self.has_inf,
            "is_monotone_inc": self.is_monotone_inc,
            "is_monotone_dec": self.is_monotone_dec,
            "is_uniform": self.is_uniform,
            "error_keywords": list(self.error_keywords),
            "first_line": self.first_line,
            "last_line": self.last_line,
        }

    def __repr__(self) -> str:
        return (
            f"OutputFingerprint(lines={self.line_count}, chars={self.char_count}, "
            f"nums={len(self.numbers)}, empty={self.is_empty}, "
            f"none_flood={self.is_all_none}, suspicious={self.is_suspicious()})"
        )


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

class BehaviorFingerprint:
    """
    Captures and compares behavioral signatures of program output.
    """

    # Error-related keywords that indicate a logical failure even when
    # the program exits with returncode 0
    _ERROR_KEYWORDS = frozenset({
        "error", "exception", "traceback", "none", "nan", "inf",
        "undefined", "null", "failed", "invalid", "overflow",
        "segfault", "assertion", "warning",
    })

    @classmethod
    def capture(cls, stdout: str) -> OutputFingerprint:
        """
        Extract a behavioral fingerprint from program stdout.

        Args:
            stdout: The raw standard output of a program run.

        Returns:
            An OutputFingerprint instance describing the observable behavior.
        """
        if stdout is None:
            stdout = ""

        stripped = stdout.strip()
        non_empty_lines = [l.strip() for l in stripped.splitlines() if l.strip()]

        # Basic metrics
        line_count = len(non_empty_lines)
        char_count = len(stripped)
        is_empty = (char_count == 0)
        first_line = non_empty_lines[0] if non_empty_lines else ""
        last_line = non_empty_lines[-1] if non_empty_lines else ""

        # None flood detection
        is_all_none = (
            line_count >= 3
            and all(l == "None" for l in non_empty_lines)
        )

        # NaN / Inf detection
        has_nan = bool(re.search(r'\bnan\b', stripped, re.IGNORECASE))
        has_inf = bool(re.search(r'\binf(inity)?\b', stripped, re.IGNORECASE))

        # Extract all numeric values
        numbers = cls._extract_numbers(stripped)

        # Monotonicity and uniformity
        is_monotone_inc = cls._is_monotone_increasing(numbers)
        is_monotone_dec = cls._is_monotone_decreasing(numbers)
        is_uniform = (len(numbers) > 1 and len(set(numbers)) == 1)

        # Extract list structures
        lists = cls._extract_lists(stripped)

        # Error keyword scan (case-insensitive, whole-word)
        error_keywords: set[str] = set()
        lower_output = stripped.lower()
        for kw in cls._ERROR_KEYWORDS:
            if re.search(r'\b' + re.escape(kw) + r'\b', lower_output):
                error_keywords.add(kw)

        return OutputFingerprint(
            raw=stripped,
            line_count=line_count,
            char_count=char_count,
            numbers=numbers,
            lists=lists,
            is_empty=is_empty,
            is_all_none=is_all_none,
            has_nan=has_nan,
            has_inf=has_inf,
            is_monotone_inc=is_monotone_inc,
            is_monotone_dec=is_monotone_dec,
            is_uniform=is_uniform,
            error_keywords=error_keywords,
            first_line=first_line,
            last_line=last_line,
        )

    @classmethod
    def delta(
        cls,
        before: OutputFingerprint,
        after: OutputFingerprint,
    ) -> float:
        """
        Compute a behavioral delta score between two output fingerprints.

        Returns:
            0.0  — outputs are behaviorally identical (patch had no effect).
            >0.0 — outputs differ; the patch changed program behavior.

        The score is NOT a quality measure — it only indicates CHANGE.
        Higher delta = more changed, not necessarily more correct.

        Components:
          - Raw string equality (most reliable)
          - Line count change
          - Number vector distance (if both have numbers)
          - First/last line equality
          - Suspicion flag changes
        """
        score = 0.0

        # 1. Raw string identity — strongest signal
        if before.raw == after.raw:
            return 0.0  # Identical output, no change at all

        # 2. Line count changed
        if before.line_count != after.line_count:
            score += 1.0

        # 3. Character count changed significantly (>5% difference)
        if before.char_count > 0:
            char_ratio = abs(before.char_count - after.char_count) / before.char_count
            if char_ratio > 0.05:
                score += char_ratio

        # 4. Numeric vector distance
        if before.numbers and after.numbers:
            score += cls._numeric_distance(before.numbers, after.numbers)
        elif before.numbers != after.numbers:
            # One had numbers, other didn't
            score += 2.0

        # 5. First/last line changed
        if before.first_line != after.first_line:
            score += 0.5
        if before.last_line != after.last_line:
            score += 0.5

        # 6. Suspicion flags changed (e.g. NaN disappeared — good sign)
        before_flags = {
            "empty": before.is_empty,
            "none_flood": before.is_all_none,
            "nan": before.has_nan,
            "inf": before.has_inf,
            "uniform": before.is_uniform,
        }
        after_flags = {
            "empty": after.is_empty,
            "none_flood": after.is_all_none,
            "nan": after.has_nan,
            "inf": after.has_inf,
            "uniform": after.is_uniform,
        }
        for key in before_flags:
            if before_flags[key] != after_flags[key]:
                score += 1.0  # A flag changed — meaningful behavioral difference

        return round(score, 4)

    @classmethod
    def is_effective(
        cls,
        before: OutputFingerprint,
        after: OutputFingerprint,
        min_delta: float = 0.0,
    ) -> bool:
        """
        Returns True if the patch produced a meaningfully different output.
        A patch that changes nothing (delta == 0) is considered ineffective.

        Args:
            before: Fingerprint of the original (buggy) program output.
            after:  Fingerprint of the patched program output.
            min_delta: Minimum delta required to be considered effective.
                       Default 0.0 means any change qualifies.
        """
        return cls.delta(before, after) > min_delta

    # -----------------------------------------------------------------------
    # Internal extraction helpers
    # -----------------------------------------------------------------------

    @staticmethod
    def _extract_numbers(text: str) -> List[float]:
        """
        Extract all numeric values (int or float) from output text.
        Returns a sorted list for stable comparison.
        """
        raw_nums = re.findall(r'-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?', text)
        values: List[float] = []
        for n in raw_nums:
            try:
                values.append(float(n))
            except ValueError:
                pass
        return sorted(values)

    @staticmethod
    def _extract_lists(text: str) -> List[list]:
        """Extract Python list-like structures from output text."""
        import ast as _ast
        matches = re.findall(r'\[[^\]]+\]', text)
        result = []
        for m in matches:
            try:
                parsed = _ast.literal_eval(m)
                if isinstance(parsed, list):
                    result.append(parsed)
            except Exception:
                pass
        return result

    @staticmethod
    def _is_monotone_increasing(nums: List[float]) -> bool:
        if len(nums) < 2:
            return False
        return all(nums[i] <= nums[i + 1] for i in range(len(nums) - 1))

    @staticmethod
    def _is_monotone_decreasing(nums: List[float]) -> bool:
        if len(nums) < 2:
            return False
        return all(nums[i] >= nums[i + 1] for i in range(len(nums) - 1))

    @staticmethod
    def _numeric_distance(a: List[float], b: List[float]) -> float:
        """
        Compute a normalized distance between two numeric vectors.
        Uses the mean absolute difference of the overlapping prefix.
        Returns 0.0 if vectors are identical, higher values for larger differences.
        """
        if not a or not b:
            return 0.0

        min_len = min(len(a), len(b))
        paired_a = a[:min_len]
        paired_b = b[:min_len]

        # Length mismatch bonus
        len_diff_score = abs(len(a) - len(b)) * 0.3

        # Mean absolute difference, log-scaled to prevent huge outliers dominating
        diffs = []
        for x, y in zip(paired_a, paired_b):
            if x == y:
                diffs.append(0.0)
            else:
                # log1p normalization to handle large numeric ranges
                diffs.append(math.log1p(abs(x - y)))

        mad = sum(diffs) / len(diffs) if diffs else 0.0
        return round(mad + len_diff_score, 4)
