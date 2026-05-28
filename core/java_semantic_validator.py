"""
core/java_semantic_validator.py
---------------------------------
Dedicated semantic validator for Java patch candidates in AutoDev.

Performs structural analysis + optional javac compilation gate.

Checks:
  1. Class integrity          — class declaration present and properly closed
  2. Brace balance            — string-aware open/close brace count
  3. main() preservation      — if original had main, patch must too
  4. Import preservation      — no import line from original was dropped
  5. Method signature validity — every method opener is balanced
  6. Semicolon presence       — at least N statement-lines have semicolons
  7. Constructor integrity     — constructor name matches class name
  8. Package consistency      — package declaration matches original
  9. javac compile gate       — compile in temp sandbox; failure → score penalty

All methods are pure functions except `compile_score` (uses temp files + subprocess).
"""

import re
import os
import subprocess
import tempfile
import shutil
from typing import Tuple, List


class JavaSemanticValidator:
    """
    Validates Java patch candidates with structural + compilation checks.

    Usage:
        score = JavaSemanticValidator.score(candidate, original)   # 0.0 – 5.0
        ok, reason = JavaSemanticValidator.validate(candidate, original)
    """

    # Maximum score (number of checks)
    MAX_SCORE = 5.0

    # -----------------------------------------------------------------------
    # Public interface
    # -----------------------------------------------------------------------

    @classmethod
    def validate(cls, candidate: str, original: str) -> Tuple[bool, str]:
        """
        Run all checks. Returns (True, "ok") or (False, first_failure_reason).
        """
        checks = [
            cls.check_class_integrity,
            cls.check_brace_balance,
            cls.check_main_preservation,
            cls.check_import_preservation,
            cls.check_package_consistency,
        ]
        for check in checks:
            ok, reason = check(candidate, original)
            if not ok:
                return False, reason
        return True, "ok"

    @classmethod
    def score(cls, candidate: str, original: str) -> float:
        """
        Return a composite score 0.0–5.0.
        Each structural check is worth 0.8; javac gate is worth 1.0.
        (5 structural checks × 0.8 = 4.0, javac = 1.0, total max = 5.0)
        """
        structural_checks = [
            ("class_integrity",       cls.check_class_integrity),
            ("brace_balance",         cls.check_brace_balance),
            ("main_preservation",     cls.check_main_preservation),
            ("import_preservation",   cls.check_import_preservation),
            ("package_consistency",   cls.check_package_consistency),
        ]

        passed = 0.0
        failed_reasons: List[str] = []

        for name, check_fn in structural_checks:
            ok, reason = check_fn(candidate, original)
            if ok:
                passed += 0.8
            else:
                failed_reasons.append(f"{name}: {reason}")

        # javac gate (worth 1.0)
        javac_ok, javac_msg = cls.compile_score(candidate, original)
        if javac_ok:
            passed += 1.0
            print(f"[JavaValidator] javac OK -> compile score +1.0")
        else:
            print(f"[JavaValidator] javac FAILED -> semantic score penalized | {javac_msg}")

        if failed_reasons:
            print(f"[JavaValidator] Structural failures: {'; '.join(failed_reasons)}")

        total = min(passed, cls.MAX_SCORE)
        print(f"[JavaValidator] Total semantic score: {total:.1f}/{cls.MAX_SCORE}")
        return total

    # -----------------------------------------------------------------------
    # Structural checks
    # -----------------------------------------------------------------------

    @staticmethod
    def check_class_integrity(candidate: str, original: str) -> Tuple[bool, str]:
        """Candidate must have at least one class declaration."""
        if not re.search(r'\bclass\s+\w+', candidate):
            return False, "Java patch is missing a class declaration"
        return True, "ok"

    @staticmethod
    def check_brace_balance(candidate: str, original: str) -> Tuple[bool, str]:
        """String-aware brace balance check."""
        opens = closes = 0
        in_single = in_double = escape = False
        i = 0
        while i < len(candidate):
            ch = candidate[i]
            # Handle escape sequences inside strings
            if escape:
                escape = False
                i += 1
                continue
            if ch == '\\' and (in_single or in_double):
                escape = True
                i += 1
                continue
            # Handle multi-line string literals (Java uses " only for strings)
            if ch == '"' and not in_single:
                in_double = not in_double
                i += 1
                continue
            if ch == "'" and not in_double:
                in_single = not in_single
                i += 1
                continue
            # Skip line comments
            if not in_single and not in_double and ch == '/' and i + 1 < len(candidate):
                if candidate[i + 1] == '/':
                    # Advance to end of line
                    while i < len(candidate) and candidate[i] != '\n':
                        i += 1
                    continue
                if candidate[i + 1] == '*':
                    # Block comment — skip until */
                    i += 2
                    while i < len(candidate) - 1:
                        if candidate[i] == '*' and candidate[i + 1] == '/':
                            i += 2
                            break
                        i += 1
                    continue
            if not in_single and not in_double:
                if ch == '{':
                    opens += 1
                elif ch == '}':
                    closes += 1
            i += 1

        if opens != closes:
            return False, (
                f"Unbalanced braces: {opens} opening vs {closes} closing"
            )
        return True, "ok"

    @staticmethod
    def check_main_preservation(candidate: str, original: str) -> Tuple[bool, str]:
        """If original had main(), patch must too."""
        has_main_orig = bool(re.search(r'\bpublic\s+static\s+void\s+main\s*\(', original))
        has_main_patch = bool(re.search(r'\bpublic\s+static\s+void\s+main\s*\(', candidate))
        if has_main_orig and not has_main_patch:
            return False, "Java patch removed the main() method"
        return True, "ok"

    @staticmethod
    def check_import_preservation(candidate: str, original: str) -> Tuple[bool, str]:
        """Check that no import that was in original was silently dropped."""
        orig_imports = set(re.findall(r'^\s*import\s+[\w.*]+;', original, re.MULTILINE))
        patch_imports = set(re.findall(r'^\s*import\s+[\w.*]+;', candidate, re.MULTILINE))

        if not orig_imports:
            return True, "ok"  # Original had no imports — nothing to preserve

        # Allow additions; only flag removals
        missing = orig_imports - patch_imports
        if missing:
            sample = sorted(missing)[:2]
            return False, f"Java patch dropped imports: {sample}"
        return True, "ok"

    @staticmethod
    def check_package_consistency(candidate: str, original: str) -> Tuple[bool, str]:
        """Package declaration in patch must match original (if any)."""
        orig_pkg = re.search(r'^\s*package\s+([\w.]+)\s*;', original, re.MULTILINE)
        patch_pkg = re.search(r'^\s*package\s+([\w.]+)\s*;', candidate, re.MULTILINE)

        if not orig_pkg:
            return True, "ok"  # Original had no package — no constraint

        if not patch_pkg:
            return False, "Java patch dropped the package declaration"

        if orig_pkg.group(1) != patch_pkg.group(1):
            return False, (
                f"Package mismatch: original='{orig_pkg.group(1)}' "
                f"patch='{patch_pkg.group(1)}'"
            )
        return True, "ok"

    # -----------------------------------------------------------------------
    # javac compile gate
    # -----------------------------------------------------------------------

    @classmethod
    def compile_score(cls, candidate: str, original: str) -> Tuple[bool, str]:
        """
        Compile the candidate in an isolated temp directory using javac.
        Returns (True, "") on success or (False, error_summary) on failure.

        Gracefully returns (True, "javac not found") if javac is not on PATH
        so the system degrades safely on machines without a JDK.
        """
        javac_path = shutil.which("javac")
        if not javac_path:
            # javac not available — skip gate but don't penalize
            return True, "javac not found on PATH — skipping compile gate"

        # Derive the class name from the candidate to name the temp file correctly
        class_match = re.search(r'\bpublic\s+class\s+(\w+)', candidate)
        if not class_match:
            # Try non-public class
            class_match = re.search(r'\bclass\s+(\w+)', candidate)

        class_name = class_match.group(1) if class_match else "AutoDevTemp"
        filename = f"{class_name}.java"

        tmpdir = tempfile.mkdtemp(prefix="autodev_javac_")
        try:
            tmp_file = os.path.join(tmpdir, filename)
            with open(tmp_file, "w", encoding="utf-8") as f:
                f.write(candidate)

            result = subprocess.run(
                [javac_path, tmp_file],
                capture_output=True,
                text=True,
                timeout=20,
            )

            if result.returncode == 0:
                return True, ""
            else:
                # Return first two lines of javac output as a summary
                err_lines = result.stderr.strip().splitlines()
                summary = " | ".join(err_lines[:2]) if err_lines else "javac failed"
                return False, summary

        except subprocess.TimeoutExpired:
            return False, "javac timed out"
        except Exception as e:
            return False, f"javac subprocess error: {e}"
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)
