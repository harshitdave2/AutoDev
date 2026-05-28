import sys
sys.path.insert(0, '.')
from core.sanitizer import sanitize_llm_output
from core.syntax_repair import auto_fix_syntax

# Case 1: Malformed JSON with real newlines (the actual failure case from logs)
bad1 = '{\n"fixed_code": "from type_error import calculate_user_average\n\ndef run_reports():\n    print(\\"Starting system report generation...\\n\\")\n"\n}'
out1 = sanitize_llm_output(bad1)
print("=== Case 1: Malformed JSON (real newlines in string) ===")
print(repr(out1[:300]))
print()

# Case 2: Unterminated string — syntax_repair should close it
bad2 = 'def foo():\n    print("Starting system report generation...'
out2 = auto_fix_syntax(bad2, "python")
print("=== Case 2: auto_fix_syntax on unterminated string ===")
print(repr(out2))
print()

# Case 3: Well-formed JSON — should extract cleanly
good = '{"fixed_code": "def foo():\\n    return 42\\n"}'
out3 = sanitize_llm_output(good)
print("=== Case 3: Valid JSON extraction ===")
print(out3)
print()

# Case 4: JSON surrounded by prose
prose = 'Here is the fix:\n\n{"fixed_code": "x = 1\\nprint(x)\\n"}\n\nLet me know!'
out4 = sanitize_llm_output(prose)
print("=== Case 4: JSON surrounded by prose ===")
print(out4)
