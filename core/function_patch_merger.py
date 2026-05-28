"""
core/function_patch_merger.py
------------------------------
Intelligent function-level patch merging for AutoDev.

When an LLM returns a partial patch (one or more modified functions, without
the rest of the file), this module merges it safely into the original source.

This is the core solution to the "Patch removed main()" class of failures.

Merge strategy:
  1. Parse both original and patch to extract function/method definitions
  2. For each function in the patch: replace the matching function in original
  3. For new functions in the patch: append them after the last existing function
  4. Preserve all non-function content:
       - Python  : imports, module-level globals, if __name__ == "__main__"
       - Java    : package declaration, imports, class wrapper, field declarations
       - C++     : #include directives, global declarations, main(), namespaces

Supported languages: Python, Java, C++

Design principles:
  - Fail-safe: if merging is uncertain, return the original unchanged
  - No semantic changes: only replace matched function bodies
  - Traceable: returns a MergeReport with what changed

Usage:
    result = FunctionPatchMerger.merge(
        original=original_code,
        patch=partial_patch,
        language="python",
    )
    if result.success:
        # use result.merged_code
        print(result.functions_replaced, result.functions_added)
    else:
        # fall back to full-file replacement
        print(result.reason)
"""

import ast
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass
class MergeReport:
    """
    Report from a FunctionPatchMerger.merge() call.

    Attributes:
        success            : True if merge succeeded.
        merged_code        : The merged source (or original if success=False).
        functions_replaced : Names of functions that were replaced.
        functions_added    : Names of functions that were newly inserted.
        reason             : Human-readable explanation (used if success=False).
        fallback_used      : True if merge fell back to full-file replacement.
    """
    success: bool
    merged_code: str
    functions_replaced: List[str] = field(default_factory=list)
    functions_added: List[str] = field(default_factory=list)
    reason: str = ""
    fallback_used: bool = False


# ---------------------------------------------------------------------------
# Merger
# ---------------------------------------------------------------------------

