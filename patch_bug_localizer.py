import re

path = 'd:/AUTODEV/autodev/core/bug_localizer.py'
src = open(path, 'r', encoding='utf-8').read()

# ── CHANGE 1: Add compiler-symbol class attrs before _STDLIB_INDICATORS ──────
old1 = '    # Penalty keywords that lower suspicion (called by standard library internals)\n    _STDLIB_INDICATORS = frozenset({'
new1 = (
    '    # Compiler-symbol regex patterns for missing-member C++ errors\n'
    '    _CPP_MISSING_MEMBER_RE = re.compile(\n'
    r"        r\"['\"]?(?:class|struct)\s+(\w+)['\"]?\s+has no member named\s+['\"]?(\w+)['\"]?\""
    '\n    )\n'
    '    _CPP_UNDECLARED_RE = re.compile(\n'
    r"        r\"['\"]?(\w+)['\"]?\s+was not declared in this scope\""
    '\n    )\n'
    '    _CPP_NO_MEMBER_IN_RE = re.compile(\n'
    r"        r\"no member named\s+['\"]?(\w+)['\"]?\s+in\s+['\"]?(\w+)['\"]?\""
    '\n    )\n\n'
    '    # Penalty keywords that lower suspicion (called by standard library internals)\n'
    '    _STDLIB_INDICATORS = frozenset({'
)
if old1 in src:
    src = src.replace(old1, new1, 1)
    print('CHANGE 1: compiler-symbol class attrs added')
else:
    print('CHANGE 1: WARNING not found')

# ── CHANGE 2: Replace _parse_cpp_errors with symbol-aware version ─────────────
OLD2_START = '    @classmethod\n    def _parse_cpp_errors(\n        cls, stderr: str, file_path: str, project_root: str\n    ) -> List[StackFrame]:\n        """Parse GCC/Clang compiler and runtime errors into StackFrame list."""'
OLD2_END   = '        return frames\n\n    # -----------------------------------------------------------------------\n    # Frame scoring'

start_idx = src.find(OLD2_START)
end_idx   = src.find(OLD2_END, start_idx)

if start_idx == -1 or end_idx == -1:
    print('CHANGE 2: WARNING boundaries not found')
else:
    NEW2 = (
        '    @classmethod\n'
        '    def _parse_cpp_errors(\n'
        '        cls, stderr: str, file_path: str, project_root: str\n'
        '    ) -> List[StackFrame]:\n'
        '        """Parse GCC/Clang compiler and runtime errors into StackFrame list.\n\n'
        '        Includes compiler-symbol-aware localization:\n'
        "          - 'class X has no member named Y'  -> map to class X definition\n"
        "          - 'Y was not declared in this scope'\n"
        "          - 'no member named Y in X'         -> map to class X definition\n"
        '        """\n'
        '        frames = []\n'
        '        # Match: file.cpp:42:5: error: ...\n'
        '        pattern = re.compile(\n'
        r"            r'([^\s:]+\.(?:cpp|cc|cxx|h|hpp)):(\d+)(?::\d+)?:\s*(error|warning|note):\s*(.*)'"
        '\n        )\n'
        '        for m in pattern.finditer(stderr):\n'
        '            source_file = m.group(1)\n'
        '            line_no = int(m.group(2))\n'
        '            kind = m.group(3)\n'
        '            message = m.group(4)\n'
        '            is_user = cls._is_user_code(source_file, project_root)\n\n'
        '            # ── Compiler-symbol-aware localization ─────────────────────\n'
        '            func_name = f"<{kind}>"\n'
        '            suspicion_boost = 0.0\n\n'
        '            # Pattern A: "\'class Student\' has no member named \'getId\'"\n'
        '            mm = cls._CPP_MISSING_MEMBER_RE.search(message)\n'
        '            if mm:\n'
        '                class_name = mm.group(1)\n'
        '                missing_method = mm.group(2)\n'
        '                func_name = class_name\n'
        '                suspicion_boost = 8.0\n'
        '                message = (\n'
        '                    f"Missing member: {missing_method} -- "\n'
        '                    f"class {class_name} definition is the repair target"\n'
        '                )\n'
        '                print(\n'
        '                    f"[BugLocalizer] Compiler-symbol: class {class_name!r} "\n'
        '                    f"missing method {missing_method!r} -- targeting class definition"\n'
        '                )\n\n'
        '            # Pattern B: "no member named \'getId\' in \'Student\'"\n'
        '            elif cls._CPP_NO_MEMBER_IN_RE.search(message):\n'
        '                nm = cls._CPP_NO_MEMBER_IN_RE.search(message)\n'
        '                missing_method = nm.group(1)\n'
        '                class_name = nm.group(2)\n'
        '                func_name = class_name\n'
        '                suspicion_boost = 8.0\n'
        '                message = (\n'
        '                    f"Missing member: {missing_method} in {class_name} "\n'
        '                    f"-- class definition is the repair target"\n'
        '                )\n'
        '                print(\n'
        '                    f"[BugLocalizer] Compiler-symbol: class {class_name!r} "\n'
        '                    f"missing method {missing_method!r}"\n'
        '                )\n\n'
        '            # Pattern C: "\'getId\' was not declared in this scope"\n'
        '            elif cls._CPP_UNDECLARED_RE.search(message):\n'
        '                ud = cls._CPP_UNDECLARED_RE.search(message)\n'
        '                undeclared_name = ud.group(1)\n'
        '                func_name = undeclared_name\n'
        '                suspicion_boost = 4.0\n'
        '                message = f"Undeclared symbol: {undeclared_name}"\n'
        '                print(\n'
        '                    f"[BugLocalizer] Compiler-symbol: {undeclared_name!r} "\n'
        '                    f"not declared -- possible missing method"\n'
        '                )\n\n'
        '            frame = StackFrame(\n'
        '                file_path=source_file,\n'
        '                line_number=line_no,\n'
        '                function_name=func_name,\n'
        '                code_snippet=message[:160],\n'
        '                is_user_code=is_user,\n'
        '            )\n'
        '            frame.suspicion_score = suspicion_boost\n'
        '            frames.append(frame)\n\n'
        '        # Also match runtime errors like segfault with address\n'
        '        if not frames and file_path:\n'
        '            frames.append(StackFrame(\n'
        '                file_path=file_path,\n'
        '                line_number=0,\n'
        '                function_name="<runtime>",\n'
        '                code_snippet=stderr.strip().splitlines()[-1][:120] if stderr.strip() else "",\n'
        '                is_user_code=True,\n'
        '            ))\n'
        '        return frames\n'
    )
    src = src[:start_idx] + NEW2 + '\n    # -----------------------------------------------------------------------\n    # Frame scoring'
    print('CHANGE 2: _parse_cpp_errors rewritten with symbol-aware logic')

