"""
core/confidence_engine.py
--------------------------
Real percentage-based confidence scoring for AutoDev.

Replaces the coarse HIGH / MEDIUM / LOW confidence labels with a
precise 0-100% score that reflects the actual quality of a repair,
factoring in syntax validity, semantic checks, regression absence,
behavioral improvement, patch conservatism, and retry count.

Score breakdown (maximum 100 points):
  +20  syntax_valid        -- patch parses without errors
  +20  semantic_valid      -- semantic checks all passed
  +20  no_regression       -- no regressions detected by RegressionGuard
  +15  behavior_improved   -- BehaviorFingerprint delta > 0 (output changed)
  +10  patch_conservative  -- similarity in optimal range [0.4, 0.9]
  +10  no_hallucination    -- no cross-language contamination
  +05  logic_clean         -- BehaviorEngine found no critical violations
   -5  per_retry_penalty   -- -5 per retry beyond first attempt (capped at -20)

Grade thresholds:
  >= 90  : A  (Excellent)
  >= 75  : B  (Good)
  >= 60  : C  (Acceptable)
  >= 40  : D  (Low confidence)
  <  40  : F  (Very low — consider escalating)

Usage:
    result = ConfidenceEngine.score(
        syntax_valid=True,
        semantic_valid=True,
        regression_report=regression_report,
        behavior_delta=delta,
        behavior_report=behavior_report,
        similarity_ratio=0.75,
        language_safe=True,
        attempt_number=1,
    )
    print(f"{result.score:.1f}% ({result.grade})")
    print(result.breakdown)
"""

from dataclasses import dataclass, field
from typing import Dict, Optional, Any
import difflib


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class ConfidenceResult:
    """
    Complete confidence scoring result for a patch candidate.

    Attributes:
        score      : Percentage score (0.0 - 100.0).
        grade      : Letter grade (A, B, C, D, F).
        label      : Human-readable confidence label.
        breakdown  : Dict mapping factor name -> points awarded.
        summary    : One-line formatted string for display.
    """
    score: float
    grade: str
    label: str
    breakdown: Dict[str, float]
    summary: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "score": round(self.score, 1),
            "grade": self.grade,
            "label": self.label,
            "breakdown": {k: round(v, 1) for k, v in self.breakdown.items()},
            "summary": self.summary,
        }

    def __str__(self) -> str:
        return self.summary


# ---------------------------------------------------------------------------
# Scoring engine
# ---------------------------------------------------------------------------

