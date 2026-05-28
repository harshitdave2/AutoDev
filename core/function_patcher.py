"""
core/function_patcher.py
-------------------------
Opt-in function-level patch engine for AutoDev.

Activated via: python autodev.py run <file> --mode function

Instead of replacing the entire file with the AI's output, this module:
  1. Extracts the target function from the AI-generated patch.
  2. Locates the same function in the original file.
  3. Replaces ONLY that function — leaving all unrelated code untouched.

This dramatically reduces the risk surface: only the buggy function is
modified, so unrelated code cannot be accidentally corrupted.

Fallback: if extraction fails (function not found, language not supported
for AST-based extraction, or the function spans the entire file), the
module transparently falls back to full-file replacement.

Language support:
  Python  → AST-based extraction (exact boundary detection)
  Java    → Regex-based extraction (method body + signature)
  C++     → Regex-based extraction (function body + signature)

Usage:
    result = FunctionPatcher.apply(
        patch_target=patch_target,
        patch_code=candidate,
        language=language,
        error_info=tb,
    )
    # result["applied"]       — True if function-level patch was applied
    # result["fallback"]      — True if fell back to full-file replacement
    # result["function_name"] — Name of the extracted function (or "")
    # result["reason"]        — Explanation of what happened
"""

import ast
import re
import os
from typing import Dict, Any, Optional, Tuple


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

