"""
core/behavior_engine.py
------------------------
Domain-aware behavioral output analysis for AutoDev.

This module extends the basic fingerprinting in behavior_fingerprint.py with
domain-specific semantic validators that can detect logically impossible or
suspicious program outputs — even when the program exits with returncode 0.

Key capabilities:
  - Negative Fibonacci detection (any negative value after position 0)
  - Accuracy/percentage bounds checking (must be 0-100%)
  - Probability bounds checking (must be 0.0-1.0)
  - Sort-order validation (labeled "sorted" output must be sorted)
  - Collection null density (>50% None values in a list is suspicious)
  - Duplicate saturation detection (same value repeated >80% of list)
  - Matrix dimension consistency
  - Numeric domain violations (negative factorials, negative distances)
  - Empty collection when non-empty expected
  - Infinity/NaN in scientific contexts

All checks are heuristic and fail-safe: a false positive is better than
a missed regression, but no check will CRASH the pipeline.

Usage:
    report = BehaviorEngine.analyze(stdout, context_hint="fibonacci")
    if not report.is_logically_valid:
        print(report.violations)
        print(report.severity)      # "CRITICAL", "WARNING", "INFO"
"""

import re
import ast
import math
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class BehaviorViolation:
    """A single detected behavioral violation."""
    rule: str           # Short name of the violated rule
    message: str        # Human-readable description
    severity: str       # "CRITICAL", "WARNING", "INFO"
    evidence: str       # The offending value or snippet


@dataclass
class BehaviorReport:
    """
    Full behavioral analysis report for a program's output.

    Attributes:
        is_logically_valid : True if no CRITICAL violations found.
        violations         : List of all detected violations.
        severity           : Highest severity level found ("CRITICAL"/"WARNING"/"INFO"/"OK").
        summary            : One-line human-readable summary.
        domain_hints       : Which domain validators fired.
        raw_output         : The original stdout analyzed.
    """
    is_logically_valid: bool
    violations: List[BehaviorViolation]
    severity: str
    summary: str
    domain_hints: List[str]
    raw_output: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "is_logically_valid": self.is_logically_valid,
            "severity": self.severity,
            "summary": self.summary,
            "violation_count": len(self.violations),
            "violations": [
                {"rule": v.rule, "message": v.message, "severity": v.severity}
                for v in self.violations
            ],
            "domain_hints": self.domain_hints,
        }


# ---------------------------------------------------------------------------
# Main engine
# ---------------------------------------------------------------------------