class ConfidenceEngine:
    """
    Computes real percentage confidence scores for patch repair attempts.

    All parameters are optional — missing information defaults to 0 points
    for that factor, rather than crashing the scoring pipeline.
    """

    # Factor weights (maximum points per factor)
    _WEIGHTS = {
        "syntax_valid":       20.0,
        "semantic_valid":     20.0,
        "no_regression":      20.0,
        "behavior_improved":  15.0,
        "patch_conservative": 10.0,
        "no_hallucination":   10.0,
        "logic_clean":         5.0,
    }

    # Retry penalty per attempt beyond the first (capped)
    _RETRY_PENALTY = 5.0
    _MAX_RETRY_PENALTY = 20.0

    # Grade thresholds
    _GRADE_THRESHOLDS = [
        (90.0, "A", "Excellent"),
        (75.0, "B", "Good"),
        (60.0, "C", "Acceptable"),
        (40.0, "D", "Low"),
        (0.0,  "F", "Very Low"),
    ]

    @classmethod
    def score(
        cls,
        syntax_valid: bool = False,
        semantic_valid: bool = False,
        regression_report: Optional[Any] = None,  # RegressionReport
        behavior_delta: float = 0.0,
        behavior_report: Optional[Any] = None,    # BehaviorReport
        similarity_ratio: float = 0.0,
        language_safe: bool = True,
        attempt_number: int = 1,
        original_code: str = "",
        patched_code: str = "",
    ) -> ConfidenceResult:
        """
        Compute the composite confidence score for a patch.

        Args:
            syntax_valid     : Whether the patch passed syntax validation.
            semantic_valid   : Whether the patch passed semantic validation.
            regression_report: RegressionReport from RegressionGuard (or None).
            behavior_delta   : BehaviorFingerprint delta score (0 = no change).
            behavior_report  : BehaviorReport from BehaviorEngine (or None).
            similarity_ratio : Token-level similarity to original (0.0-1.0).
            language_safe    : Whether cross-language contamination check passed.
            attempt_number   : Which retry attempt produced this patch (1-indexed).
            original_code    : Original source for similarity re-computation if ratio not given.
            patched_code     : Patched source for similarity re-computation.

        Returns:
            ConfidenceResult with score, grade, breakdown, and summary.
        """
        breakdown: Dict[str, float] = {}

        # --- Factor 1: Syntax validity ---
        breakdown["syntax_valid"] = cls._WEIGHTS["syntax_valid"] if syntax_valid else 0.0

        # --- Factor 2: Semantic validity ---
        breakdown["semantic_valid"] = cls._WEIGHTS["semantic_valid"] if semantic_valid else 0.0

        # --- Factor 3: No regression ---
        no_reg = True
        if regression_report is not None:
            # Works with RegressionReport dataclass (has_regression attr)
            no_reg = not getattr(regression_report, "has_regression", False)
        breakdown["no_regression"] = cls._WEIGHTS["no_regression"] if no_reg else 0.0

        # --- Factor 4: Behavior improved ---
        behavior_improved = behavior_delta > 0.0
        if behavior_improved:
            # Scale the award by how much behavior changed (capped at max weight)
            # delta of 1.0 = 50% of max, delta of 3.0+ = 100% of max
            scale = min(1.0, behavior_delta / 3.0)
            breakdown["behavior_improved"] = cls._WEIGHTS["behavior_improved"] * scale
        else:
            breakdown["behavior_improved"] = 0.0

        # --- Factor 5: Patch conservatism ---
        # Compute similarity if not provided but code strings are
        if similarity_ratio == 0.0 and original_code and patched_code:
            orig_tokens = original_code.split()
            patch_tokens = patched_code.split()
            if orig_tokens and patch_tokens:
                similarity_ratio = difflib.SequenceMatcher(
                    None, orig_tokens, patch_tokens
                ).ratio()

        # Optimal range: [0.4, 0.9]
        # Too low (<0.3) = likely rewrite/hallucination
        # Too high (>0.95) = identical = no fix
        if 0.4 <= similarity_ratio <= 0.9:
            # Score peaks at 0.7 similarity
            distance_from_peak = abs(similarity_ratio - 0.7)
            conservatism_score = max(0.0, 1.0 - distance_from_peak / 0.3)
            breakdown["patch_conservative"] = cls._WEIGHTS["patch_conservative"] * conservatism_score
        elif similarity_ratio > 0.95:
            breakdown["patch_conservative"] = 0.0  # Too similar = no fix
        elif similarity_ratio < 0.3:
            breakdown["patch_conservative"] = 0.0  # Too different = hallucination
        else:
            # In transition zones — partial score
            breakdown["patch_conservative"] = cls._WEIGHTS["patch_conservative"] * 0.4

        # --- Factor 6: No cross-language hallucination ---
        breakdown["no_hallucination"] = cls._WEIGHTS["no_hallucination"] if language_safe else 0.0

        # --- Factor 7: Logic cleanliness ---
        logic_clean = True
        if behavior_report is not None:
            logic_clean = getattr(behavior_report, "is_logically_valid", True)
        breakdown["logic_clean"] = cls._WEIGHTS["logic_clean"] if logic_clean else 0.0

        # --- Retry penalty ---
        retry_penalty = min(
            cls._MAX_RETRY_PENALTY,
            max(0, attempt_number - 1) * cls._RETRY_PENALTY
        )
        breakdown["retry_penalty"] = -retry_penalty

        # --- Compute total ---
        raw_total = sum(breakdown.values())
        # Clamp to [0, 100]
        score = max(0.0, min(100.0, raw_total))

        # --- Determine grade ---
        grade, label = cls._get_grade(score)

        summary = (
            f"{score:.1f}% confidence ({grade} — {label}) | "
            f"syntax={syntax_valid}, semantic={semantic_valid}, "
            f"no_regression={no_reg}, attempt={attempt_number}"
        )

        return ConfidenceResult(
            score=round(score, 2),
            grade=grade,
            label=label,
            breakdown=breakdown,
            summary=summary,
        )

    @classmethod
    def score_from_attempt(
        cls,
        attempt_number: int,
        model_name: str = "",
        patch_result: Optional[Dict[str, Any]] = None,
    ) -> ConfidenceResult:
        """
        Simplified scoring for backward compatibility with the existing
        attempt-count-based confidence system.

        Maps retry count to a confidence score in the legacy way,
        but returns a ConfidenceResult for consistent interface.

        Args:
            attempt_number: 1-indexed retry count.
            model_name: Name of the model that produced the fix.
            patch_result: Optional result dict for additional context.

        Returns:
            ConfidenceResult with score derived from attempt count.
        """
        # Legacy mapping: attempt 1 = HIGH (~85%), 2 = MEDIUM (~65%), 3+ = LOW (~40%)
        base_scores = {1: 85.0, 2: 65.0, 3: 45.0}
        score = base_scores.get(attempt_number, max(20.0, 50.0 - attempt_number * 10))
        grade, label = cls._get_grade(score)
        breakdown = {
            "base_from_attempt": score,
            "note": "Legacy score — run full ConfidenceEngine.score() for real scoring",
        }
        return ConfidenceResult(
            score=score,
            grade=grade,
            label=label,
            breakdown=breakdown,
            summary=f"{score:.1f}% confidence ({grade} — {label}) [attempt-based estimate]",
        )

    # -----------------------------------------------------------------------
    # Internal helpers
    # -----------------------------------------------------------------------

    @classmethod
    def _get_grade(cls, score: float):
        """Return (grade_letter, grade_label) for a given score."""
        for threshold, grade, label in cls._GRADE_THRESHOLDS:
            if score >= threshold:
                return grade, label
        return "F", "Very Low"

    @classmethod
    def format_for_display(cls, result: ConfidenceResult) -> str:
        """
        Format a ConfidenceResult for display in the Rich console summary panel.
        Returns a Rich-markup string.
        """
        if result.grade == "A":
            color = "bold green"
        elif result.grade == "B":
            color = "green"
        elif result.grade == "C":
            color = "yellow"
        elif result.grade == "D":
            color = "bold yellow"
        else:
            color = "bold red"

        return f"[{color}]{result.score:.1f}% ({result.grade} — {result.label})[/{color}]"