class FunctionPatcher:
    """
    Function-level patch applicator.

    All public methods are classmethods — no instantiation needed.
    """

    @classmethod
    def apply(
        cls,
        patch_target: str,
        patch_code: str,
        language: str,
        error_info: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Apply a function-level patch to patch_target.

        Extracts the target function from patch_code, locates it in the
        original file, and replaces only that function in-place.

        Args:
            patch_target : Absolute path to the file to patch.
            patch_code   : Full AI-generated repaired source code.
            language     : "python", "java", or "cpp".
            error_info   : Traceback dict with optional "line" key used as
                           a hint for which function to target.

        Returns:
            Dict with keys:
                applied       (bool)  — True if patch was written to disk.
                fallback      (bool)  — True if full-file fallback was used.
                function_name (str)   — Extracted function name, or "".
                reason        (str)   — Human-readable explanation.
        """
        if not os.path.exists(patch_target):
            return cls._result(applied=False, fallback=False, reason="patch_target does not exist")

        with open(patch_target, "r", encoding="utf-8") as f:
            original_code = f.read()

        if not original_code.strip():
            return cls._result(applied=False, fallback=False, reason="original file is empty")

        crash_line = int(error_info.get("line", 0)) if error_info else 0
        language = language.lower()

        # --- Step 1: Extract target function from the PATCH ---
        patch_func_name, patch_func_src = cls._extract_target_function(
            patch_code, language, crash_line
        )

        if not patch_func_name or not patch_func_src:
            # Cannot extract a function from the patch — full-file fallback
            return cls._full_file_fallback(
                patch_target, original_code, patch_code,
                reason="Could not extract target function from patch — using full-file fallback"
            )

        # --- Step 2: Locate the same function in the ORIGINAL file ---
        orig_func_src, orig_start, orig_end = cls._locate_function_in_original(
            original_code, patch_func_name, language
        )

        if not orig_func_src:
            # Function not found in original — full-file fallback
            return cls._full_file_fallback(
                patch_target, original_code, patch_code,
                reason=(
                    f"Function '{patch_func_name}' not found in original file "
                    f"— using full-file fallback"
                )
            )

        # --- Step 3: Replace only the target function ---
        new_code = cls._splice_function(original_code, orig_start, orig_end, patch_func_src)

        if new_code == original_code:
            return cls._result(
                applied=False,
                fallback=False,
                function_name=patch_func_name,
                reason=f"Function '{patch_func_name}' was identical after patching — no change written"
            )

        with open(patch_target, "w", encoding="utf-8") as f:
            f.write(new_code)

        return cls._result(
            applied=True,
            fallback=False,
            function_name=patch_func_name,
            reason=f"Function-level patch applied to '{patch_func_name}'"
        )

    # -----------------------------------------------------------------------
    # Function extraction from patch
    # -----------------------------------------------------------------------

    @classmethod
    def _extract_target_function(
        cls,
        code: str,
        language: str,
        crash_line: int = 0,
    ) -> Tuple[str, str]:
        """
        Extract the most relevant function from the AI-generated patch code.

        Uses the crash_line as a hint to select the tightest enclosing function
        when multiple functions are present.

        Returns:
            (function_name, function_source) or ("", "") if not found.
        """
        if language == "python":
            return cls._extract_python_function(code, crash_line)
        elif language == "java":
            return cls._extract_java_function(code, crash_line)
        elif language == "cpp":
            return cls._extract_cpp_function(code, crash_line)
        return "", ""

    @staticmethod
    def _extract_python_function(code: str, crash_line: int) -> Tuple[str, str]:
        """Extract the tightest Python function wrapping crash_line using AST."""
        try:
            tree = ast.parse(code)
        except SyntaxError:
            return "", ""

        lines = code.splitlines()
        best_node = None
        min_size = float("inf")

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if not hasattr(node, "end_lineno"):
                    continue
                # If crash_line is known, prefer the enclosing function
                if crash_line > 0:
                    if node.lineno <= crash_line <= node.end_lineno:
                        size = node.end_lineno - node.lineno
                        if size < min_size:
                            min_size = size
                            best_node = node
                else:
                    # No crash line hint: pick the smallest (most specific) function
                    size = node.end_lineno - node.lineno
                    if size < min_size:
                        min_size = size
                        best_node = node

        if not best_node:
            # No function found at crash line; fall back to first function in file
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    best_node = node
                    break

        if not best_node:
            return "", ""

        func_src = "\n".join(lines[best_node.lineno - 1: best_node.end_lineno])
        return best_node.name, func_src

    @staticmethod
    def _extract_java_function(code: str, crash_line: int) -> Tuple[str, str]:
        """
        Extract a Java method using brace-balanced regex extraction.
        Selects the method whose declaration line is closest to crash_line.
        """
        # Match method signatures: <modifiers> <return_type> <name>(<params>) {
        method_start_pattern = re.compile(
            r'^(\s*(?:public|private|protected|static|final|synchronized|native|abstract|'
            r'default|override|\s)*\s*'
            r'(?:[\w<>\[\]]+)\s+(\w+)\s*\([^)]*\)\s*(?:throws\s+[\w,\s]+)?\s*\{)',
            re.MULTILINE,
        )

        lines = code.splitlines()
        candidates = []

        for m in method_start_pattern.finditer(code):
            start_line = code[:m.start()].count("\n") + 1  # 1-indexed
            method_name = m.group(2)

            # Skip class-like names (constructor detection heuristic)
            if method_name[0].isupper() and "return" not in m.group(1):
                pass  # Allow constructors through

            # Extract brace-balanced body starting from match
            body_start = m.start() + m.group(0).rfind("{")
            body_src, body_end_char = FunctionPatcher._extract_brace_balanced_block(
                code, body_start
            )

            if not body_src:
                continue

            full_src = code[m.start(): body_end_char]
            candidates.append((start_line, method_name, full_src))

        if not candidates:
            return "", ""

        if crash_line > 0:
            # Select the method whose start line is closest to (and before) crash_line
            valid = [(ln, name, src) for (ln, name, src) in candidates if ln <= crash_line]
            if valid:
                best = max(valid, key=lambda x: x[0])
                return best[1], best[2]

        # Default: first method
        return candidates[0][1], candidates[0][2]

    @staticmethod
    def _extract_cpp_function(code: str, crash_line: int) -> Tuple[str, str]:
        """
        Extract a C++ function using brace-balanced regex extraction.
        """
        # C++ function signature: <return_type> <name>(<params>) { ... }
        func_start_pattern = re.compile(
            r'^(\s*(?:inline|static|virtual|explicit|constexpr|\s)*'
            r'[\w:<>*&\s]+\s+(\w+)\s*\([^)]*\)\s*(?:const|noexcept|override)?\s*\{)',
            re.MULTILINE,
        )

        candidates = []

        for m in func_start_pattern.finditer(code):
            func_name = m.group(2)

            # Skip known non-function patterns
            if func_name in ("if", "for", "while", "switch", "else", "do", "try", "catch"):
                continue

            start_line = code[:m.start()].count("\n") + 1
            brace_pos = m.start() + m.group(0).rfind("{")
            body_src, body_end_char = FunctionPatcher._extract_brace_balanced_block(
                code, brace_pos
            )

            if not body_src:
                continue

            full_src = code[m.start(): body_end_char]
            candidates.append((start_line, func_name, full_src))

        if not candidates:
            return "", ""

        if crash_line > 0:
            valid = [(ln, name, src) for (ln, name, src) in candidates if ln <= crash_line]
            if valid:
                best = max(valid, key=lambda x: x[0])
                return best[1], best[2]

        # Default: main() if present, otherwise first
        for (ln, name, src) in candidates:
            if name == "main":
                return name, src
        return candidates[0][1], candidates[0][2]

    # -----------------------------------------------------------------------
    # Function location in original file
    # -----------------------------------------------------------------------

    @classmethod
    def _locate_function_in_original(
        cls,
        original_code: str,
        func_name: str,
        language: str,
    ) -> Tuple[str, int, int]:
        """
        Locate a function by name in the original source code.

        Returns:
            (function_source, char_start, char_end) or ("", 0, 0) if not found.
        """
        if language == "python":
            return cls._locate_python_function(original_code, func_name)
        elif language in ("java", "cpp"):
            return cls._locate_braced_function(original_code, func_name)
        return "", 0, 0

    @staticmethod
    def _locate_python_function(code: str, func_name: str) -> Tuple[str, int, int]:
        """Locate a Python function by name using the AST."""
        try:
            tree = ast.parse(code)
        except SyntaxError:
            return "", 0, 0

        lines = code.splitlines()

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name == func_name and hasattr(node, "end_lineno"):
                    # Convert line numbers to character offsets
                    start_chars = sum(len(l) + 1 for l in lines[:node.lineno - 1])
                    end_chars = sum(len(l) + 1 for l in lines[:node.end_lineno])
                    func_src = "\n".join(lines[node.lineno - 1: node.end_lineno])
                    return func_src, start_chars, end_chars

        return "", 0, 0

    @staticmethod
    def _locate_braced_function(code: str, func_name: str) -> Tuple[str, int, int]:
        """
        Locate a Java/C++ function by name using regex + brace balancing.
        """
        # Flexible pattern: match the function name with optional modifiers before
        pattern = re.compile(
            r'((?:(?:public|private|protected|static|final|virtual|inline|'
            r'synchronized|override|const|constexpr|explicit|\s)+\s*)?'
            r'[\w:<>*&\[\]]+\s+)(\b' + re.escape(func_name) + r'\b)'
            r'(\s*\([^)]*\)\s*(?:const|noexcept|override|throws\s+[\w,\s]+)?\s*\{)',
            re.MULTILINE,
        )

        for m in pattern.finditer(code):
            brace_pos = m.start() + m.group(0).rfind("{")
            body_src, end_char = FunctionPatcher._extract_brace_balanced_block(code, brace_pos)
            if not body_src:
                continue
            full_src = code[m.start(): end_char]
            return full_src, m.start(), end_char

        return "", 0, 0

    # -----------------------------------------------------------------------
    # Splice helper
    # -----------------------------------------------------------------------

    @staticmethod
    def _splice_function(
        original_code: str,
        orig_start: int,
        orig_end: int,
        new_func_src: str,
    ) -> str:
        """
        Replace the character range [orig_start, orig_end) in original_code
        with new_func_src, preserving surrounding whitespace.
        """
        before = original_code[:orig_start]
        after = original_code[orig_end:]

        # Preserve a newline separator before/after if present
        if before and not before.endswith("\n"):
            before += "\n"
        if after and not after.startswith("\n"):
            new_func_src = new_func_src.rstrip() + "\n"

        return before + new_func_src + after

    # -----------------------------------------------------------------------
    # Brace-balanced block extractor (Java / C++)
    # -----------------------------------------------------------------------

    @staticmethod
    def _extract_brace_balanced_block(code: str, open_brace_pos: int) -> Tuple[str, int]:
        """
        Starting from the '{' at open_brace_pos, walk forward tracking depth
        until the matching '}' is found.

        Returns:
            (block_source_including_braces, char_index_after_closing_brace)
            or ("", 0) if not balanced.
        """
        if open_brace_pos >= len(code) or code[open_brace_pos] != "{":
            return "", 0

        depth = 0
        in_single = in_double = escape_next = False
        in_line_comment = in_block_comment = False

        for i in range(open_brace_pos, len(code)):
            ch = code[i]

            # Handle escape sequences inside strings
            if escape_next:
                escape_next = False
                continue
            if ch == "\\" and (in_single or in_double):
                escape_next = True
                continue

            # Handle line comments
            if not in_string_context(in_single, in_double, in_block_comment):
                if ch == "/" and i + 1 < len(code):
                    if code[i + 1] == "/" and not in_block_comment:
                        in_line_comment = True
                        continue
                    if code[i + 1] == "*" and not in_line_comment:
                        in_block_comment = True
                        continue

            if in_line_comment:
                if ch == "\n":
                    in_line_comment = False
                continue

            if in_block_comment:
                if ch == "*" and i + 1 < len(code) and code[i + 1] == "/":
                    in_block_comment = False
                continue

            # String tracking
            if ch == '"' and not in_single:
                in_double = not in_double
                continue
            if ch == "'" and not in_double:
                in_single = not in_single
                continue
            if in_single or in_double:
                continue

            # Brace counting
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return code[open_brace_pos: i + 1], i + 1

        return "", 0  # Unbalanced braces

    # -----------------------------------------------------------------------
    # Full-file fallback
    # -----------------------------------------------------------------------

    @classmethod
    def _full_file_fallback(
        cls,
        patch_target: str,
        original_code: str,
        patch_code: str,
        reason: str = "",
    ) -> Dict[str, Any]:
        """
        Fall back to writing the entire patch_code as the file content.
        Used when function extraction fails.
        """
        with open(patch_target, "w", encoding="utf-8") as f:
            f.write(patch_code)

        print(f"[FunctionPatcher] Full-file fallback: {reason}")
        return cls._result(
            applied=True,
            fallback=True,
            function_name="",
            reason=f"Full-file fallback — {reason}"
        )

    # -----------------------------------------------------------------------
    # Result builder
    # -----------------------------------------------------------------------

    @staticmethod
    def _result(
        applied: bool,
        fallback: bool,
        function_name: str = "",
        reason: str = "",
    ) -> Dict[str, Any]:
        return {
            "applied": applied,
            "fallback": fallback,
            "function_name": function_name,
            "reason": reason,
        }


# ---------------------------------------------------------------------------
# Helper (module-level to avoid closure overhead in hot loop)
# ---------------------------------------------------------------------------

def in_string_context(in_single: bool, in_double: bool, in_block_comment: bool) -> bool:
    return in_single or in_double or in_block_comment