class FunctionPatchMerger:
    """
    Merges partial function patches into the original source file.

    All methods are classmethods. The merge() entry point dispatches to
    the language-specific implementation.
    """

    @classmethod
    def merge(
        cls,
        original: str,
        patch: str,
        language: str = "python",
    ) -> MergeReport:
        """
        Merge a (possibly partial) patch into the original source.

        Args:
            original : The complete original source file content.
            patch    : The LLM-generated patch (may be partial or complete).
            language : "python", "java", or "cpp".

        Returns:
            MergeReport with success flag and merged_code.
        """
        if not original or not original.strip():
            return MergeReport(
                success=False,
                merged_code=patch or "",
                reason="Original code is empty — using patch as-is",
            )

        if not patch or not patch.strip():
            return MergeReport(
                success=False,
                merged_code=original,
                reason="Patch is empty — keeping original unchanged",
            )

        # Determine if patch looks like a snippet vs full file
        patch_lines = patch.strip().splitlines()
        orig_lines = original.strip().splitlines()
        is_snippet = len(patch_lines) < len(orig_lines) * 0.60
        merge_tag = "SNIPPET_MERGE" if is_snippet else "FULL_FILE"
        print(f"[FunctionPatchMerger] {merge_tag} — patch={len(patch_lines)} lines, original={len(orig_lines)} lines")

        lang = language.lower()
        try:
            if lang == "python":
                return cls._merge_python(original, patch)
            elif lang == "java":
                return cls._merge_java(original, patch)
            elif lang == "cpp":
                return cls._merge_cpp(original, patch)
            else:
                return MergeReport(
                    success=False,
                    merged_code=original,
                    reason=f"Language '{language}' not supported by FunctionPatchMerger",
                )
        except Exception as e:
            return MergeReport(
                success=False,
                merged_code=original,
                reason=f"Merge error: {e}",
            )

    # -----------------------------------------------------------------------
    # Python merger — uses AST for precise function extraction
    # -----------------------------------------------------------------------

    @classmethod
    def _merge_python(cls, original: str, patch: str) -> MergeReport:
        """
        Merge Python patches using AST-based function boundary detection.
        """
        # Parse original
        try:
            orig_tree = ast.parse(original)
        except SyntaxError as e:
            return MergeReport(
                success=False,
                merged_code=original,
                reason=f"Original has syntax error: {e}",
            )

        # Parse patch — may fail if partial
        try:
            patch_tree = ast.parse(patch)
            patch_valid = True
        except SyntaxError:
            patch_valid = False
            patch_tree = None

        # Extract functions from original
        orig_functions = cls._extract_python_functions(original, orig_tree)

        # Extract functions from patch
        if patch_valid and patch_tree:
            patch_functions = cls._extract_python_functions(patch, patch_tree)
        else:
            # Patch is partial/invalid — try to extract function definitions
            # using a regex-based approach as fallback
            patch_functions = cls._extract_python_functions_regex(patch)

        if not patch_functions:
            # No functions in patch — if it's valid Python, use full-file
            if patch_valid:
                return MergeReport(
                    success=True,
                    merged_code=patch,
                    reason="Patch is a complete file with no function-level changes",
                    fallback_used=True,
                )
            return MergeReport(
                success=False,
                merged_code=original,
                reason="Could not extract any functions from the patch",
            )

        # Perform replacement
        result_code = original
        replaced: List[str] = []
        added: List[str] = []

        for func_name, patch_func_src in patch_functions.items():
            if func_name in orig_functions:
                # Replace existing function
                result_code = cls._replace_python_function(
                    result_code, func_name, patch_func_src
                )
                replaced.append(func_name)
            else:
                # New function — append before __main__ block or at end
                result_code = cls._insert_python_function(
                    result_code, func_name, patch_func_src
                )
                added.append(func_name)

        if not replaced and not added:
            return MergeReport(
                success=False,
                merged_code=original,
                reason="No functions could be matched or added",
            )

        return MergeReport(
            success=True,
            merged_code=result_code,
            functions_replaced=replaced,
            functions_added=added,
            reason=(
                f"Merged: replaced {replaced}, added {added}"
            ),
        )

    @staticmethod
    def _extract_python_functions(
        source: str, tree: ast.Module
    ) -> Dict[str, str]:
        """
        Extract all top-level function definitions from a parsed AST.
        Returns dict: func_name -> full source code of the function.
        """
        lines = source.splitlines(keepends=True)
        functions: Dict[str, str] = {}
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if hasattr(node, "end_lineno"):
                    func_lines = lines[node.lineno - 1: node.end_lineno]
                    functions[node.name] = "".join(func_lines).rstrip()
        return functions

    @staticmethod
    def _extract_python_functions_regex(source: str) -> Dict[str, str]:
        """
        Regex fallback for extracting function definitions from unparseable code.
        Finds 'def func_name(...):' and captures the indented body below it.
        """
        functions: Dict[str, str] = {}
        lines = source.splitlines()
        i = 0
        while i < len(lines):
            m = re.match(r'^(def |async def )(\w+)\s*\(', lines[i])
            if m:
                func_name = m.group(2)
                start = i
                # Collect body until dedent or EOF
                i += 1
                while i < len(lines):
                    line = lines[i]
                    # Blank lines are ok inside a function
                    if line.strip() == "":
                        i += 1
                        continue
                    # If line is indented, it's part of the function
                    if line[0] in (" ", "\t"):
                        i += 1
                        continue
                    # Dedented line = function ended
                    break
                func_src = "\n".join(lines[start:i]).rstrip()
                functions[func_name] = func_src
            else:
                i += 1
        return functions

    @staticmethod
    def _replace_python_function(source: str, func_name: str, new_func: str) -> str:
        """
        Replace the named function in source with new_func.
        Uses AST to find exact line boundaries.
        """
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return source

        lines = source.splitlines(keepends=True)
        for node in tree.body:
            if (isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and node.name == func_name
                    and hasattr(node, "end_lineno")):
                start = node.lineno - 1
                end = node.end_lineno
                # Build new source: everything before + new func + everything after
                before = "".join(lines[:start])
                after = "".join(lines[end:])
                return before + new_func + "\n" + after

        # Fallback: regex-based replacement
        pattern = re.compile(
            r'^(?:async )?def\s+' + re.escape(func_name) + r'\s*\(.*?(?=\ndef |\nclass |\Z)',
            re.MULTILINE | re.DOTALL,
        )
        return pattern.sub(new_func, source, count=1)

    @staticmethod
    def _insert_python_function(source: str, func_name: str, new_func: str) -> str:
        """
        Insert a new function before the if __name__ == '__main__': block,
        or append at the end.
        """
        main_block_pattern = re.compile(
            r'^if\s+__name__\s*==\s*[\'"]__main__[\'"]\s*:',
            re.MULTILINE
        )
        m = main_block_pattern.search(source)
        if m:
            # Insert before main block with blank line separation
            insert_pos = m.start()
            return source[:insert_pos] + new_func + "\n\n\n" + source[insert_pos:]
        else:
            return source.rstrip() + "\n\n\n" + new_func + "\n"

    # -----------------------------------------------------------------------
    # Java merger — regex-based method extraction
    # -----------------------------------------------------------------------

    @classmethod
    def _merge_java(cls, original: str, patch: str) -> MergeReport:
        """
        Merge Java patches by replacing matching methods in the class body.
        Preserves class declaration, package, imports, fields, and main().

        Extended: if patch has NO class declaration, treats it as a partial
        class body (methods-only) and injects each method individually.
        """
        patch_has_class = bool(re.search(r'\bclass\s+\w', patch))

        # --- Case 1: Patch is a complete file → full-file replacement ---
        if patch_has_class:
            # Check if it is roughly complete (≥ 60% length of original)
            if len(patch.strip()) >= 0.60 * len(original.strip()):
                return MergeReport(
                    success=True,
                    merged_code=patch,
                    reason="Patch is a complete Java file",
                    fallback_used=True,
                )
            # Patch has a class decl but is significantly smaller than original
            # — treat as partial class, still try method-level merge below

        patch_methods = cls._extract_java_methods(patch)

        if not patch_methods:
            if patch_has_class:
                # Has class but no extractable methods → use as full file
                return MergeReport(
                    success=True,
                    merged_code=patch,
                    reason="Patch is a complete Java file (no extractable methods)",
                    fallback_used=True,
                )
            return MergeReport(
                success=False,
                merged_code=original,
                reason="No Java methods found in patch",
            )

        # --- Case 2: Partial class body — inject methods into original class ---
        if not patch_has_class:
            print("[FunctionPatchMerger] Java patch has no class declaration — partial body mode")

        result = original
        replaced: List[str] = []
        added: List[str] = []

        for method_name, method_src in patch_methods.items():
            if cls._java_has_method(result, method_name):
                result = cls._replace_java_method(result, method_name, method_src)
                replaced.append(method_name)
            else:
                result = cls._insert_java_method(result, method_src)
                added.append(method_name)

        if not replaced and not added:
            return MergeReport(
                success=False,
                merged_code=original,
                reason="No Java methods could be matched",
            )

        return MergeReport(
            success=True,
            merged_code=result,
            functions_replaced=replaced,
            functions_added=added,
            reason=f"Java merge: replaced {replaced}, added {added}",
        )

    @staticmethod
    def _extract_java_methods(source: str) -> Dict[str, str]:
        """
        Extract named methods from Java source using brace-matching.
        Returns dict: method_name -> full method source.
        """
        methods: Dict[str, str] = {}
        # Match method signatures (simplified: access modifier + return type + name + params)
        sig_pattern = re.compile(
            r'(?:(?:public|private|protected|static|final|synchronized|abstract|native|default)\s+)*'
            r'(?:[\w<>\[\]]+\s+)+(\w+)\s*\([^)]*\)\s*(?:throws\s+[\w,\s]+)?\s*\{',
            re.MULTILINE,
        )
        for m in sig_pattern.finditer(source):
            method_name = m.group(1)
            if method_name in ("if", "for", "while", "switch", "catch", "try"):
                continue
            # Find the complete method body using brace matching
            start = m.start()
            brace_start = source.index('{', m.start())
            depth = 0
            end = brace_start
            for i, ch in enumerate(source[brace_start:], brace_start):
                if ch == '{':
                    depth += 1
                elif ch == '}':
                    depth -= 1
                    if depth == 0:
                        end = i + 1
                        break
            method_src = source[start:end].strip()
            methods[method_name] = method_src
        return methods

    @staticmethod
    def _java_has_method(source: str, method_name: str) -> bool:
        """Check if a method with this name exists in the Java source."""
        pattern = re.compile(
            r'\b' + re.escape(method_name) + r'\s*\([^)]*\)\s*(?:throws\s+[\w,\s]+)?\s*\{',
        )
        return bool(pattern.search(source))

    @staticmethod
    def _replace_java_method(source: str, method_name: str, new_method: str) -> str:
        """Replace an existing method in Java source."""
        sig_pattern = re.compile(
            r'(?:(?:public|private|protected|static|final|synchronized|abstract|native|default)\s+)*'
            r'(?:[\w<>\[\]]+\s+)+' + re.escape(method_name) + r'\s*\([^)]*\)\s*(?:throws\s+[\w,\s]+)?\s*\{',
            re.MULTILINE,
        )
        m = sig_pattern.search(source)
        if not m:
            return source

        brace_start = source.index('{', m.start())
        depth = 0
        end = brace_start
        for i, ch in enumerate(source[brace_start:], brace_start):
            if ch == '{':
                depth += 1
            elif ch == '}':
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break

        return source[:m.start()] + new_method + source[end:]

    @staticmethod
    def _insert_java_method(source: str, new_method: str) -> str:
        """Insert a new method before the last closing brace of the class."""
        last_brace = source.rfind("}")
        if last_brace == -1:
            return source + "\n\n    " + new_method + "\n}"
        return source[:last_brace] + "\n\n    " + new_method + "\n" + source[last_brace:]

    # -----------------------------------------------------------------------
    # C++ merger — regex + brace matching
    # -----------------------------------------------------------------------

    @classmethod
    def _merge_cpp(cls, original: str, patch: str) -> MergeReport:
        """
        Merge C++ patches by replacing matching function definitions.
        Preserves #include directives, global declarations, and main().

        Also handles out-of-line class method definitions using the
        ClassName::methodName(...) notation that the LLM commonly produces
        for targeted method repairs.
        """
        patch_functions = cls._extract_cpp_functions(patch)

        if not patch_functions:
            # Fallback: try to detect out-of-line class method definitions
            # Pattern: ReturnType ClassName::methodName(params) { ... }
            outline_methods = cls._extract_cpp_outline_methods(patch)
            if outline_methods:
                print(
                    f"[FunctionPatchMerger] Detected {len(outline_methods)} out-of-line "
                    f"C++ method definition(s) — injecting into class body"
                )
                result = original
                replaced: List[str] = []
                added: List[str] = []
                for qualified_name, method_src in outline_methods.items():
                    # qualified_name is "ClassName::methodName"
                    parts = qualified_name.split("::", 1)
                    method_name = parts[1] if len(parts) == 2 else qualified_name
                    if cls._cpp_has_function(result, method_name):
                        result = cls._replace_cpp_function(result, method_name, method_src)
                        replaced.append(qualified_name)
                    else:
                        result = cls._insert_cpp_function(result, method_name, method_src)
                        added.append(qualified_name)
                if replaced or added:
                    return MergeReport(
                        success=True,
                        merged_code=result,
                        functions_replaced=replaced,
                        functions_added=added,
                        reason=f"C++ out-of-line merge: replaced {replaced}, added {added}",
                    )

            # No functions found in patch — if it has includes, full-file
            if re.search(r'^#include', patch, re.MULTILINE):
                return MergeReport(
                    success=True,
                    merged_code=patch,
                    reason="Patch appears to be a complete C++ file",
                    fallback_used=True,
                )
            patch_line_count = len(patch.strip().splitlines())
            return MergeReport(
                success=False,
                merged_code=original,
                reason=(
                    f"No C++ functions found in patch ({patch_line_count} lines) — "
                    f"patch may be too small to parse or use an unsupported syntax"
                ),
            )

        result = original
        replaced: List[str] = []
        added: List[str] = []

        for func_name, func_src in patch_functions.items():
            if func_name == "main":
                # Never replace main() from a partial patch
                # (main is usually not the bug)
                continue
            if cls._cpp_has_function(result, func_name):
                result = cls._replace_cpp_function(result, func_name, func_src)
                replaced.append(func_name)
            else:
                result = cls._insert_cpp_function(result, func_name, func_src)
                added.append(func_name)

        if not replaced and not added:
            return MergeReport(
                success=False,
                merged_code=original,
                reason="No C++ functions could be matched (all were 'main' or unknown)",
            )

        return MergeReport(
            success=True,
            merged_code=result,
            functions_replaced=replaced,
            functions_added=added,
            reason=f"C++ merge: replaced {replaced}, added {added}",
        )

    @staticmethod
    def _extract_cpp_functions(source: str) -> Dict[str, str]:
        """Extract named C++ functions using signature + brace matching."""
        functions: Dict[str, str] = {}
        # Match: return_type function_name(params) { ... }
        sig_pattern = re.compile(
            r'(?:[\w:*&<>\s]+)\s+(\w+)\s*\([^)]*\)\s*(?:const|noexcept|override)?\s*\{',
            re.MULTILINE,
        )
        for m in sig_pattern.finditer(source):
            func_name = m.group(1)
            if func_name in ("if", "for", "while", "switch", "catch"):
                continue
            brace_start = source.index('{', m.start())
            depth = 0
            end = brace_start
            for i, ch in enumerate(source[brace_start:], brace_start):
                if ch == '{':
                    depth += 1
                elif ch == '}':
                    depth -= 1
                    if depth == 0:
                        end = i + 1
                        break
            func_src = source[m.start():end].strip()
            functions[func_name] = func_src
        return functions

    @staticmethod
    def _extract_cpp_outline_methods(source):
        """
        Extract out-of-line C++ class method definitions using ClassName::methodName notation.

        These are definitions like:
            int Student::getId() { return id_; }
            void Matrix::multiply(int n) { ... }

        Returns dict: "ClassName::methodName" -> inline method source (ClassName:: prefix stripped).
        """
        import re as _re
        methods = {}
        sig_pattern = _re.compile(
            r'(?:[\w*&<>\s]*)?\b(\w+)::(\w+)\s*\([^)]*\)\s*(?:const|noexcept|override)?\s*\{',
            _re.MULTILINE,
        )
        for m in sig_pattern.finditer(source):
            class_name = m.group(1)
            method_name = m.group(2)
            if method_name in ('if', 'for', 'while', 'switch', 'catch'):
                continue
            qualified = class_name + '::' + method_name
            try:
                brace_start = source.index('{', m.start())
            except ValueError:
                continue
            depth = 0
            end = brace_start
            for i, ch in enumerate(source[brace_start:], brace_start):
                if ch == '{':
                    depth += 1
                elif ch == '}':
                    depth -= 1
                    if depth == 0:
                        end = i + 1
                        break
            raw_src = source[m.start():end].strip()
            # Strip the ClassName:: qualifier for inline injection
            inline_src = _re.sub(
                r'\b' + _re.escape(class_name) + r'::(' + _re.escape(method_name) + r')',
                r'\1',
                raw_src,
                count=1,
            )
            methods[qualified] = inline_src
        return methods

    @staticmethod
    def _cpp_has_function(source: str, func_name: str) -> bool:
        """Check if a function with this name exists in the C++ source."""
        pattern = re.compile(
            r'\b' + re.escape(func_name) + r'\s*\([^)]*\)\s*(?:const|noexcept|override)?\s*\{'
        )
        return bool(pattern.search(source))

    @staticmethod
    def _replace_cpp_function(source: str, func_name: str, new_func: str) -> str:
        """Replace an existing C++ function in source."""
        sig_pattern = re.compile(
            r'(?:[\w:*&<>\s]+)\s+' + re.escape(func_name) +
            r'\s*\([^)]*\)\s*(?:const|noexcept|override)?\s*\{',
            re.MULTILINE,
        )
        m = sig_pattern.search(source)
        if not m:
            return source
        brace_start = source.index('{', m.start())
        depth = 0
        end = brace_start
        for i, ch in enumerate(source[brace_start:], brace_start):
            if ch == '{':
                depth += 1
            elif ch == '}':
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break
        return source[:m.start()] + new_func + source[end:]

    @staticmethod
    def _insert_cpp_function(source: str, func_name: str, new_func: str) -> str:
        """Insert a new C++ function before main() or at end of file."""
        main_match = re.search(r'\bint\s+main\s*\(', source)
        if main_match:
            return source[:main_match.start()] + new_func + "\n\n" + source[main_match.start():]
        # Before last closing brace
        last_brace = source.rfind("}")
        if last_brace != -1:
            return source[:last_brace] + "\n\n" + new_func + "\n" + source[last_brace:]
        return source.rstrip() + "\n\n" + new_func + "\n"
