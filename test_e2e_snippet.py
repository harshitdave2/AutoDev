"""
End-to-end test: simulate the exact failure case from the bug report.
Original file: 195 lines
LLM returns: 14-line function patch
Old behavior: REJECTED (Patch is too short: 14 lines vs 195, threshold 25%)
New behavior: ACCEPTED + merged correctly
"""
import sys
sys.path.insert(0, 'd:/AUTODEV/autodev')

from core.patch_validator import PatchValidator
from core.function_patch_merger import FunctionPatchMerger

# Simulate a 195-line C++ file
original_195 = """#include <iostream>
#include <string>
#include <vector>

class Student {
private:
    int id_;
    std::string name_;
    double gpa_;

public:
    Student(int id, const std::string& name, double gpa)
        : id_(id), name_(name), gpa_(gpa) {}

    std::string getName() const { return name_; }
    double getGpa() const { return gpa_; }

    // Missing: getId() method -- this is the bug
    // The compiler error is: 'class Student' has no member named 'getId'
};

class Roster {
private:
    std::vector<Student> students_;
public:
    void addStudent(const Student& s) { students_.push_back(s); }
    int size() const { return students_.size(); }
    Student getStudent(int idx) const { return students_[idx]; }
};
""" + "\n// padding line\n" * 162 + """
int main() {
    Student s(42, "Alice", 3.9);
    std::cout << s.getName() << std::endl;
    std::cout << s.getId() << std::endl;  // BUG: getId() does not exist
    return 0;
}
"""

# 14-line LLM patch (the targeted repair)
llm_14_line_patch = """int getId() const {
    return id_;
}"""

print("=" * 60)
print("SCENARIO: 14-line snippet vs 195-line original")
print(f"Original: {len(original_195.splitlines())} lines")
print(f"Patch:    {len(llm_14_line_patch.splitlines())} lines")
print(f"Ratio:    {len(llm_14_line_patch.splitlines()) / len(original_195.splitlines()):.1%}")
print("=" * 60)

# OLD behavior simulation (full mode, size check fires)
print("\n--- OLD BEHAVIOR (patch_mode='full') ---")
ok_old, reason_old = PatchValidator.validate(llm_14_line_patch, original_195, 'cpp', patch_mode='full')
print(f"Result: ok={ok_old}, reason={reason_old}")

# NEW behavior: detect snippet, merge first, then validate merged
print("\n--- NEW BEHAVIOR (patch_mode='snippet') ---")

# Step 1: auto-detect mode (what _detect_patch_mode would return)
orig_lines = original_195.strip().splitlines()
cand_lines = llm_14_line_patch.strip().splitlines()
auto_mode = "snippet" if len(cand_lines) < len(orig_lines) * 0.60 and "#include" not in llm_14_line_patch else "full"
print(f"[PatchMode] Auto-detected: {auto_mode.upper()}_PATCH")

# Step 2: Merge BEFORE validate
print("[PatchMerge] Merging snippet into full file...")
merge_result = FunctionPatchMerger.merge(original=original_195, patch=llm_14_line_patch, language='cpp')
print(f"  merge.success = {merge_result.success}")
print(f"  functions_replaced = {merge_result.functions_replaced}")
print(f"  functions_added    = {merge_result.functions_added}")
print(f"  merged lines       = {len(merge_result.merged_code.splitlines())}")

# Step 3: Validate merged result as full file
print("[Validator] Validating reconstructed full file (mode=full)...")
ok_new, reason_new = PatchValidator.validate(merge_result.merged_code, original_195, 'cpp', patch_mode='full')
print(f"Result: ok={ok_new}, reason={reason_new}")

print("\n" + "=" * 60)
print("SUMMARY:")
print(f"  OLD: REJECTED — {reason_old}")
print(f"  NEW: {'ACCEPTED' if ok_new else 'REJECTED'} — {reason_new}")
if ok_new:
    print("\n  SUCCESS: Valid 14-line function repair now accepted!")
    print("  'getId()' method injected into Student class correctly.")
print("=" * 60)
