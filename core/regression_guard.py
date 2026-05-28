"""
core/regression_guard.py
-------------------------
Regression detection for AutoDev patch validation.

Captures a complete execution snapshot BEFORE a patch is applied, then
compares it to the POST-patch snapshot to detect regressions — cases where
the patch "fixed" the original crash but introduced NEW problems.

A regression is defined as any of:
  - New crash: was exit 0, now exit non-0
  - New error keywords in stderr that were absent before
  - New stderr content when previously clean
  - Significant output shrinkage (lost more than 30% of lines)
  - Significant numeric drift in previously-stable values
  - New warning-pattern matches in stderr/stdout

Usage:
    guard = RegressionGuard()
    before = guard.capture(run_result)
    # ... apply patch ...
    after = guard.capture(new_run_result)
    report = guard.check(before, after)
    if report.has_regression:
        print(report.reasons)
"""

import re
import math
from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional


# ---------------------------------------------------------------------------
# Snapshot structure
# ---------------------------------------------------------------------------

@dataclass
class ExecutionSnapshot:
    """
    Complete record of a single program execution for regression comparison.

    Attributes:
        returncode     : Process exit code (0 = success).
        stdout         : Standard output (stripped).
        stderr         : Standard error (stripped).
        stdout_lines   : Non-empty stdout lines.
        stderr_lines   : Non-empty stderr lines.
        numbers        : Sorted list of all numeric values in stdout.
        error_keywords : Set of error-related keywords found in stderr.
        warning_count  : Number of warning-pattern matches in stderr.
        has_crash      : True if returncode != 0.
        output_length  : Character count of stdout.
    """
    returncode: int
    stdout: str
    stderr: str
    stdout_lines: List[str]
    stderr_lines: List[str]
    numbers: List[float]
    error_keywords: set
    warning_count: int
    has_crash: bool
    output_length: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            "returncode": self.returncode,
            "has_crash": self.has_crash,
            "stdout_lines": len(self.stdout_lines),
            "stderr_lines": len(self.stderr_lines),
            "output_length": self.output_length,
            "numbers_count": len(self.numbers),
            "error_keywords": list(self.error_keywords),
            "warning_count": self.warning_count,
        }


# ---------------------------------------------------------------------------
# Regression report
# ---------------------------------------------------------------------------

@dataclass
class RegressionReport:
    """
    Result of a before/after regression check.

    Attributes:
        has_regression  : True if a regression was detected.
        reasons         : List of human-readable regression descriptions.
        severity        : "CRITICAL", "WARNING", or "OK".
        before_summary  : One-line summary of before state.
        after_summary   : One-line summary of after state.
    """
    has_regression: bool
    reasons: List[str]
    severity: str
    before_summary: str
    after_summary: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "has_regression": self.has_regression,
            "severity": self.severity,
            "reasons": self.reasons,
            "before": self.before_summary,
            "after": self.after_summary,
        }

    def __str__(self) -> str:
        if not self.has_regression:
            return f"RegressionGuard: OK — {self.after_summary}"
        return (
            f"RegressionGuard: {self.severity} — "
            + "; ".join(self.reasons[:3])
        )


# ---------------------------------------------------------------------------
# Main guard class
# ---------------------------------------------------------------------------