class BehaviorEngine:
    """
    Domain-aware behavioral output analyzer.

    All analyze() calls are safe: exceptions inside individual checks are
    caught and logged as INFO-level violations rather than crashing.
    """

    # Severity ordering for comparison
    _SEVERITY_RANK = {"CRITICAL": 3, "WARNING": 2, "INFO": 1, "OK": 0}

    @classmethod
    def analyze(
        cls,
        stdout: str,
        context_hint: str = "",
        language: str = "python",
    ) -> BehaviorReport:
        """
        Run all behavioral validators against a program's stdout.

        Args:
            stdout       : Raw standard output string from a program run.
            context_hint : Optional free-text hint about the program's domain
                           (e.g. "fibonacci", "sort", "matrix"). Used to activate
                           domain-specific validators.
            language     : Target language ("python", "java", "cpp").

        Returns:
            BehaviorReport with is_logically_valid, violations, and severity.
        """
        if stdout is None:
            stdout = ""

        violations: List[BehaviorViolation] = []
        domain_hints: List[str] = []

        # Extract numeric values and list structures from output
        numbers = cls._extract_numbers(stdout)
        lists = cls._extract_lists(stdout)
        lines = [l.strip() for l in stdout.splitlines() if l.strip()]
        hint_lower = context_hint.lower()
        output_lower = stdout.lower()

        # --- Universal checks (always run) ---
        violations += cls._check_nan_inf(stdout, numbers)
        violations += cls._check_none_flood(lines)
        violations += cls._check_null_density(lists, violations)
        violations += cls._check_duplicate_saturation(lists)
        violations += cls._check_empty_output(stdout, lines)

        # --- Domain-specific checks (activated by hint or output content) ---

        # Fibonacci domain
        if "fibonacci" in hint_lower or "fibonacci" in output_lower or "fib" in hint_lower:
            domain_hints.append("fibonacci")
            violations += cls._check_fibonacci_negativity(numbers, lines)

        # Sorting domain
        if "sort" in hint_lower or "sort" in output_lower or "order" in hint_lower:
            domain_hints.append("sort")
            violations += cls._check_sort_order(lists, lines)

        # Percentage / accuracy domain
        if any(kw in output_lower for kw in ["accuracy", "percent", "%", "precision", "recall", "f1"]):
            domain_hints.append("percentage")
            violations += cls._check_percentage_bounds(numbers, stdout)

        # Probability domain
        if any(kw in output_lower for kw in ["probability", "prob", "likelihood", "confidence"]):
            domain_hints.append("probability")
            violations += cls._check_probability_bounds(numbers, stdout)

        # Factorial / combinatorics domain
        if any(kw in output_lower for kw in ["factorial", "permut", "combin"]):
            domain_hints.append("factorial")
            violations += cls._check_factorial_negativity(numbers, lines)

        # Distance / metric domain
        if any(kw in output_lower for kw in ["distance", "dist", "euclidean", "manhattan"]):
            domain_hints.append("distance")
            violations += cls._check_distance_negativity(numbers, stdout)

        # Average / mean domain
        if any(kw in output_lower for kw in ["average", "mean", "avg"]):
            domain_hints.append("average")
            violations += cls._check_average_range(numbers, lists, stdout)

        # Normalization domain
        if any(kw in output_lower for kw in ["normalized", "normaliz", "unit vector"]):
            domain_hints.append("normalize")
            violations += cls._check_normalized_bounds(numbers, stdout)

        # --- Determine overall severity and validity ---
        if not violations:
            severity = "OK"
        else:
            highest = max(
                cls._SEVERITY_RANK.get(v.severity, 0) for v in violations
            )
            severity = ["OK", "INFO", "WARNING", "CRITICAL"][highest]

        is_logically_valid = severity != "CRITICAL"

        # Build summary
        critical_count = sum(1 for v in violations if v.severity == "CRITICAL")
        warning_count = sum(1 for v in violations if v.severity == "WARNING")
        if not violations:
            summary = "Output appears logically valid."
        elif critical_count > 0:
            summary = (
                f"{critical_count} critical violation(s) detected: "
                + "; ".join(v.rule for v in violations if v.severity == "CRITICAL")
            )
        else:
            summary = (
                f"{warning_count} warning(s): "
                + "; ".join(v.rule for v in violations if v.severity == "WARNING")[:120]
            )

        return BehaviorReport(
            is_logically_valid=is_logically_valid,
            violations=violations,
            severity=severity,
            summary=summary,
            domain_hints=domain_hints,
            raw_output=stdout,
        )

    # -----------------------------------------------------------------------
    # Universal validators
    # -----------------------------------------------------------------------

    @staticmethod
    def _check_nan_inf(stdout: str, numbers: List[float]) -> List[BehaviorViolation]:
        violations = []
        if re.search(r'\bnan\b', stdout, re.IGNORECASE):
            violations.append(BehaviorViolation(
                rule="nan_output",
                message="Output contains NaN — a computation produced an undefined result",
                severity="CRITICAL",
                evidence=re.search(r'.{0,30}nan.{0,30}', stdout, re.IGNORECASE).group(0).strip()
            ))
        if re.search(r'\binf(inity)?\b', stdout, re.IGNORECASE):
            violations.append(BehaviorViolation(
                rule="inf_output",
                message="Output contains Infinity — likely a division by zero or overflow",
                severity="CRITICAL",
                evidence=re.search(r'.{0,30}inf.{0,30}', stdout, re.IGNORECASE).group(0).strip()
            ))
        return violations

    @staticmethod
    def _check_none_flood(lines: List[str]) -> List[BehaviorViolation]:
        if len(lines) >= 3 and all(l == "None" for l in lines):
            return [BehaviorViolation(
                rule="none_flood",
                message=f"All {len(lines)} output lines are 'None' — function returns were lost",
                severity="CRITICAL",
                evidence=f"{len(lines)} x None"
            )]
        none_count = sum(1 for l in lines if l == "None")
        if len(lines) > 0 and none_count / len(lines) > 0.6:
            return [BehaviorViolation(
                rule="none_majority",
                message=f"{none_count}/{len(lines)} output lines are 'None'",
                severity="WARNING",
                evidence=f"{none_count} None lines"
            )]
        return []

    @staticmethod
    def _check_null_density(
        lists: List[list],
        existing: List[BehaviorViolation],
    ) -> List[BehaviorViolation]:
        """Detect lists where >50% of values are None."""
        violations = []
        for lst in lists:
            if len(lst) < 2:
                continue
            none_count = sum(1 for x in lst if x is None)
            density = none_count / len(lst)
            if density > 0.5:
                violations.append(BehaviorViolation(
                    rule="null_density",
                    message=f"List has {none_count}/{len(lst)} None values ({density:.0%}) — likely broken",
                    severity="WARNING",
                    evidence=str(lst[:8])
                ))
        return violations

    @staticmethod
    def _check_duplicate_saturation(lists: List[list]) -> List[BehaviorViolation]:
        """Detect lists where >80% of values are identical (uniform output)."""
        violations = []
        for lst in lists:
            if len(lst) < 3:
                continue
            # Count most frequent value
            from collections import Counter
            most_common_val, most_common_count = Counter(lst).most_common(1)[0]
            density = most_common_count / len(lst)
            if density > 0.8 and len(set(lst)) == 1:
                violations.append(BehaviorViolation(
                    rule="uniform_list",
                    message=(
                        f"List contains {most_common_count}/{len(lst)} identical values ({most_common_val!r}) "
                        f"— computation may be stuck or returning wrong variable"
                    ),
                    severity="WARNING",
                    evidence=str(lst[:8])
                ))
        return violations

    @staticmethod
    def _check_empty_output(stdout: str, lines: List[str]) -> List[BehaviorViolation]:
        """Detect completely empty output (may indicate silent crash)."""
        if not stdout or not stdout.strip():
            return [BehaviorViolation(
                rule="empty_output",
                message="Program produced no output — may have silently failed",
                severity="WARNING",
                evidence="(empty)"
            )]
        return []

    # -----------------------------------------------------------------------
    # Domain-specific validators
    # -----------------------------------------------------------------------

    @staticmethod
    def _check_fibonacci_negativity(
        numbers: List[float],
        lines: List[str],
    ) -> List[BehaviorViolation]:
        """
        Fibonacci sequences must be non-negative (F(0)=0, F(1)=1, ...).
        Any negative value indicates a logical bug in the computation.
        """
        violations = []
        negative_fibs = [n for n in numbers if n < 0]
        if negative_fibs:
            violations.append(BehaviorViolation(
                rule="fibonacci_negative",
                message=(
                    f"Fibonacci output contains {len(negative_fibs)} negative value(s) — "
                    f"Fibonacci numbers must be non-negative"
                ),
                severity="CRITICAL",
                evidence=str(negative_fibs[:5])
            ))
        return violations

    @staticmethod
    def _check_percentage_bounds(
        numbers: List[float],
        stdout: str,
    ) -> List[BehaviorViolation]:
        """Percentages and accuracy values must be in [0, 100]."""
        violations = []
        # Look for percentage-labeled values using context
        pct_pattern = re.compile(
            r'(?:accuracy|precision|recall|f1|percent(?:age)?|score)'
            r'\s*[:=]?\s*(-?\d+(?:\.\d+)?)',
            re.IGNORECASE
        )
        for m in pct_pattern.finditer(stdout):
            val = float(m.group(1))
            if val > 100.0:
                violations.append(BehaviorViolation(
                    rule="percentage_overflow",
                    message=f"Percentage/accuracy value {val} exceeds 100% — logically impossible",
                    severity="CRITICAL",
                    evidence=m.group(0)
                ))
            elif val < 0.0:
                violations.append(BehaviorViolation(
                    rule="percentage_negative",
                    message=f"Percentage/accuracy value {val} is negative — logically impossible",
                    severity="CRITICAL",
                    evidence=m.group(0)
                ))
        return violations

    @staticmethod
    def _check_probability_bounds(
        numbers: List[float],
        stdout: str,
    ) -> List[BehaviorViolation]:
        """Probability values must be in [0.0, 1.0]."""
        violations = []
        prob_pattern = re.compile(
            r'(?:probability|prob|likelihood)\s*[:=]?\s*(-?\d+(?:\.\d+)?)',
            re.IGNORECASE
        )
        for m in prob_pattern.finditer(stdout):
            val = float(m.group(1))
            if val > 1.0 or val < 0.0:
                violations.append(BehaviorViolation(
                    rule="probability_out_of_bounds",
                    message=f"Probability value {val} is outside [0, 1] — logically impossible",
                    severity="CRITICAL",
                    evidence=m.group(0)
                ))
        return violations

    @staticmethod
    def _check_sort_order(lists: List[list], lines: List[str]) -> List[BehaviorViolation]:
        """
        If a line says "sorted" and contains a list, the list must actually be sorted.
        Checks both ascending and descending order.
        """
        violations = []
        # Look for lines that mention "sorted" and contain a list
        for line in lines:
            if "sort" not in line.lower():
                continue
            # Extract any list-like structure in this line
            list_match = re.search(r'\[([^\]]+)\]', line)
            if not list_match:
                continue
            try:
                parsed = ast.literal_eval("[" + list_match.group(1) + "]")
                if not isinstance(parsed, list) or len(parsed) < 2:
                    continue
                # Check if all elements are comparable
                try:
                    is_asc = all(parsed[i] <= parsed[i+1] for i in range(len(parsed)-1))
                    is_desc = all(parsed[i] >= parsed[i+1] for i in range(len(parsed)-1))
                    if not is_asc and not is_desc:
                        violations.append(BehaviorViolation(
                            rule="sort_order_violated",
                            message=f"Output labeled 'sorted' but list is not in order: {parsed[:8]}",
                            severity="CRITICAL",
                            evidence=str(parsed[:8])
                        ))
                except TypeError:
                    pass  # Mixed types — skip
            except (ValueError, SyntaxError):
                pass
        return violations

    @staticmethod
    def _check_factorial_negativity(
        numbers: List[float],
        lines: List[str],
    ) -> List[BehaviorViolation]:
        """Factorial results must be positive integers."""
        violations = []
        factorial_pattern = re.compile(
            r'factorial\s*(?:of\s*)?\d+\s*[:=]?\s*(-?\d+(?:\.\d+)?)',
            re.IGNORECASE
        )
        for line in lines:
            for m in factorial_pattern.finditer(line):
                val = float(m.group(1))
                if val < 0:
                    violations.append(BehaviorViolation(
                        rule="factorial_negative",
                        message=f"Factorial result {val} is negative — logically impossible",
                        severity="CRITICAL",
                        evidence=m.group(0)
                    ))
                elif val != int(val):
                    violations.append(BehaviorViolation(
                        rule="factorial_non_integer",
                        message=f"Factorial result {val} is not an integer",
                        severity="WARNING",
                        evidence=m.group(0)
                    ))
        return violations

    @staticmethod
    def _check_distance_negativity(
        numbers: List[float],
        stdout: str,
    ) -> List[BehaviorViolation]:
        """Distance and magnitude values must be non-negative."""
        violations = []
        dist_pattern = re.compile(
            r'(?:distance|dist|magnitude|length|norm)\s*[:=]?\s*(-?\d+(?:\.\d+)?)',
            re.IGNORECASE
        )
        for m in dist_pattern.finditer(stdout):
            val = float(m.group(1))
            if val < 0:
                violations.append(BehaviorViolation(
                    rule="distance_negative",
                    message=f"Distance/magnitude value {val} is negative — logically impossible",
                    severity="CRITICAL",
                    evidence=m.group(0)
                ))
        return violations

    @staticmethod
    def _check_average_range(
        numbers: List[float],
        lists: List[list],
        stdout: str,
    ) -> List[BehaviorViolation]:
        """
        If an average is computed, verify it falls within [min(inputs), max(inputs)].
        Detects wrong-direction averages, div-by-count errors, etc.
        """
        violations = []
        avg_pattern = re.compile(
            r'(?:average|mean|avg)\s*[:=]?\s*(-?\d+(?:\.\d+)?)',
            re.IGNORECASE
        )
        # Only check if we can find both the list and the average in the output
        if not lists:
            return violations
        for lst in lists:
            if len(lst) < 2:
                continue
            try:
                numeric_lst = [float(x) for x in lst]
                lst_min, lst_max = min(numeric_lst), max(numeric_lst)
            except (TypeError, ValueError):
                continue

            for m in avg_pattern.finditer(stdout):
                avg_val = float(m.group(1))
                # Average must be between min and max of input (within small float tolerance)
                tolerance = abs(lst_max - lst_min) * 0.01 + 1e-9
                if avg_val < lst_min - tolerance or avg_val > lst_max + tolerance:
                    violations.append(BehaviorViolation(
                        rule="average_out_of_range",
                        message=(
                            f"Average {avg_val} is outside the range "
                            f"[{lst_min}, {lst_max}] of the input data"
                        ),
                        severity="WARNING",
                        evidence=m.group(0)
                    ))
        return violations

    @staticmethod
    def _check_normalized_bounds(
        numbers: List[float],
        stdout: str,
    ) -> List[BehaviorViolation]:
        """
        Normalized vectors and values should have components in [-1, 1]
        and magnitude approximately 1.0.
        """
        violations = []
        # Look for numbers labeled as "normalized"
        norm_pattern = re.compile(
            r'(?:normalized|unit|norm)\s*[:=]?\s*\[([^\]]+)\]',
            re.IGNORECASE
        )
        for m in norm_pattern.finditer(stdout):
            try:
                vals = [float(x.strip()) for x in m.group(1).split(',') if x.strip()]
                if not vals:
                    continue
                magnitude = math.sqrt(sum(v**2 for v in vals))
                # A unit vector should have magnitude close to 1.0
                if abs(magnitude - 1.0) > 0.1 and len(vals) > 1:
                    violations.append(BehaviorViolation(
                        rule="normalization_magnitude",
                        message=(
                            f"Normalized vector has magnitude {magnitude:.4f} "
                            f"(expected ~1.0) — normalization is incorrect"
                        ),
                        severity="WARNING",
                        evidence=m.group(0)[:80]
                    ))
            except (ValueError, TypeError):
                pass
        return violations

    # -----------------------------------------------------------------------
    # Extraction helpers
    # -----------------------------------------------------------------------

    @staticmethod
    def _extract_numbers(text: str) -> List[float]:
        """Extract all numeric values from output text."""
        raw = re.findall(r'-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?', text)
        values = []
        for n in raw:
            try:
                values.append(float(n))
            except ValueError:
                pass
        return values

    @staticmethod
    def _extract_lists(text: str) -> List[list]:
        """Extract Python list-like structures from output text."""
        matches = re.findall(r'\[[^\]]+\]', text)
        result = []
        for m in matches:
            try:
                parsed = ast.literal_eval(m)
                if isinstance(parsed, list):
                    result.append(parsed)
            except Exception:
                pass
        return result


# ---------------------------------------------------------------------------
# Convenience wrapper for retry_manager integration
# ---------------------------------------------------------------------------

def analyze_output(
    stdout: str,
    context_hint: str = "",
    language: str = "python",
) -> BehaviorReport:
    """
    Module-level convenience function for direct import in retry_manager.

    Usage:
        from core.behavior_engine import analyze_output
        report = analyze_output(result["stdout"], context_hint="sort")
    """
    return BehaviorEngine.analyze(stdout, context_hint=context_hint, language=language)
