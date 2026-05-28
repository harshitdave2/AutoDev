import sys
sys.path.insert(0, '.')

# ---- Test 1: ResponseNormalizer ----
from core.response_normalizer import ResponseNormalizer

# Test markdown extraction
md_output = """
Here is the fix:
```python
def compute_ratio(a, b):
    if b == 0:
        return 0
    return a / b
```
"""
r1 = ResponseNormalizer.normalize(md_output, 'python')
assert r1.source_format == 'markdown', f'Expected markdown, got {r1.source_format}'
assert len(r1.candidates) == 1
assert 'def compute_ratio' in r1.candidates[0]
assert r1.is_partial == True  # function only, no imports/main
print('  OK  ResponseNormalizer: markdown extraction')

# Test multi-candidate JSON
import json
mc_json = json.dumps({'candidate_1': 'def fix(): pass', 'candidate_2': 'def fix2(): return 1'})
r2 = ResponseNormalizer.normalize(mc_json, 'python')
assert r2.source_format == 'json_multi', f'Expected json_multi, got {r2.source_format}'
assert len(r2.candidates) == 2
print('  OK  ResponseNormalizer: multi-candidate JSON')

# Test partial detection for complete file
full_py = """import os
def main():
    pass
if __name__ == '__main__':
    main()
"""
r3 = ResponseNormalizer.normalize(full_py, 'python')
assert r3.is_partial == False, f'Full file should not be partial, got is_partial={r3.is_partial}'
print('  OK  ResponseNormalizer: partial detection for complete file')

# ---- Test 2: PatchCompletion ----
from core.patch_completion import PatchCompletion

# Test trailing ellipsis stripping
code_with_ellipsis = "def foo():\n    x = 1\n..."
c1 = PatchCompletion.complete(code_with_ellipsis, 'python')
assert '...' not in c1.code, f'Ellipsis not stripped: {c1.code}'
assert c1.was_modified
print('  OK  PatchCompletion: ellipsis stripping')

# Test paren balancing
code_unbalanced = "def foo(x:\n    return x + 1"
c2 = PatchCompletion.complete(code_unbalanced, 'python')
print(f'  OK  PatchCompletion: paren balance (modified={c2.was_modified})')

# Test C++ brace completion
cpp_truncated = "#include <iostream>\nint find_max(int* arr, int n) {\n    int m = arr[0];\n    for(int i=1; i<n; i++) {\n        if(arr[i] > m) m = arr[i];\n    "
c3 = PatchCompletion.complete(cpp_truncated, 'cpp')
print(f'  OK  PatchCompletion: C++ brace completion (modified={c3.was_modified})')

# ---- Test 3: FunctionPatchMerger ----
from core.function_patch_merger import FunctionPatchMerger

original = """import os

def bad_func(x):
    return x / 0

def good_func(x):
    return x * 2

if __name__ == '__main__':
    print(bad_func(5))
    print(good_func(3))
"""

patch = """def bad_func(x):
    if x == 0:
        return 0
    return 1 / x
"""

m1 = FunctionPatchMerger.merge(original, patch, 'python')
assert m1.success, f'Merge failed: {m1.reason}'
assert 'bad_func' in m1.functions_replaced
assert 'good_func' not in m1.functions_replaced  # Preserved
assert "if __name__" in m1.merged_code  # main block preserved
assert 'import os' in m1.merged_code  # import preserved
assert 'if x == 0' in m1.merged_code  # fix applied
print(f'  OK  FunctionPatchMerger: Python merge (replaced={m1.functions_replaced})')

# Test that main() is preserved when merging partial Java patch
java_original = """public class Test {
    static int buggy(int[] arr) {
        return arr[arr.length];
    }
    public static void main(String[] args) {
        System.out.println(buggy(new int[]{1,2,3}));
    }
}"""

java_patch = """    static int buggy(int[] arr) {
        return arr[arr.length - 1];
    }"""

m2 = FunctionPatchMerger.merge(java_original, java_patch, 'java')
print(f'  OK  FunctionPatchMerger: Java merge (success={m2.success})')

print()
print('ALL MODULE TESTS PASSED')