class RegressionGuard:
    """
    Captures execution snapshots and detects regressions between them.

    Configuration:
        output_shrink_threshold : Fraction of line loss to flag as a regression.
                                  Default 0.3 (>30% lines lost).
        numeric_drift_threshold : Log-scale distance threshold for numeric drift.
                                  Default 2.0.
        min_lines_for_shrink    : Minimum lines in before snapshot before shrink
                                  check is enforced. Default 3.
    """

    # Error-related keywords to track in stderr
    _ERROR_KEYWORDS = frozenset({
        "error", "exception", "traceback", "segfault", "assertion",
        "fatal", "abort", "corruption", "overflow", "underflow",
        "null pointer", "nullpointer", "index out", "out of bounds",
        "undefined behavior", "stack overflow",
    })

    # Warning patterns to count
    _WARNING_PATTERNS = [
        re.compile(r'\bwarning\b', re.IGNORECASE),
        re.compile(r'\bdeprecation\b', re.IGNORECASE),
        re.compile(r'\buncaught\b', re.IGNORECASE),
    ]

    def __init__(
        self,
        output_shrink_threshold: float = 0.3,
        numeric_drift_threshold: float = 2.0,
        min_lines_for_shrink: int = 3,
    ):
        self.output_shrink_threshold = output_shrink_threshold
        self.numeric_drift_threshold = numeric_drift_threshold
        self.min_lines_for_shrink = min_lines_for_shrink

    def capture(self, run_result: Dict[str, Any]) -> ExecutionSnapshot:
        """
        Capture an ExecutionSnapshot from a run_script() result dict.

        Args:
            run_result: Dict with keys "returncode", "stdout", "stderr".

        Returns:
            ExecutionSnapshot with extracted metrics.
        """
        returncode = int(run_result.get("returncode", -1))
        stdout = (run_result.get("stdout") or "").strip()
        stderr = (run_result.get("stderr") or "").strip()

        stdout_lines = [l.strip() for l in stdout.splitlines() if l.strip()]
        stderr_lines = [l.strip() for l in stderr.splitlines() if l.strip()]

        numbers = self._extract_numbers(stdout)
        error_keywords = self._extract_error_keywords(stderr)
        warning_count = self._count_warnings(stderr)
        has_crash = returncode != 0
        output_length = len(stdout)

        return ExecutionSnapshot(
            returncode=returncode,
            stdout=stdout,
            stderr=stderr,
            stdout_lines=stdout_lines,
            stderr_lines=stderr_lines,
            numbers=numbers,
            error_keywords=error_keywords,
            warning_count=warning_count,
            has_crash=has_crash,
            output_length=output_length,
        )

    def check(
        self,
        before: ExecutionSnapshot,
        after: ExecutionSnapshot,
    ) -> RegressionReport:
        """
        Compare before and after snapshots and detect regressions.

        The check is asymmetric: improvements are always allowed, only
        degradations are flagged.

        Args:
            before: Snapshot captured before the patch was applied.
            after:  Snapshot captured after the patch was applied.

        Returns:
            RegressionReport with has_regression, reasons, severity.
        """
        reasons: List[str] = []
        severity = "OK"

        # ---- Check 1: New crash introduced ----
        # A patch that turns a clean run into a crash is a regression.
        if not before.has_crash and after.has_crash:
            reasons.append(
                f"Patch introduced a new crash (was exit 0, now exit {after.returncode})"
            )
            severity = "CRITICAL"

        # ---- Check 2: Returncode worsened ----
        # E.g., was exit 1 (crash), now exit 139 (segfault) — different error
        if before.has_crash and after.has_crash and after.returncode != before.returncode:
            reasons.append(
                f"Exit code changed from {before.returncode} to {after.returncode} "
                f"— patch changed the failure mode but did not fix it"
            )
            if severity == "OK":
                severity = "WARNING"

        # ---- Check 3: New error keywords in stderr ----
        new_errors = after.error_keywords - before.error_keywords
        if new_errors:
            reasons.append(
                f"New error keyword(s) in stderr after patch: {', '.join(sorted(new_errors))}"
            )
            if severity not in ("CRITICAL",):
                severity = "WARNING"

        # ---- Check 4: New stderr content (was clean, now has errors) ----
        if not before.stderr_lines and after.stderr_lines:
            # Only flag this if the after run also crashed, otherwise it's just warnings
            if after.has_crash:
                reasons.append(
                    "Patch introduced new stderr output in a previously clean run"
                )
                if severity == "OK":
                    severity = "WARNING"

        # ---- Check 5: Significant output shrinkage ----
        before_lines = len(before.stdout_lines)
        after_lines = len(after.stdout_lines)
        if before_lines >= self.min_lines_for_shrink and after_lines < before_lines:
            shrink_ratio = (before_lines - after_lines) / before_lines
            if shrink_ratio > self.output_shrink_threshold:
                reasons.append(
                    f"Output shrinkage: {before_lines} lines → {after_lines} lines "
                    f"({shrink_ratio:.0%} lost) — patch may have broken output generation"
                )
                if severity == "OK":
                    severity = "WARNING"

        # ---- Check 6: Numeric drift in stable output ----
        # Only check when both runs had numbers and neither crashed
        if (not before.has_crash and not after.has_crash
                and before.numbers and after.numbers):
            drift = self._numeric_drift(before.numbers, after.numbers)
            if drift > self.numeric_drift_threshold:
                reasons.append(
                    f"Significant numeric drift detected (drift={drift:.2f}) — "
                    f"patch changed output values unexpectedly"
                )
                if severity == "OK":
                    severity = "WARNING"

        # ---- Check 7: New warnings introduced ----
        new_warnings = after.warning_count - before.warning_count
        if new_warnings > 0:
            reasons.append(
                f"Patch introduced {new_warnings} new warning(s)"
            )
            if severity == "OK":
                severity = "INFO"

        has_regression = len(reasons) > 0 and severity in ("CRITICAL", "WARNING")

        before_summary = (
            f"exit={before.returncode}, lines={len(before.stdout_lines)}, "
            f"errs={len(before.error_keywords)}"
        )
        after_summary = (
            f"exit={after.returncode}, lines={len(after.stdout_lines)}, "
            f"errs={len(after.error_keywords)}"
        )

        return RegressionReport(
            has_regression=has_regression,
            reasons=reasons,
            severity=severity,
            before_summary=before_summary,
            after_summary=after_summary,
        )

    # -----------------------------------------------------------------------
    # Internal helpers
    # -----------------------------------------------------------------------

    @staticmethod
    def _extract_numbers(text: str) -> List[float]:
        raw = re.findall(r'-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?', text)
        values = []
        for n in raw:
            try:
                v = float(n)
                if not math.isnan(v) and not math.isinf(v):
                    values.append(v)
            except ValueError:
                pass
        return sorted(values)

    def _extract_error_keywords(self, stderr: str) -> set:
        """Return set of matched error keywords found in stderr."""
        lower = stderr.lower()
        found = set()
        for kw in self._ERROR_KEYWORDS:
            if kw in lower:
                found.add(kw)
        return found

    def _count_warnings(self, stderr: str) -> int:
        """Count warning-pattern matches in stderr."""
        count = 0
        for pattern in self._WARNING_PATTERNS:
            count += len(pattern.findall(stderr))
        return count

    @staticmethod
    def _numeric_drift(before: List[float], after: List[float]) -> float:
        """
        Compute log-scale mean absolute drift between two sorted number lists.
        Returns 0.0 if identical, higher for larger differences.
        Only compares the overlapping prefix (first min(len) elements).
        """
        if not before or not after:
            return 0.0
        min_len = min(len(before), len(after))
        diffs = []
        for x, y in zip(before[:min_len], after[:min_len]):
            if x == y:
                diffs.append(0.0)
            else:
                diffs.append(math.log1p(abs(x - y)))
        return sum(diffs) / len(diffs) if diffs else 0.0
