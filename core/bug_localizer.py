"""
core/bug_localizer.py
----------------------
Intelligent bug localization for AutoDev.

Improves on the basic traceback parsing in analyzer.py by:
  1. Extracting the full stack frame chain with suspicion scores
  2. Performing caller-chain analysis
  3. Mapping import dependencies of the buggy function
  4. Detecting multi-file bugs (imported module vs entry script)
  5. Ranking suspicious functions by likelihood of containing the root bug

The BugLocalizer does NOT modify files. It provides intelligence to the
retry_manager to improve patch_target selection and LLM context quality.

Usage:
    result = BugLocalizer.localize(
        file_path=script_path,
        stderr=run_result["stderr"],
        language="python",
    )
    print(result.primary_target)    # File most likely to contain the bug
    print(result.suspicious_funcs)  # Ranked list of suspicious functions
    print(result.summary)           # Human-readable localization report
"""

import ast
import re
import os
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Tuple, Any


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class StackFrame:
    """A single frame extracted from a traceback or compiler error."""
    file_path: str      # Absolute or relative path to source file
    line_number: int    # 1-indexed line number
    function_name: str  # Function or method name ("<module>" for top-level)
    code_snippet: str   # The line of code at that position (may be empty)
    is_user_code: bool  # True if this frame is in user code (not stdlib)
    suspicion_score: float = 0.0  # Computed suspicion weight


@dataclass
class SuspiciousFunction:
    """A function ranked by likelihood of containing the bug."""
    name: str
    file_path: str
    start_line: int
    end_line: int
    suspicion_score: float
    source: str         # Extracted source code of this function
    reason: str         # Why it's suspicious


@dataclass
class LocalizationResult:
    """
    Complete bug localization result.

    Attributes:
        primary_target    : File most likely to contain the root bug.
        primary_function  : Name of the most suspicious function.
        stack_frames      : All extracted stack frames (deepest first).
        suspicious_funcs  : Ranked list of suspicious functions.
        import_deps       : Modules imported by the primary function.
        is_multi_file     : True if bug spans multiple files.
        crash_line        : The line number of the crash.
        summary           : Human-readable localization report.
        raw_traceback     : The original stderr used for localization.
    """
    primary_target: str
    primary_function: str
    stack_frames: List[StackFrame]
    suspicious_funcs: List[SuspiciousFunction]
    import_deps: List[str]
    is_multi_file: bool
    crash_line: int
    summary: str
    raw_traceback: str


# ---------------------------------------------------------------------------
# Localizer
# ---------------------------------------------------------------------------

