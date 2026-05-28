import ast
import re


def _count_unescaped(line: str, char: str) -> int:
    """Count occurrences of char that are not preceded by a backslash."""
    return len(re.findall(r'(?<!\\)' + re.escape(char), line))


def _fix_unclosed_quote_on_line(line: str) -> str:
    """
    If a line has an odd number of unescaped double-quotes and ends inside
    a string, append a closing double-quote.  Same for single quotes.
    We only act when the line ends mid-string (no closing quote at EOL).
    """
    # Ignore comment lines and blank lines
    stripped = line.rstrip()
    if not stripped or stripped.lstrip().startswith('#'):
        return line

    dq = _count_unescaped(stripped, '"')
    sq = _count_unescaped(stripped, "'")

    # Only close if the count is odd AND the line doesn't already end with
    # a quote or closing paren/bracket (which would mean it was intentional).
    if dq % 2 != 0 and not stripped.endswith(('"', ')', ']', ',')):
        stripped += '"'
    elif sq % 2 != 0 and not stripped.endswith(("'", ')', ']', ',')):
        stripped += "'"

    # Preserve trailing whitespace of original line
    return stripped + line[len(line.rstrip()):]


def _count_braces_outside_strings(code: str):
    """
    Count '{' and '}' characters that are NOT inside string literals.
    This prevents false mismatch counts caused by braces in print statements
    or other string arguments.
    """
    opens = 0
    closes = 0
    in_single = False
    in_double = False
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

        if ch == '"' and not in_single:
            in_double = not in_double
            i += 1
            continue

        if ch == "'" and not in_double:
            in_single = not in_single
            i += 1
            continue

        if not in_single and not in_double:
            if ch == '{':
                opens += 1
            elif ch == '}':
                closes += 1

        i += 1

    return opens, closes


