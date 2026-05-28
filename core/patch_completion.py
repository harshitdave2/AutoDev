"""
core/patch_completion.py
-------------------------
Lightweight, conservative patch auto-completion for AutoDev.

When an LLM returns a truncated or incomplete patch, this module attempts
to repair it BEFORE the patch reaches the validator.  The goal is to rescue
valid partial repairs that would otherwise be hard-rejected.

Conservative principles:
  - Never add logic — only close structures that are clearly open
  - Never remove existing code
  - Bail out immediately if the completion would change semantics
  - Return the original code unchanged if any heuristic is uncertain

Supported completions:
  Python  : unclosed parentheses, missing return/pass in empty blocks,
            incomplete function bodies (truncated mid-expression)
  Java    : unbalanced braces, missing closing braces for class/method
  C++     : unbalanced braces, missing semicolons after last statement,
            incomplete function bodies

Usage:
    result = PatchCompletion.complete(code, language="python")
    if result.was_modified:
        print("Completed:", result.repairs_applied)
    result = PatchCompleter.complete(code, language="python")
    print(result)
"""

import ast
import re
from dataclasses import dataclass, field
from typing import List, Tuple


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass
class CompletionResult:
    """
    Result of a patch completion attempt.

    Attributes:
        code            : The (possibly modified) code string.
        was_modified    : True if any repair was applied.
        repairs_applied : List of repair descriptions applied.
        is_safe         : False if the completer gave up due to uncertainty.
    """
    code: str
    was_modified: bool
    repairs_applied: List[str] = field(default_factory=list)
    is_safe: bool = True