class BugLocalizer:
    """
    Intelligent bug localization engine.

    All methods are classmethods for easy use without instantiation.
    """

    # Patterns for common system/library paths to exclude
    _STDLIB_PATTERNS = [
        "site-packages", "dist-packages", "/usr/lib", "\\usr\\lib",
        "python3.", "python2.", "lib\\python", "lib/python",
        "<frozen ", "<stdin>", "<string>",
    ]

    # Compiler-symbol regex patterns for missing-member C++ errors
    _CPP_MISSING_MEMBER_RE = re.compile(
        r"['\"]{0,1}(?:class|struct)\s+(\w+)['\"]{0,1}\s+has no member named\s+['\"]{0,1}(\w+)['\"]{0,1}"
    )
    _CPP_UNDECLARED_RE = re.compile(
        r"['\"]{0,1}(\w+)['\"]{0,1}\s+was not declared in this scope"
    )
    _CPP_NO_MEMBER_IN_RE = re.compile(
        r"no member named\s+['\"]{0,1}(\w+)['\"]{0,1}\s+in\s+['\"]{0,1}(\w+)['\"]{0,1}"
    )
    # Penalty keywords that lower suspicion (called by standard library internals)
    _STDLIB_INDICATORS = frozenset({
        "runpy", "importlib", "threading", "subprocess", "asyncio",
        "contextlib", "functools", "abc", "warnings",
    })

    @classmethod
    def localize(
        cls,
        file_path: str,
        stderr: str,
        language: str = "python",
        project_root: Optional[str] = None,
    ) -> LocalizationResult:
        """
        Analyze stderr to localize the bug and rank suspicious functions.

        Args:
            file_path    : Entry script path (used as baseline for user-code detection).
            stderr       : Full standard error output from the failed run.
            language     : "python", "java", or "cpp".
            project_root : Optional project root for multi-file detection.

        Returns:
            LocalizationResult with ranked suspicious functions and primary target.
        """
        if not stderr:
            stderr = ""

        if project_root is None:
            project_root = os.path.dirname(os.path.abspath(file_path)) if file_path else os.getcwd()

        # Route to language-specific parser
        if language == "python":
            frames = cls._parse_python_traceback(stderr, project_root)
        elif language == "java":
            frames = cls._parse_java_traceback(stderr, project_root)
        elif language == "cpp":
            frames = cls._parse_cpp_errors(stderr, file_path, project_root)
        else:
            frames = cls._parse_python_traceback(stderr, project_root)  # Fallback

        # Score frames
        frames = cls._score_frames(frames)

        # Determine primary target
        user_frames = [f for f in frames if f.is_user_code]
        primary_frame = user_frames[-1] if user_frames else (frames[-1] if frames else None)

        primary_target = file_path  # Default
        primary_function = "<unknown>"
        crash_line = 0

        if primary_frame:
            if os.path.exists(primary_frame.file_path):
                primary_target = primary_frame.file_path
            crash_line = primary_frame.line_number
            primary_function = primary_frame.function_name

        # Extract suspicious functions from the primary file
        suspicious_funcs = cls._extract_suspicious_functions(
            primary_target, frames, language
        )

        # Detect import dependencies of primary function
        import_deps = cls._extract_import_deps(primary_target, primary_function, language)

        # Detect multi-file bugs
        unique_user_files = set(
            f.file_path for f in frames if f.is_user_code and os.path.exists(f.file_path)
        )
        is_multi_file = len(unique_user_files) > 1

        # Build summary
        summary = cls._build_summary(
            primary_target, primary_function, crash_line,
            suspicious_funcs, is_multi_file, frames
        )

        return LocalizationResult(
            primary_target=primary_target,
            primary_function=primary_function,
            stack_frames=frames,
            suspicious_funcs=suspicious_funcs,
            import_deps=import_deps,
            is_multi_file=is_multi_file,
            crash_line=crash_line,
            summary=summary,
            raw_traceback=stderr,
        )

    # -----------------------------------------------------------------------
    # Language-specific traceback parsers
    # -----------------------------------------------------------------------

    @classmethod
    def _parse_python_traceback(
        cls, stderr: str, project_root: str
    ) -> List[StackFrame]:
        """Parse Python traceback into StackFrame list."""
        frames = []
        # Match: File "path", line N, in func_name
        pattern = re.compile(
            r'File\s+"([^"]+)",\s+line\s+(\d+),\s+in\s+(\S+)'
        )
        # Match the code snippet that follows (next non-empty line)
        lines = stderr.splitlines()
        for i, line in enumerate(lines):
            m = pattern.search(line)
            if not m:
                continue
            file_path = m.group(1)
            line_no = int(m.group(2))
            func_name = m.group(3)
            # Try to get the code snippet from the next line
            snippet = ""
            if i + 1 < len(lines):
                snippet = lines[i + 1].strip()
            is_user = cls._is_user_code(file_path, project_root)
            frames.append(StackFrame(
                file_path=file_path,
                line_number=line_no,
                function_name=func_name,
                code_snippet=snippet,
                is_user_code=is_user,
            ))
        return frames

    @classmethod
    def _parse_java_traceback(
        cls, stderr: str, project_root: str
    ) -> List[StackFrame]:
        """Parse Java stack trace into StackFrame list."""
        frames = []
        # Match: at com.example.Class.method(File.java:42)
        pattern = re.compile(
            r'at\s+([\w.$<>]+)\.([\w$<>]+)\(([^:)]+):(\d+)\)'
        )
        for m in pattern.finditer(stderr):
            class_name = m.group(1)
            method_name = m.group(2)
            file_name = m.group(3)
            line_no = int(m.group(4))
            # Heuristic: user code if class doesn't start with java/sun/com.sun/org.
            is_user = not any(class_name.startswith(p) for p in [
                "java.", "javax.", "sun.", "com.sun.", "org.junit",
                "jdk.", "org.springframework.",
            ])
            frames.append(StackFrame(
                file_path=file_name,
                line_number=line_no,
                function_name=f"{class_name}.{method_name}",
                code_snippet="",
                is_user_code=is_user,
            ))
        return frames

    @classmethod
    def _parse_cpp_errors(
        cls, stderr: str, file_path: str, project_root: str
    ) -> List[StackFrame]:
        """Parse GCC/Clang compiler and runtime errors into StackFrame list.

        Includes compiler-symbol-aware localization:
          - 'class X has no member named Y'  -> map to class X definition
          - 'Y was not declared in this scope'
          - 'no member named Y in X'         -> map to class X definition
        """
        frames = []
        # Match: file.cpp:42:5: error: ...
        pattern = re.compile(
            r'([^\s:]+\.(?:cpp|cc|cxx|h|hpp)):(\d+)(?::\d+)?:\s*(error|warning|note):\s*(.*)'
        )
        for m in pattern.finditer(stderr):
            source_file = m.group(1)
            line_no = int(m.group(2))
            kind = m.group(3)
            message = m.group(4)
            is_user = cls._is_user_code(source_file, project_root)

            # ── Compiler-symbol-aware localization ─────────────────────
            func_name = f"<{kind}>"
            suspicion_boost = 0.0

            # Pattern A: "'class Student' has no member named 'getId'"
            mm = cls._CPP_MISSING_MEMBER_RE.search(message)
            if mm:
                class_name = mm.group(1)
                missing_method = mm.group(2)
                func_name = class_name
                suspicion_boost = 8.0
                message = (
                    f"Missing member: {missing_method} -- "
                    f"class {class_name} definition is the repair target"
                )
                print(
                    f"[BugLocalizer] Compiler-symbol: class {class_name!r} "
                    f"missing method {missing_method!r} -- targeting class definition"
                )

            # Pattern B: "no member named 'getId' in 'Student'"
            elif cls._CPP_NO_MEMBER_IN_RE.search(message):
                nm = cls._CPP_NO_MEMBER_IN_RE.search(message)
                missing_method = nm.group(1)
                class_name = nm.group(2)
                func_name = class_name
                suspicion_boost = 8.0
                message = (
                    f"Missing member: {missing_method} in {class_name} "
                    f"-- class definition is the repair target"
                )
                print(
                    f"[BugLocalizer] Compiler-symbol: class {class_name!r} "
                    f"missing method {missing_method!r}"
                )

            # Pattern C: "'getId' was not declared in this scope"
            elif cls._CPP_UNDECLARED_RE.search(message):
                ud = cls._CPP_UNDECLARED_RE.search(message)
                undeclared_name = ud.group(1)
                func_name = undeclared_name
                suspicion_boost = 4.0
                message = f"Undeclared symbol: {undeclared_name}"
                print(
                    f"[BugLocalizer] Compiler-symbol: {undeclared_name!r} "
                    f"not declared -- possible missing method"
                )

            frame = StackFrame(
                file_path=source_file,
                line_number=line_no,
                function_name=func_name,
                code_snippet=message[:160],
                is_user_code=is_user,
            )
            frame.suspicion_score = suspicion_boost
            frames.append(frame)

        # Also match runtime errors like segfault with address
        if not frames and file_path:
            frames.append(StackFrame(
                file_path=file_path,
                line_number=0,
                function_name="<runtime>",
                code_snippet=stderr.strip().splitlines()[-1][:120] if stderr.strip() else "",
                is_user_code=True,
            ))
        return frames

    # -----------------------------------------------------------------------
    # Frame scoring

    @classmethod
    def _score_frames(cls, frames):
        """
        Assign suspicion scores to all stack frames.

        Scoring heuristics:
          - User code frames score higher than stdlib frames
          - Deeper frames (closer to crash site) score higher
          - Frames with code snippets score slightly higher
          - Frames from well-known stdlib modules score very low
        """
        n = len(frames)
        for i, frame in enumerate(frames):
            # Don't overwrite a suspicion_boost already set by compiler-symbol detection
            if frame.suspicion_score > 0.0:
                continue

            score = 0.0

            # Depth bonus: later frames (closer to crash) are more suspicious
            depth_bonus = (i + 1) / n if n > 0 else 0.5
            score += depth_bonus * 5.0

            # User code bonus
            if frame.is_user_code:
                score += 4.0

            # Code snippet presence
            if frame.code_snippet:
                score += 0.5

            # Stdlib penalty
            func_lower = frame.function_name.lower()
            if any(ind in func_lower for ind in cls._STDLIB_INDICATORS):
                score -= 2.0

            # Module-level calls get mild boost (often where bugs live)
            if frame.function_name == "<module>":
                score += 1.0

            frame.suspicion_score = max(0.0, score)

        return frames

    # -----------------------------------------------------------------------
    # Suspicious function extraction
    # -----------------------------------------------------------------------

    @classmethod
    def _extract_suspicious_functions(
        cls,
        file_path,
        frames,
        language,
    ):
        """
        Extract and rank the most suspicious functions from the source file.
        """
        if not file_path or not os.path.exists(file_path):
            return []

        try:
            with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                source = f.read()
        except Exception:
            return []

        # Group frames by function name to accumulate suspicion
        func_suspicion = {}
        func_frame = {}
        for frame in frames:
            if not frame.is_user_code:
                continue
            name = frame.function_name
            func_suspicion[name] = func_suspicion.get(name, 0.0) + frame.suspicion_score
            if name not in func_frame or frame.suspicion_score > func_frame[name].suspicion_score:
                func_frame[name] = frame

        suspicious_funcs = []

        if language == "python":
            suspicious_funcs = cls._extract_python_functions(
                source, file_path, func_suspicion, func_frame
            )
        elif language == "cpp":
            suspicious_funcs = cls._extract_cpp_functions_with_classes(
                source, file_path, func_suspicion, func_frame
            )
        elif language == "java":
            suspicious_funcs = cls._extract_generic_functions(
                source, file_path, func_suspicion, func_frame, language
            )

        # Sort by suspicion score descending
        suspicious_funcs.sort(key=lambda f: f.suspicion_score, reverse=True)
        return suspicious_funcs[:5]  # Return top 5

    @staticmethod
    def _extract_python_functions(
        source,
        file_path,
        func_suspicion,
        func_frame,
    ):
        """Extract Python functions using AST."""
        import ast as _ast
        results = []
        try:
            tree = _ast.parse(source)
        except SyntaxError:
            return results

        lines = source.splitlines()
        for node in _ast.walk(tree):
            if not isinstance(node, (_ast.FunctionDef, _ast.AsyncFunctionDef)):
                continue
            if not hasattr(node, "end_lineno"):
                continue
            func_src = "\n".join(lines[node.lineno - 1: node.end_lineno])
            suspicion = func_suspicion.get(node.name, 0.0)
            frame = func_frame.get(node.name)
            reason = (
                f"Referenced in traceback at line {frame.line_number}"
                if frame else "Not directly in traceback but in suspicious file"
            )
            results.append(SuspiciousFunction(
                name=node.name,
                file_path=file_path,
                start_line=node.lineno,
                end_line=node.end_lineno,
                suspicion_score=suspicion,
                source=func_src[:2000],
                reason=reason,
            ))
        return results

    @staticmethod
    def _extract_generic_functions(
        source,
        file_path,
        func_suspicion,
        func_frame,
        language,
    ):
        """Extract Java/C++ methods using regex-based approach."""
        results = []
        lines = source.splitlines()

        if language == "java":
            pattern = re.compile(
                r'(?:public|private|protected|static|final|void|\s)+'
                r'([\w<>\[\]]+)\s+(\w+)\s*\([^)]*\)\s*(?:throws\s+[\w,\s]+)?\s*\{',
                re.MULTILINE,
            )
        else:  # cpp
            pattern = re.compile(
                r'(?:[\w:<>*&\s]+)\s+(\w+)\s*\([^)]*\)\s*(?:const|noexcept)?\s*\{',
                re.MULTILINE,
            )

        for m in pattern.finditer(source):
            func_name = m.group(2) if language == "java" else m.group(1)
            start_line = source[:m.start()].count("\n") + 1
            suspicion = func_suspicion.get(func_name, 0.0)
            end_line = min(start_line + 30, len(lines))
            func_src = "\n".join(lines[start_line - 1: end_line])
            frame = func_frame.get(func_name)
            reason = (
                f"Referenced in traceback at line {frame.line_number}"
                if frame else "Pattern matched in suspicious file"
            )
            results.append(SuspiciousFunction(
                name=func_name,
                file_path=file_path,
                start_line=start_line,
                end_line=end_line,
                suspicion_score=suspicion,
                source=func_src[:2000],
                reason=reason,
            ))
        return results

    @staticmethod
    def _extract_cpp_functions_with_classes(
        source,
        file_path,
        func_suspicion,
        func_frame,
    ):
        """
        Extract C++ functions AND class definitions when a class name is a suspect.

        When the compiler error targets a specific class (e.g. 'class Student has
        no member named getId'), we find the entire class body and return it as
        the top SuspiciousFunction so the LLM gets the full class context.
        """
        results = []
        lines = source.splitlines()

        # First pass: are any suspects actually CLASS names in this file?
        for suspect_name, score in func_suspicion.items():
            class_pattern = re.compile(
                r'\bclass\s+' + re.escape(suspect_name) + r'\b[^{;]*\{',
                re.MULTILINE,
            )
            cm = class_pattern.search(source)
            if cm:
                start_line = source[:cm.start()].count('\n') + 1
                try:
                    brace_start = source.index('{', cm.start())
                except ValueError:
                    continue
                depth = 0
                end_pos = brace_start
                for i, ch in enumerate(source[brace_start:], brace_start):
                    if ch == '{':
                        depth += 1
                    elif ch == '}':
                        depth -= 1
                        if depth == 0:
                            end_pos = i + 1
                            break
                end_line = source[:end_pos].count('\n') + 1
                class_src = '\n'.join(lines[start_line - 1: end_line])
                frame = func_frame.get(suspect_name)
                reason = (
                    f"Class definition targeted: compiler reported missing member "
                    f"(line {frame.line_number})" if frame
                    else f"Class {suspect_name} identified as repair target by compiler error"
                )
                results.append(SuspiciousFunction(
                    name=suspect_name,
                    file_path=file_path,
                    start_line=start_line,
                    end_line=end_line,
                    suspicion_score=score,
                    source=class_src[:3000],
                    reason=reason,
                ))

        # Second pass: regular function suspects not yet captured
        func_pattern = re.compile(
            r'(?:[\w:*&<>\s]+)\s+(\w+)\s*\([^)]*\)\s*(?:const|noexcept)?\s*\{',
            re.MULTILINE,
        )
        captured_names = {r.name for r in results}
        for m in func_pattern.finditer(source):
            func_name = m.group(1)
            if func_name in ('if', 'for', 'while', 'switch', 'catch', 'class'):
                continue
            if func_name in captured_names:
                continue
            start_line = source[:m.start()].count('\n') + 1
            end_line = min(start_line + 30, len(lines))
            func_src = '\n'.join(lines[start_line - 1: end_line])
            suspicion = func_suspicion.get(func_name, 0.0)
            frame = func_frame.get(func_name)
            reason = (
                f"Referenced in compiler error at line {frame.line_number}" if frame
                else "Pattern matched in suspicious file"
            )
            results.append(SuspiciousFunction(
                name=func_name,
                file_path=file_path,
                start_line=start_line,
                end_line=end_line,
                suspicion_score=suspicion,
                source=func_src[:2000],
                reason=reason,
            ))

        return results

    # -----------------------------------------------------------------------
    # Import dependency analysis
    # -----------------------------------------------------------------------

    @staticmethod
    def _extract_import_deps(
        file_path,
        function_name,
        language,
    ):
        """
        Extract the names of modules imported in the source file.
        Used to provide context about what the buggy function depends on.
        """
        if not file_path or not os.path.exists(file_path):
            return []

        try:
            with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                source = f.read()
        except Exception:
            return []

        deps = []

        if language == "python":
            import ast as _ast
            try:
                tree = _ast.parse(source)
                for node in _ast.walk(tree):
                    if isinstance(node, _ast.Import):
                        for alias in node.names:
                            deps.append(alias.name.split(".")[0])
                    elif isinstance(node, _ast.ImportFrom):
                        if node.module:
                            deps.append(node.module.split(".")[0])
            except SyntaxError:
                pass
        elif language == "java":
            for m in re.finditer(r'^import\s+([\w.]+)', source, re.MULTILINE):
                deps.append(m.group(1).split(".")[-1])
        elif language == "cpp":
            for m in re.finditer(r'#include\s+[<"]([^>"]+)[>"]', source):
                deps.append(m.group(1))

        # Remove duplicates while preserving order
        seen = set()
        unique_deps = []
        for d in deps:
            if d not in seen:
                seen.add(d)
                unique_deps.append(d)
        return unique_deps

    # -----------------------------------------------------------------------
    # Helpers
    # -----------------------------------------------------------------------

    @classmethod
    def _is_user_code(cls, file_path, project_root):
        """Return True if the file path is user code (not stdlib/library)."""
        if not file_path:
            return False
        normalized = file_path.replace("\\", "/")
        for pattern in cls._STDLIB_PATTERNS:
            if pattern in normalized:
                return False
        # Relative paths or paths within project_root are user code
        try:
            abs_path = os.path.abspath(file_path)
            abs_root = os.path.abspath(project_root)
            if os.path.commonpath([abs_path, abs_root]) == abs_root:
                return True
        except (ValueError, OSError):
            pass
        # Default: if it exists on disk, it's likely user code
        return os.path.exists(file_path)

    @staticmethod
    def _build_summary(
        primary_target,
        primary_function,
        crash_line,
        suspicious_funcs,
        is_multi_file,
        frames,
    ):
        """Build a concise human-readable localization summary."""
        target_name = os.path.basename(primary_target) if primary_target else "unknown"
        lines = [
            f"[BugLocalizer] Primary target: {target_name}",
            f"  Crash function: {primary_function} (line {crash_line})",
            f"  Stack depth: {len(frames)} frames",
        ]
        if is_multi_file:
            lines.append("  [!] Multi-file bug detected")
        if suspicious_funcs:
            top = suspicious_funcs[0]
            lines.append(
                f"  Top suspect: {top.name} "
                f"(lines {top.start_line}-{top.end_line}, "
                f"score={top.suspicion_score:.1f})"
            )
        return "\n".join(lines)
