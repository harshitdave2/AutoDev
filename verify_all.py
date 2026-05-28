import sys
sys.path.insert(0, 'd:/AUTODEV/autodev')

print('=== Verifying all modified modules ===')

# 1. PatchValidator
from core.patch_validator import PatchValidator
print('[1] PatchValidator:')
orig = '#include <iostream>\nclass Student { int id_; };\nint main(){return 0;}'
snippet = 'int getId() { return id_; }'
ok, reason = PatchValidator.validate(snippet, orig, 'cpp', patch_mode='snippet')
print(f'    snippet mode: ok={ok}, reason={reason}')
ok2, reason2 = PatchValidator.validate(snippet, orig, 'cpp', patch_mode='full')
print(f'    full mode:    ok={ok2}, reason={reason2}')

# 2. FunctionPatchMerger
from core.function_patch_merger import FunctionPatchMerger
print('[2] FunctionPatchMerger:')
has_outline = hasattr(FunctionPatchMerger, '_extract_cpp_outline_methods')
print(f'    has _extract_cpp_outline_methods: {has_outline}')
patch_src = 'int Student::getId() { return id_; }'
if has_outline:
    outline = FunctionPatchMerger._extract_cpp_outline_methods(patch_src)
    print(f'    out-of-line methods detected: {list(outline.keys())}')

# 3. BugLocalizer
from core.bug_localizer import BugLocalizer
print('[3] BugLocalizer:')
checks = [
    '_score_frames', '_extract_suspicious_functions', '_extract_python_functions',
    '_extract_generic_functions', '_extract_cpp_functions_with_classes',
    '_extract_import_deps', '_is_user_code', '_build_summary',
    '_CPP_MISSING_MEMBER_RE', '_CPP_NO_MEMBER_IN_RE', '_CPP_UNDECLARED_RE',
]
for c in checks:
    status = 'OK' if hasattr(BugLocalizer, c) else 'MISSING'
    print(f'    {status}: {c}')

# Test compiler-symbol detection
stderr_test = "buggy.cpp:42:5: error: 'class Student' has no member named 'getId'"
frames = BugLocalizer._parse_cpp_errors(stderr_test, 'buggy.cpp', '.')
if frames:
    f = frames[0]
    print(f'    Symbol detection: func_name={f.function_name!r}, score={f.suspicion_score}')

# 4. RetryManager
from agent.retry_manager import RetryManager
print('[4] RetryManager:')
print('    has _detect_patch_mode:', hasattr(RetryManager, '_detect_patch_mode'))
print('    has _validate_candidate:', hasattr(RetryManager, '_validate_candidate'))

print('=== All verifications complete ===')