def auto_fix_syntax(code: str, language: str) -> str:
    """
    Attempt lightweight repairs of common minor syntax errors produced by
    truncated or malformed LLM output, then validate with ast.parse for Python.
    Falls back to the original code if repair still fails validation.
    """
    if not code or not code.strip():
        return code

    original_code = code

    # Step 0: Remove leftover JSON wrapper tokens
    # These can appear when the sanitizer's fallback path was not 100% clean.
    code = re.sub(r'^\s*\{\s*\n?', '', code)
    code = re.sub(r'^\s*"fixed_code"\s*:\s*"?', '', code)
    code = re.sub(r'"?\s*\}?\s*$', '', code)
    code = code.strip()

    # Step 1: Fix unclosed quotes (line-by-line) — safe for all languages
    lines = code.split('\n')
    repaired_lines = [_fix_unclosed_quote_on_line(ln) for ln in lines]

    # Step 2: Fix unbalanced parentheses per-line
    fixed_lines = []
    for line in repaired_lines:
        open_p = line.count('(')
        close_p = line.count(')')
        if open_p > close_p and line.rstrip().endswith(('(', ',', '+')):
            fixed_lines.append(line)
        elif open_p > close_p:
            fixed_lines.append(line.rstrip() + ')' * (open_p - close_p))
        else:
            fixed_lines.append(line)
    
    if language == 'java':
        lines_before_java = list(fixed_lines)  # snapshot before Java mutations
        java_lines = []
        total_lines = len(fixed_lines)
        for li, line in enumerate(fixed_lines):
            stripped = line.strip()
            # Skip blank lines and comment lines
            if not stripped or stripped.startswith(('/*', '*', '//')):
                java_lines.append(line)
                continue
            # Lines that must NOT get a semicolon appended
            no_semi_endings = (';', '{', '}', ',', '(', ')', '@', ':')
            no_semi_starts = (
                '//', '@', 'class ', 'interface ', 'enum ',
                'public class', 'private class', 'protected class',
                'if ', 'if(', 'else', 'for ', 'for(',
                'while ', 'while(', 'do ', 'try', 'catch', 'finally',
                'switch ', 'switch(',
                '/*', '*',
            )
            if stripped.endswith(no_semi_endings):
                java_lines.append(line)
                continue
            if any(stripped.startswith(kw) for kw in no_semi_starts):
                java_lines.append(line)
                continue
            # If the NEXT non-blank line starts with '{', this is a method/block header
            next_content = ''
            for ni in range(li + 1, total_lines):
                ns = fixed_lines[ni].strip()
                if ns:
                    next_content = ns
                    break
            if next_content.startswith('{') or next_content.startswith('->'):
                java_lines.append(line)
                continue
            # Lambda or annotation-like lines
            if '->' in stripped or stripped.startswith('//') or stripped.startswith('@'):
                java_lines.append(line)
                continue
            # Safe to add semicolon
            java_lines.append(line.rstrip() + ';')

        candidate_java = '\n'.join(java_lines)
        # Rollback guard: if brace balance got worse, revert
        orig_ob, orig_cb = _count_braces_outside_strings('\n'.join(lines_before_java))
        new_ob, new_cb = _count_braces_outside_strings(candidate_java)
        orig_deficit = abs(orig_ob - orig_cb)
        new_deficit = abs(new_ob - new_cb)
        if new_deficit <= orig_deficit:
            code = candidate_java
        else:
            print("[SyntaxRepair] Java semicolon pass worsened brace balance — reverting")
            code = '\n'.join(lines_before_java)
    elif language == 'python':
        py_lines = []
        for line in fixed_lines:
            stripped = line.strip()
            if re.match(r'^(if|elif|else|for|while|def|class)\b', stripped) and not stripped.endswith(':'):
                line = line.rstrip() + ':'
            py_lines.append(line)
        code = '\n'.join(py_lines)
    else:
        code = '\n'.join(fixed_lines)

    # Step 3: Fix unbalanced braces (whole-file) using string-aware counting
    # For Java and C++: only add closing braces for CLEARLY truncated output
    # (i.e. the model cut off mid-file). We are conservative: only append if
    # the imbalance is large (>=2) to avoid corrupting code that has braces in
    # string literals that fool a naive counter.
    open_b, close_b = _count_braces_outside_strings(code)
    deficit = open_b - close_b

    if language == 'python':
        # Python rarely uses braces for blocks; only fix dicts/sets
        if deficit > 0:
            code = code.rstrip() + '\n' + '}' * deficit
    elif language == 'java':
        # Only repair when clearly truncated (large imbalance)
        if deficit >= 2:
            code = code.rstrip() + '\n' + '}\n' * deficit

    # Step 4: Fix trivial Python indentation (only obvious zero-indent drops)
    if language == 'python':
        lines = code.split('\n')
        fixed = []
        current_indent = 0
        for line in lines:
            stripped = line.strip()
            if not stripped:
                fixed.append(line)
                continue

            actual_indent = len(line) - len(line.lstrip())
            outdent_kw = ('else:', 'elif ', 'except', 'except:', 'finally:')

            if actual_indent == 0 and current_indent > 0 and not stripped.startswith(outdent_kw):
                if fixed and fixed[-1].rstrip().endswith(':'):
                    line = ' ' * current_indent + stripped

            fixed.append(line)

            if stripped.endswith(':') and not stripped.startswith('#'):
                current_indent = actual_indent + 4
            elif stripped in ('return', 'break', 'continue', 'pass'):
                current_indent = max(0, current_indent - 4)

        code = '\n'.join(fixed)

    # Step 5: Ensure final newline
    if not code.endswith('\n'):
        code += '\n'

    # Step 6: Validate repaired code (Python only)
    if language == 'python':
        try:
            ast.parse(code)
        except SyntaxError:
            # Repair made things worse or couldn't help — give back original
            return original_code

    # Step 7: Logging
    if code.strip() != original_code.strip():
        print('Auto-repaired minor syntax issues.')

    return code