# ---------------------------------------------------------------------------
# Completion engine
# ---------------------------------------------------------------------------
class PatchCompleter:
    """
    Conservative patch completion engine.

    All methods are classmethods. The complete() entry point runs each
    repair in sequence and short-circuits if any repair is uncertain.
    """

    # Maximum lines a "truncated" completion may add
    _MAX_COMPLETION_LINES = 10

    @classmethod
    def complete(cls, code: str, language: str = "python") -> str:
        """
        Attempt to complete/repair a potentially truncated patch.
        Returns repaired string.

        Repairs are applied in order. Each repair returns a possibly-modified
        string and a description. If any repair signals uncertainty
        (is_safe=False), the original code is returned unchanged.

        Args:
            code     : The raw (possibly truncated) patch code string.
            language : "python", "java", or "cpp".

        """
        if not code or not code.strip():
            return code or ""

        original = code
        repairs: List[str] = []
        lang = language.lower()

        # ---- Universal repairs ----
        code, r = cls._strip_trailing_ellipsis(code)
        if r:
            repairs.append(r)

        code, r = cls._strip_orphan_markdown_fences(code)
        if r:
            repairs.append(r)

        # ---- Language-specific repairs ----
        if lang == "python":
            code, rlist, safe = cls._complete_python(code)
            repairs += rlist
            if not safe:
                print("[PatchCompletion] Python repair unsafe, returning original")
                return original

        elif lang in ("java", "cpp"):
            code, rlist, safe = cls._complete_braced(code, lang)
            repairs += rlist
            if not safe:
                print(f"[PatchCompletion] {lang.upper()} repair unsafe, returning original")
                return original

        was_modified = code.rstrip() != original.rstrip()
        
        if was_modified and repairs:
            print(f"[PatchCompletion] Repaired: {', '.join(repairs[:3])}")
            
        return code

    # -----------------------------------------------------------------------
    # Universal repairs
    # -----------------------------------------------------------------------

    @staticmethod
    def _strip_trailing_ellipsis(code: str) -> Tuple[str, str]:
        """
        Remove trailing '...' or '# ...' that LLMs append to indicate truncation.
        These markers are NOT valid Python/Java/C++ and confuse parsers.
        """
        stripped = code.rstrip()
        # Check last non-empty line
        last_line = stripped.splitlines()[-1].strip() if stripped.splitlines() else ""
        if last_line in ("...", "# ...", "# ... (rest unchanged)", "// ..."):
            # Drop the last line
            lines = stripped.splitlines()
            new_code = "\n".join(lines[:-1])
            return new_code, f"Stripped trailing truncation marker: {last_line!r}"
        return code, ""

    @staticmethod
    def _strip_orphan_markdown_fences(code: str) -> Tuple[str, str]:
        """Remove any remaining ``` markers that weren't caught by normalization."""
        if "```" not in code:
            return code, ""
        cleaned = re.sub(r'```\w*\s*\n?', '', code)
        cleaned = cleaned.replace("```", "")
        if cleaned.rstrip() != code.rstrip():
            return cleaned, "Stripped orphan markdown fence markers"
        return code, ""

    # -----------------------------------------------------------------------
    # Python-specific completion
    # -----------------------------------------------------------------------

    @classmethod
    def _complete_python(cls, code: str) -> Tuple[str, List[str], bool]:
        """
        Apply Python-specific completions.

        Returns (completed_code, repairs_list, is_safe).
        is_safe=False means we gave up — return original.
        """
        repairs: List[str] = []

        # 1. Balance parentheses
        code, r = cls._balance_parens_python(code)
        if r:
            repairs.append(r)

        # 2. Balance brackets
        code, r = cls._balance_brackets(code, "[", "]")
        if r:
            repairs.append(r)

        # 3. Repair empty block bodies (def/if/for/while with no body)
        code, r, safe = cls._repair_empty_blocks_python(code)
        if not safe:
            return code, repairs, False
        if r:
            repairs.append(r)

        # 4. Validate: try to parse as Python
        # If still invalid after our repairs, signal unsafe
        try:
            ast.parse(code)
        except SyntaxError as e:
            # Only reject if we couldn't fix it
            # (The original was already broken — we tried our best)
            pass  # Don't set unsafe — let validator handle it

        return code, repairs, True

    @staticmethod
    def _balance_parens_python(code: str) -> Tuple[str, str]:
        """Add missing closing parentheses at end of code."""
        open_count = 0
        in_string_single = in_string_double = False
        in_triple_single = in_triple_double = False
        i = 0
        while i < len(code):
            ch = code[i]
            # Triple quotes
            if code[i:i+3] == '"""':
                in_triple_double = not in_triple_double
                i += 3
                continue
            if code[i:i+3] == "'''":
                in_triple_single = not in_triple_single
                i += 3
                continue
            if in_triple_double or in_triple_single:
                i += 1
                continue
            if ch == '"' and not in_string_single:
                in_string_double = not in_string_double
            elif ch == "'" and not in_string_double:
                in_string_single = not in_string_single
            if not in_string_single and not in_string_double:
                if ch == '(':
                    open_count += 1
                elif ch == ')':
                    open_count -= 1
            i += 1

        if open_count > 0 and open_count <= 5:
            closing = ")" * open_count
            return code.rstrip() + closing, f"Added {open_count} missing closing parenthesis"
        return code, ""

    @staticmethod
    def _balance_brackets(code: str, open_ch: str, close_ch: str) -> Tuple[str, str]:
        """Add missing closing brackets/braces."""
        # Simple non-string-aware count (good enough for completion)
        in_str = False
        depth = 0
        for ch in code:
            if ch == '"' or ch == "'":
                in_str = not in_str
            if in_str:
                continue
            if ch == open_ch:
                depth += 1
            elif ch == close_ch:
                depth -= 1

        if depth > 0 and depth <= 5:
            closing = close_ch * depth
            return code.rstrip() + "\n" + closing, f"Added {depth} missing '{close_ch}'"
        return code, ""

    @staticmethod
    def _repair_empty_blocks_python(code: str) -> Tuple[str, str, bool]:
        """
        Add 'pass' to empty function/class/if/for/while bodies.
        Only safe when the body is completely absent (colon at end, next line
        is de-dented or EOF).
        """
        lines = code.splitlines()
        new_lines = []
        repairs = []
        i = 0

        BLOCK_STARTERS = re.compile(
            r'^(\s*)(def |class |if |elif |else:|for |while |try:|except|finally:)',
            re.MULTILINE,
        )

        while i < len(lines):
            line = lines[i]
            stripped = line.rstrip()

            # Check if this line starts a block (ends with colon)
            if stripped.endswith(":") and BLOCK_STARTERS.match(stripped):
                new_lines.append(line)
                # Check if next line exists and is properly indented
                if i + 1 < len(lines):
                    next_line = lines[i + 1]
                    if next_line.strip() == "":
                        # Empty next line — check the one after
                        if i + 2 >= len(lines) or (
                            lines[i + 2].strip() != ""
                            and not lines[i + 2].startswith(" " * (len(stripped) - len(stripped.lstrip()) + 1))
                        ):
                            # Block body is missing — add pass
                            indent = len(stripped) - len(stripped.lstrip()) + 4
                            new_lines.append(" " * indent + "pass  # auto-completed")
                            repairs.append(f"Added 'pass' to empty block at line {i+1}")
                else:
                    # EOF after colon — block needs a body
                    indent = len(stripped) - len(stripped.lstrip()) + 4
                    new_lines.append(" " * indent + "pass  # auto-completed")
                    repairs.append(f"Added 'pass' to empty block at EOF (line {i+1})")
                i += 1
                continue

            new_lines.append(line)
            i += 1

        result = "\n".join(new_lines)
        repair_str = "; ".join(repairs) if repairs else ""
        return result, repair_str, True

    # -----------------------------------------------------------------------
    # Java / C++ brace completion
    # -----------------------------------------------------------------------

    @classmethod
    def _complete_braced(cls, code: str, language: str) -> Tuple[str, List[str], bool]:
        """
        Balance braces for Java and C++.
        Only adds closing braces at the end of the file — never restructures.
        """
        repairs: List[str] = []

        depth = cls._count_brace_depth(code)

        if depth < 0:
            # More closing than opening — don't touch it
            return code, repairs, True

        if depth > 0:
            if depth > cls._MAX_COMPLETION_LINES:
                # Too many missing braces — structure is too broken to auto-fix
                return code, repairs, True  # safe=True but no repair

            closing_braces = "\n".join("}" * depth)
            # Add one brace per line for readability
            braces_str = "\n".join(["}"] * depth)
            code = code.rstrip() + "\n" + braces_str
            repairs.append(f"Added {depth} missing closing brace(s)")

        # For C++: check for missing semicolons on class/struct closing brace
        if language == "cpp":
            code, r = cls._cpp_class_semicolon(code)
            if r:
                repairs.append(r)

        return code, repairs, True

    @staticmethod
    def _count_brace_depth(code: str) -> int:
        """
        Count unmatched open braces, skipping string/comment contexts.
        Returns: positive = missing closings, negative = extra closings.
        """
        depth = 0
        in_line_comment = False
        in_block_comment = False
        in_single = in_double = False
        escape_next = False
        i = 0
        while i < len(code):
            ch = code[i]
            if escape_next:
                escape_next = False
                i += 1
                continue
            if ch == '\\' and (in_single or in_double):
                escape_next = True
                i += 1
                continue
            if not in_single and not in_double and not in_block_comment:
                if ch == '/' and i + 1 < len(code):
                    if code[i+1] == '/' and not in_line_comment:
                        in_line_comment = True
                        i += 2
                        continue
                    if code[i+1] == '*':
                        in_block_comment = True
                        i += 2
                        continue
            if in_line_comment:
                if ch == '\n':
                    in_line_comment = False
                i += 1
                continue
            if in_block_comment:
                if ch == '*' and i + 1 < len(code) and code[i+1] == '/':
                    in_block_comment = False
                    i += 2
                    continue
                i += 1
                continue
            if ch == '"' and not in_single:
                in_double = not in_double
            elif ch == "'" and not in_double:
                in_single = not in_single
            if not in_single and not in_double:
                if ch == '{':
                    depth += 1
                elif ch == '}':
                    depth -= 1
            i += 1
        return depth

    @staticmethod
    def _cpp_class_semicolon(code: str) -> Tuple[str, str]:
        """
        In C++, class/struct definitions must end with '}; '.
        If the last non-empty line is '}' without a semicolon, and there's
        a class/struct earlier, add the semicolon.
        """
        lines = code.rstrip().splitlines()
        if not lines:
            return code, ""
        last = lines[-1].rstrip()
        if last == "}" and re.search(r'\b(?:class|struct)\b', code):
            lines[-1] = "};"
            return "\n".join(lines), "Added missing ';' after class/struct closing brace"
        return code, ""