# ── CHANGE 3: Route C++ through _extract_cpp_functions_with_classes ───────────
old3 = (
    '        if language == "python":\n'
    '            suspicious_funcs = cls._extract_python_functions(\n'
    '                source, file_path, func_suspicion, func_frame\n'
    '            )\n'
    '        elif language in ("java", "cpp"):\n'
    '            suspicious_funcs = cls._extract_generic_functions(\n'
    '                source, file_path, func_suspicion, func_frame, language\n'
    '            )'
)
new3 = (
    '        if language == "python":\n'
    '            suspicious_funcs = cls._extract_python_functions(\n'
    '                source, file_path, func_suspicion, func_frame\n'
    '            )\n'
    '        elif language == "cpp":\n'
    '            suspicious_funcs = cls._extract_cpp_functions_with_classes(\n'
    '                source, file_path, func_suspicion, func_frame\n'
    '            )\n'
    '        elif language == "java":\n'
    '            suspicious_funcs = cls._extract_generic_functions(\n'
    '                source, file_path, func_suspicion, func_frame, language\n'
    '            )'
)
if old3 in src:
    src = src.replace(old3, new3, 1)
    print('CHANGE 3: C++ routed to _extract_cpp_functions_with_classes')
else:
    print('CHANGE 3: WARNING routing block not found')

# ── CHANGE 4: Add _extract_cpp_functions_with_classes before import dep section ─
ANCHOR4 = '    # -----------------------------------------------------------------------\n    # Import dependency analysis'
NEW_METHOD4 = '''    @staticmethod
    def _extract_cpp_functions_with_classes(
        source,
        file_path,
        func_suspicion,
        func_frame,
    ):
        """
        Extract C++ functions AND class definitions when a class name is a suspect.

        When the compiler error targets a specific class (e.g. "class Student has
        no member named 'getId'"), we find the entire class body and return it as
        the top SuspiciousFunction so the LLM gets the full class context.
        """
        results = []
        lines = source.splitlines()

        # First pass: are any suspects actually CLASS names in this file?
        for suspect_name, score in func_suspicion.items():
            class_pattern = re.compile(
                r'\\bclass\\s+' + re.escape(suspect_name) + r'\\b[^{;]*\\{',
                re.MULTILINE,
            )
            cm = class_pattern.search(source)
            if cm:
                start_line = source[:cm.start()].count('\\n') + 1
                brace_start = source.index('{', cm.start())
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
                end_line = source[:end_pos].count('\\n') + 1
                class_src = '\\n'.join(lines[start_line - 1: end_line])
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

        # Second pass: regular function suspects
        func_pattern = re.compile(
            r'(?:[\\w:*&<>\\s]+)\\s+(\\w+)\\s*\\([^)]*\\)\\s*(?:const|noexcept)?\\s*\\{',
            re.MULTILINE,
        )
        captured_names = {r.name for r in results}
        for m in func_pattern.finditer(source):
            func_name = m.group(1)
            if func_name in ('if', 'for', 'while', 'switch', 'catch', 'class'):
                continue
            if func_name in captured_names:
                continue
            start_line = source[:m.start()].count('\\n') + 1
            end_line = min(start_line + 30, len(lines))
            func_src = '\\n'.join(lines[start_line - 1: end_line])
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

    '''

if ANCHOR4 in src and '_extract_cpp_functions_with_classes' not in src:
    src = src.replace(ANCHOR4, NEW_METHOD4 + ANCHOR4, 1)
    print('CHANGE 4: _extract_cpp_functions_with_classes added')
elif '_extract_cpp_functions_with_classes' in src:
    print('CHANGE 4: method already exists')
else:
    print('CHANGE 4: WARNING anchor not found')

open(path, 'w', encoding='utf-8').write(src)
print('bug_localizer.py written successfully')
