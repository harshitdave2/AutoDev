"""Fix the malformed regex lines in bug_localizer.py (lines 107-115)"""
import re

path = 'd:/AUTODEV/autodev/core/bug_localizer.py'
src = open(path, 'r', encoding='utf-8').read()

lines = src.splitlines(keepends=True)

# Find and replace lines 107-115 (0-indexed: 106-114)
# The malformed block looks like:
#   _CPP_MISSING_MEMBER_RE = re.compile(
#       r\"...\"
#   )
# We need it to be:
#   _CPP_MISSING_MEMBER_RE = re.compile(
#       r"..."
#   )

new_lines = list(lines)

# Replace line 108 (0-indexed 107)
new_lines[107] = '        r"[\'\"?(?:class|struct)\\s+(\\w+)[\'\"?\\s+has no member named\\s+[\'\"?(\\w+)[\'\"?"\n'
# Build the correct patterns
pattern_block = (
    '    # Compiler-symbol regex patterns for missing-member C++ errors\n'
    '    _CPP_MISSING_MEMBER_RE = re.compile(\n'
    '        r"[\'\\\"]{0,1}(?:class|struct)\\s+(\\w+)[\'\\\"]{0,1}\\s+has no member named\\s+[\'\\\"]{0,1}(\\w+)[\'\\\"]{0,1}"\n'
    '    )\n'
    '    _CPP_UNDECLARED_RE = re.compile(\n'
    '        r"[\'\\\"]{0,1}(\\w+)[\'\\\"]{0,1}\\s+was not declared in this scope"\n'
    '    )\n'
    '    _CPP_NO_MEMBER_IN_RE = re.compile(\n'
    '        r"no member named\\s+[\'\\\"]{0,1}(\\w+)[\'\\\"]{0,1}\\s+in\\s+[\'\\\"]{0,1}(\\w+)[\'\\\"]{0,1}"\n'
    '    )\n'
)

# Find the exact block range
src_find = '    # Compiler-symbol regex patterns for missing-member C++ errors\n'
start = src.find(src_find)
end_marker = '\n    # Penalty keywords that lower suspicion'
end = src.find(end_marker, start)

if start != -1 and end != -1:
    src = src[:start] + pattern_block + src[end+1:]
    open(path, 'w', encoding='utf-8').write(src)
    print('Fixed regex block OK')
else:
    print(f'Markers not found: start={start}, end={end}')
