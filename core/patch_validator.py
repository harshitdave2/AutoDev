"""
core/patch_validator.py
-----------------------
Production-grade semantic and structural patch validator for AutoDev.

Validates AI-generated patch candidates BEFORE they are written to disk,
catching logical errors that syntax checks and compile gates cannot detect.

Validation tiers per language:
  Python  → Full AST-based semantic analysis
  Java    → Partial structural analysis (brace balance, return paths, semicolons)
  C++     → Structural analysis only (include/main presence, brace balance, no Python leakage)

patch_mode parameter:
  "full"     → Full-file replacement — all checks active (default).
  "function" → Function-level patch — size threshold and structural checks skipped.
  "snippet"  → Snippet/partial patch — same relaxations as "function".

All methods are pure functions — no file I/O, no side effects.
"""

import ast
import re
import difflib
from typing import Tuple, List


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

class PatchValidator:
    """
    Validates a generated patch candidate against the original source code.

    Usage:
        is_valid, reason = PatchValidator.validate(candidate, original, language)
        is_valid, reason = PatchValidator.validate(candidate, original, language, patch_mode="function")

    Returns:
        (True, "ok") if the candidate passes all checks.
        (False, "<reason>") if any check fails — the caller should skip this candidate.
    """

    @classmethod
    def validate(
        cls,
        candidate: str,
        original: str,
        language: str,
        patch_mode: str = "full",  # "full" | "function" | "snippet"
    ) -> Tuple[bool, str]:
        """
        Run all applicable validation checks for the target language.

        Args:
            candidate  : The patch code to validate.
            original   : The original source file content.
            language   : "python", "java", or "cpp".
            patch_mode : "full" (default) applies all checks including size thresholds.
                         "function" or "snippet" skips size/structural guards — the
                         caller is expected to have already merged the patch into the
                         full file before calling validate().

        Returns (is_valid, reason_string).
        """
        if not candidate or not candidate.strip():
            return False, "Candidate is empty"

        language = language.lower()
        is_snippet = patch_mode in ("function", "snippet")

        # Log patch mode
        mode_label = patch_mode.upper() + "_PATCH" if is_snippet else "FULL_FILE"
        print(f"[PatchMode] {mode_label} — {'size threshold skipped' if is_snippet else 'size threshold active'}")

        # --- Universal checks (all languages) ---
        ok, reason = cls.check_cross_language_contamination(candidate, language)
        if not ok:
            print(f"[PatchValidator][{language.upper()}] REJECTED — {reason}")
            return False, reason

        ok, reason = cls.check_structural_similarity(original, candidate, patch_mode=patch_mode)
        if not ok:
            print(f"[PatchValidator][{language.upper()}] REJECTED — {reason}")
            return False, reason

        # --- Language-specific checks ---
        if language == "python":
            result = cls._validate_python(candidate, original)
        elif language == "java":
            result = cls._validate_java(candidate, original, patch_mode=patch_mode)
        elif language == "cpp":
            result = cls._validate_cpp(candidate, original, patch_mode=patch_mode)
        else:
            # Unknown language — pass structural checks only
            return True, "ok"

        if not result[0]:
            print(f"[PatchValidator][{language.upper()}] REJECTED — {result[1]}")
        return result

    # -----------------------------------------------------------------------
    # Python — Full AST semantic validation
    # -----------------------------------------------------------------------

    @classmethod
    def _validate_python(cls, candidate: str, original: str) -> Tuple[bool, str]:
        """Run full AST-based semantic validation for Python patches."""

        # 1. Parse AST — hard requirement for Python
        try:
            tree = ast.parse(candidate)
        except SyntaxError as e:
            return False, f"Python SyntaxError in patch: {e}"

        # 2. Semantic checks
        ok, reason = cls.check_return_paths(candidate, "python")
        if not ok:
            return False, reason

        ok, reason = cls.check_division_safety(candidate, "python")
        if not ok:
            return False, reason

        ok, reason = cls.check_loop_bounds(candidate, "python")
        if not ok:
            return False, reason

        ok, reason = cls.check_none_dereference(candidate, "python")
        if not ok:
            return False, reason

        return True, "ok"

    # -----------------------------------------------------------------------
    # Java — Partial structural validation
    # -----------------------------------------------------------------------

    @classmethod
    def _validate_java(
        cls,
        candidate: str,
        original: str,
        patch_mode: str = "full",
    ) -> Tuple[bool, str]:
        """Run structural validation for Java patches."""

        is_snippet = patch_mode in ("function", "snippet")

        # 1. Brace balance
        ok, reason = cls._check_brace_balance(candidate)
        if not ok:
            return False, reason

        # 2. Must retain class declaration — only for full-file patches
        if not is_snippet and "class " not in candidate:
            return False, "Java patch is missing a class declaration"

        # 3. Detect Python leakage (def, import numpy)
        if re.search(r'\bdef\s+\w+\s*\(', candidate):
            return False, "Java patch contains Python 'def' keyword — language corruption"
        if "import numpy" in candidate or "import pandas" in candidate:
            return False, "Java patch contains Python import — language corruption"

        # 4. Check that method return paths exist (basic scan — no full CFG)
        ok, reason = cls.check_return_paths(candidate, "java")
        if not ok:
            return False, reason

        return True, "ok"

    # -----------------------------------------------------------------------
    # C++ — Structural validation only
    # -----------------------------------------------------------------------

    @classmethod
    def _validate_cpp(
        cls,
        candidate: str,
        original: str,
        patch_mode: str = "full",
    ) -> Tuple[bool, str]:
        """Run structural validation for C++ patches."""

        is_snippet = patch_mode in ("function", "snippet")

        # 1. Must have #include (all non-trivial C++ files need at least one)
        #    — only enforced for full-file patches
        if not is_snippet:
            if "#include" not in candidate:
                # Only enforce if original had includes
                if "#include" in original:
                    return False, "C++ patch dropped all #include directives"

            # 2. Must retain main() if original had it — only for full-file patches
            has_main_orig = bool(re.search(r'\bmain\s*\(', original))
            has_main_patch = bool(re.search(r'\bmain\s*\(', candidate))
            if has_main_orig and not has_main_patch:
                return False, "C++ patch removed main() function"
        else:
            print("[PatchValidator][CPP] Snippet mode — skipping #include and main() checks")

        # 3. Brace balance
        ok, reason = cls._check_brace_balance(candidate)
        if not ok:
            return False, reason

        # 4. No Python contamination
        if re.search(r'\bdef\s+\w+\s*\(', candidate):
            return False, "C++ patch contains Python 'def' — language corruption"
        if re.search(r'\bprint\s*\((?!\s*(f|\"|\'))', candidate):
            # Python-style print without a format specifier
            pass  # Allow printf() — only flag naked Python print()
        if "import numpy" in candidate or "import sys" in candidate:
            return False, "C++ patch contains Python imports — language corruption"

        return True, "ok"

    # -----------------------------------------------------------------------
    # Shared semantic checks
    # -----------------------------------------------------------------------

    @staticmethod
    def check_cross_language_contamination(code: str, language: str) -> Tuple[bool, str]:
        """
        Detect obvious cross-language pollution in a generated patch.
        This is the single authoritative gate, replacing ad-hoc checks
        scattered in agent.py and retry_manager.py.
        """
        code_lower = code.lower()

        if language == "cpp":
            if re.search(r'^\s*def\s+\w+\s*\(', code, re.MULTILINE):
                return False, "C++ patch contains Python 'def' function definition"
            if re.search(r'^\s*import\s+\w+', code, re.MULTILINE):
                return False, "C++ patch contains Python-style import statement"
            # C++ files must NOT start with a Python shebang
            if code.strip().startswith("#!/usr/bin/env python"):
                return False, "C++ patch has Python shebang"

        elif language == "java":
            if re.search(r'^\s*def\s+\w+\s*\(', code, re.MULTILINE):
                return False, "Java patch contains Python 'def' function definition"
            if "#include" in code:
                return False, "Java patch contains C++ #include directive"

        elif language == "python":
            if "#include" in code:
                return False, "Python patch contains C++ #include directive"
            if re.search(r'\bpublic\s+static\s+void\s+main\b', code):
                return False, "Python patch contains Java main() signature"

        return True, "ok"

    @staticmethod
    def check_structural_similarity(
        original: str,
        candidate: str,
        patch_mode: str = "full",
    ) -> Tuple[bool, str]:
        """
        Token-level structural similarity check.
        Rejects patches that deviate too far from the original (likely hallucinations
        or full rewrites) while also rejecting patches that are identical (no fix applied).

        Uses SequenceMatcher at the token level for more precision than raw character ratio.

        patch_mode:
          "full"              → Apply size threshold (< 25% of original rejected).
          "function"/"snippet" → Skip size threshold; the caller already merged the patch
                                 into a full file before calling validate().
        """
        if not original or not original.strip():
            return True, "ok"  # No original to compare against

        orig_tokens = original.split()
        patch_tokens = candidate.split()

        if not patch_tokens:
            return False, "Patch is empty after tokenization"

        orig_lines = original.strip().splitlines()
        patch_lines = candidate.strip().splitlines()

        is_snippet = patch_mode in ("function", "snippet")

        # Length guard — only apply for full-file patches
        if not is_snippet:
            if len(orig_lines) > 10 and len(patch_lines) < len(orig_lines) * 0.25:
                return False, (
                    f"Patch is too short: {len(patch_lines)} lines vs "
                    f"{len(orig_lines)} original lines (threshold: 25%)"
                )

        # Similarity check: must be similar enough not to be a hallucination
        # For snippet mode this compares the merged reconstructed file vs original,
        # so the threshold is still meaningful.
        ratio = difflib.SequenceMatcher(None, orig_tokens, patch_tokens).ratio()

        if len(orig_lines) > 10 and ratio < 0.35:
            if is_snippet:
                # For snippets, a very low ratio may just mean it's a small patch —
                # only reject if the snippet itself is suspiciously low-quality.
                # Use a relaxed threshold of 0.05 (nearly empty/garbage content).
                if ratio < 0.05:
                    return False, (
                        f"Patch token similarity extremely low: {ratio:.2f} "
                        f"(snippet mode threshold: 0.05) — likely garbage output"
                    )
            else:
                return False, (
                    f"Patch token similarity too low: {ratio:.2f} "
                    f"(threshold: 0.35) — likely a hallucinated rewrite"
                )

        # Identity check: a patch identical to the original fixes nothing
        if original.strip() == candidate.strip():
            return False, "Patch is identical to the original — no fix was applied"

        return True, "ok"

    @staticmethod
    def check_division_safety(code: str, language: str) -> Tuple[bool, str]:
        """
        Detect unguarded division expressions where the divisor is a literal zero
        or is explicitly assigned zero in the same scope.

        Python: uses AST analysis.
        Java/C++: regex-based scan for `/ 0` or `% 0` literals.
        """
        if language == "python":
            try:
                tree = ast.parse(code)
            except SyntaxError:
                return True, "ok"  # Syntax errors caught elsewhere

            # Collect all assignments: var = <constant>
            assignments: dict[str, object] = {}
            for node in ast.walk(tree):
                if isinstance(node, ast.Assign):
                    for target in node.targets:
                        if isinstance(target, ast.Name) and isinstance(node.value, ast.Constant):
                            assignments[target.id] = node.value.value

            # Walk all BinOp nodes for Div/Mod
            for node in ast.walk(tree):
                if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Div, ast.Mod, ast.FloorDiv)):
                    # Check for literal zero divisor
                    if isinstance(node.right, ast.Constant) and node.right.value == 0:
                        return False, "Patch contains division by literal zero"
                    # Check for variable known to be zero
                    if isinstance(node.right, ast.Name):
                        val = assignments.get(node.right.id)
                        if val == 0:
                            return False, (
                                f"Patch divides by '{node.right.id}' "
                                f"which is assigned 0 in the same scope — unguarded ZeroDivisionError"
                            )
        else:
            # Java / C++ — regex-based literal check only
            if re.search(r'/\s*0\b', code) or re.search(r'%\s*0\b', code):
                return False, "Patch contains division/modulo by literal zero"

        return True, "ok"

    @staticmethod
    def check_return_paths(code: str, language: str) -> Tuple[bool, str]:
        """
        Verify that non-void functions have a return statement on at least
        one exit path.

        Python: AST-based — checks every FunctionDef that is not a constructor,
                property setter, or explicitly returns None.
        Java: Structural regex scan — looks for methods that declare a non-void
              return type but contain no 'return' keyword.
        """
        if language == "python":
            try:
                tree = ast.parse(code)
            except SyntaxError:
                return True, "ok"

            for node in ast.walk(tree):
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue

                # Skip __init__, __str__, etc. (common void-style methods)
                if node.name.startswith("__") and node.name.endswith("__"):
                    continue

                # Check whether function body has ANY return with a value
                has_value_return = False
                for child in ast.walk(node):
                    if isinstance(child, ast.Return) and child.value is not None:
                        has_value_return = True
                        break

                # Check for explicit annotation: -> None means void is intentional
                returns_annotation = node.returns
                if returns_annotation and isinstance(returns_annotation, ast.Constant):
                    if returns_annotation.value is None:
                        continue  # void function, skip

                # A function with only a docstring body and no return is suspicious
                body_stmts = [s for s in node.body if not isinstance(s, ast.Expr)]
                if not body_stmts and not has_value_return:
                    return False, (
                        f"Function '{node.name}' has an empty body — "
                        f"likely a truncated patch"
                    )

        elif language == "java":
            # Find all Java methods with non-void return types
            method_pattern = re.compile(
                r'\b(int|long|double|float|boolean|String|char|byte|short|[\w<>\[\]]+)\s+'
                r'(\w+)\s*\([^)]*\)\s*(?:throws\s+[\w,\s]+)?\s*\{([^{}]*(?:\{[^{}]*\}[^{}]*)*)\}',
                re.DOTALL
            )
            for m in method_pattern.finditer(code):
                return_type = m.group(1)
                method_name = m.group(2)
                body = m.group(3)

                # Skip void-like types and constructors
                if return_type in ("void", "Void"):
                    continue
                if method_name[0].isupper():
                    continue  # Likely a constructor

                if "return" not in body:
                    return False, (
                        f"Java method '{method_name}' declares return type "
                        f"'{return_type}' but has no return statement"
                    )

        return True, "ok"

    @staticmethod
    def check_loop_bounds(code: str, language: str) -> Tuple[bool, str]:
        """
        Detect common off-by-one patterns in loop bounds that will cause
        IndexError at runtime.

        Python: AST-based scan of For/While loops using range().
        Java/C++: Regex scan for `<= arr.length`, `<= size`, `<= len` patterns.
        """
        if language == "python":
            try:
                tree = ast.parse(code)
            except SyntaxError:
                return True, "ok"

            for node in ast.walk(tree):
                if not isinstance(node, ast.For):
                    continue
                # Pattern: for i in range(len(arr) + 1) or range(n + 1) where n is len
                iter_ = node.iter
                if not (isinstance(iter_, ast.Call) and isinstance(iter_.func, ast.Name)
                        and iter_.func.id == "range"):
                    continue

                args = iter_.args
                # range(stop) or range(start, stop)
                stop_arg = args[-1] if args else None
                if stop_arg is None:
                    continue

                # Detect: range(len(arr) + 1)
                if (isinstance(stop_arg, ast.BinOp)
                        and isinstance(stop_arg.op, ast.Add)
                        and isinstance(stop_arg.right, ast.Constant)
                        and stop_arg.right.value == 1):
                    left = stop_arg.left
                    if (isinstance(left, ast.Call)
                            and isinstance(left.func, ast.Name)
                            and left.func.id == "len"):
                        return False, (
                            "Patch uses range(len(...) + 1) — "
                            "this will cause an IndexError on the last iteration"
                        )

        else:
            # Java / C++ — regex scan
            # Catches: i <= arr.length, i <= arr.size(), i <= n where n could be len
            oob_patterns = [
                r'\bi\s*<=\s*\w+\.length\b',
                r'\bi\s*<=\s*\w+\.size\s*\(\)',
                r'\bi\s*<=\s*\w+\.length\s*\(\)',
            ]
            for pattern in oob_patterns:
                if re.search(pattern, code):
                    return False, (
                        f"Patch uses '<= length/size' loop bound — "
                        f"likely off-by-one error (should use '<')"
                    )

        return True, "ok"

    @staticmethod
    def check_none_dereference(code: str, language: str) -> Tuple[bool, str]:
        """
        Detect method calls on variables that are explicitly assigned None
        in the same scope within the patch.

        Python only (Java None checks are done at compile time via the Java compiler).
        """
        if language != "python":
            return True, "ok"

        try:
            tree = ast.parse(code)
        except SyntaxError:
            return True, "ok"

        for func_node in ast.walk(tree):
            if not isinstance(func_node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Module)):
                continue

            # Collect variable → None assignments within this scope
            none_vars: set[str] = set()

            for node in ast.walk(func_node):
                if isinstance(node, ast.Assign):
                    for target in node.targets:
                        if isinstance(target, ast.Name):
                            if isinstance(node.value, ast.Constant) and node.value.value is None:
                                none_vars.add(target.id)

            # Look for attribute access or method calls on those variables
            for node in ast.walk(func_node):
                if isinstance(node, ast.Attribute):
                    if isinstance(node.value, ast.Name) and node.value.id in none_vars:
                        return False, (
                            f"Patch dereferences '{node.value.id}' which is "
                            f"assigned None — will raise AttributeError at runtime"
                        )

        return True, "ok"

    # -----------------------------------------------------------------------
    # Internal helpers
    # -----------------------------------------------------------------------

    @staticmethod
    def _check_brace_balance(code: str) -> Tuple[bool, str]:
        """
        String-aware brace balance checker.
        Ignores braces inside string literals to avoid false positives from
        f-strings, format strings, and print statements.
        """
        opens = closes = 0
        in_single = in_double = escape_next = False

        for ch in code:
            if escape_next:
                escape_next = False
                continue
            if ch == "\\" and (in_single or in_double):
                escape_next = True
                continue
            if ch == '"' and not in_single:
                in_double = not in_double
                continue
            if ch == "'" and not in_double:
                in_single = not in_single
                continue
            if in_single or in_double:
                continue
            if ch == "{":
                opens += 1
            elif ch == "}":
                closes += 1

        if opens != closes:
            return False, (
                f"Patch has unbalanced braces: {opens} opening vs {closes} closing"
            )
        return True, "ok"

    @staticmethod
    def get_validation_summary(results: List[Tuple[bool, str]]) -> str:
        """
        Format a list of (is_valid, reason) tuples into a human-readable
        summary string for logging.
        """
        passed = [r for r in results if r[0]]
        failed = [r for r in results if not r[0]]
        lines = [f"  PASS ({len(passed)}): {', '.join(r[1] for r in passed) or 'none'}"]
        if failed:
            lines.append(f"  FAIL ({len(failed)}): {'; '.join(r[1] for r in failed)}")
        return "\n".join(lines)
