import os
import sys
import hashlib
import re
import time

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from models.base_model import BaseModel
from core.bug_memory import BugMemory
from core.sanitizer import _strip_bos_artifacts, _extract_json_block
from core.response_normalizer import ResponseNormalizer, NormalizedOutput
from core.patch_completion import PatchCompleter


def strip_rich_tags(text: str):
    # Match specific rich format tags to avoid removing array indices like [10] or [ii]
    return re.sub(r"\[/?(?:bold|dim|italic|underline|blink|reverse|strike|red|green|yellow|blue|magenta|cyan|white|black|#\w+)[^\]]*\]", "", text, flags=re.IGNORECASE)


def extract_signature(code: str):
    return code.strip().split('\n')[0].strip() if code.strip() else ""


class AutoDevAgent:

    def __init__(self, model: BaseModel):
        self.model = model
        self.bug_memory = BugMemory()

    def request_fix(
        self,
        error_info,
        code_context,
        language="python",
        caller_context=None,
        full_file_mode=False,
        full_file_content="",
        entry_file="",
        error_file="",
        entry_code="",
        fast_mode: bool = False,
        memory_hint: str = "",
    ):

        error_type = error_info.get("error_type", "")

        function_signature = extract_signature(code_context)

        # Language-aware cache lookup (only use for matching language)
        cached_fix = self.bug_memory.retrieve_fix(error_type, function_signature)
        if cached_fix:
            print(f"[RepairMemory] Cache hit for {error_type} / {function_signature[:40]}")
            return [cached_fix]

        # ---------- LANGUAGE SPECIFIC RULES ----------

        java_metadata_block = ""

        if language == "python":

            rules = """
Repair Rules (Python):
- Return ONLY valid source code.
- Do NOT include explanations.
- Do NOT include markdown fences (```python ... ```).
- Preserve the original programming language.
- Provide a single continuous code block.
- Keep the original structure intact.
"""

        elif language == "cpp":

            rules = """
Repair Rules (C++):
- Return ONLY valid source code.
- Do NOT include explanations.
- Do NOT include markdown fences (```cpp ... ```).
- Preserve the original programming language.
- The input program is written in C++.
- NEVER convert the program to Python.
- NEVER include 'def', 'import', or 'print('.
- Keep #include statements and the main() function.
- The output must compile with g++.

CRITICAL C++ RULES:
- If you see `int A = {{...}}` or `int B = {{...}}`, this is INVALID C++.
  Replace with `int A[2][2] = {{...}}` and `int B[2][2] = {{...}}`.
- NEVER convert plain arrays to vectors unless the entire function signature is also rewritten.
- Matrix multiply index must be C[i][j] += A[i][k] * B[k][j], not B[i][j].
"""

        elif language == "java":

            match = re.search(r"public\s+class\s+(\w+)", code_context)
            if match:
                class_name = match.group(1)
                file_name = os.path.basename(entry_file)
                print(f"Detected Java class name: {class_name}")

                java_metadata_block = f"""
Java File Metadata:
File name: {file_name}
Declared public class: {class_name}

Important Java rule:
The public class name must match the filename.
"""

            rules = """
Repair Rules (Java):
- Return ONLY valid Java source code.
- Do NOT include explanations, comments about changes, or markdown fences (```java ... ```).
- Preserve the original programming language (Java).
- NEVER convert the program to Python, C++, or any other language.
- Preserve the original package declaration (e.g. "package test_scripts;") exactly as-is.
- Preserve the original class name and class structure.
- Fix only the logical bug — do not rewrite unrelated methods.
- The output must compile with javac.

CRITICAL JAVA RULES:
- Do NOT include 'def ', 'import numpy', or any Python keywords.
- Do NOT add any new package declarations unless one already exists.
- Always initialize variables before use (NullPointerException is often caused by un-initialized fields).
- Keep all existing import statements.

If a mismatch exists between the file name and the public class name, fix it by either:

1. Renaming the class to match the file name
   OR
2. Adjusting the file reference accordingly.

Prefer modifying the class declaration instead of renaming files.
"""

        else:

            rules = """
Repair Rules:
- Preserve original functionality.
- Fix root cause.
- Return valid code in the same language.
"""

        # ---------- LANGUAGE GUARD ----------

        language_header = f"""
You are fixing a {language.upper()} program.

CRITICAL:
- Preserve the original language.
- Return ONLY valid {language.upper()} code.
- Do NOT convert the code to another language.
"""

        # ---------- TARGET BLOCK ----------

        # ---------- TARGET BLOCK ----------

        # In fast mode, request only 1 candidate to reduce output size and latency.
        if fast_mode:
            instruction = """
Return ONLY this JSON format:
{
"candidate_1": "FULL VALID SOURCE CODE"
}
Generate exactly 1 minimal fix for the bug.
Do not include explanations.
Do not include markdown.
Do not convert to another language.
"""
            print("[FastMode] Single-candidate prompt selected")

        elif full_file_mode:

            instruction = """
Return ONLY this JSON format:
{
"candidate_1": "FULL VALID SOURCE CODE",
"candidate_2": "FULL VALID SOURCE CODE",
"candidate_3": "FULL VALID SOURCE CODE"
}
Generate 3 different fixes for the bug. Return them separately.
Do not include explanations.
Do not include markdown.
Do not convert to another language.
"""

        else:

            instruction = """
Return ONLY JSON:
{
"candidate_1": "<first fix>",
"candidate_2": "<second fix>",
"candidate_3": "<third fix>"
}
Generate 3 different fixes for the bug. Return them separately.
"""

        caller_block = ""

        if caller_context:
            caller_block = f"\nCaller Function:\n{caller_context}"

        # ---------- ENHANCED CONTEXT ----------
        f_name = os.path.basename(error_file) if error_file else "unknown"
        b_line = error_info.get('line', 'unknown')
        e_type = error_info.get('error_type', 'Error')
        e_msg = error_info.get('error_message', 'unknown')
        f_sig = function_signature if function_signature else "unknown"

        context_code = full_file_content if full_file_mode else code_context

        context_block = f"File: {f_name}\nFunction: {f_sig}\nError: {e_type}: {e_msg}\nBug location: line {b_line}\n\nCode context:\n{context_code}"

        # ---------- MEMORY HINT ----------
        memory_hint_block = ""
        if memory_hint and memory_hint.strip():
            memory_hint_block = f"\n{memory_hint.strip()}\n"

        # ---------- PROMPT ----------

        prompt = strip_rich_tags(f"""
{language_header}
{java_metadata_block}
{instruction}

{rules}

You are fixing a bug in an existing program.

Important rules:
* Only modify the existing code.
* Do NOT create a new program.
* Do NOT add unrelated functions.
* Do NOT remove large sections of code.
* Do NOT rewrite the file.
* Only change the minimal number of lines needed to fix the bug.
* Preserve the structure of the original program.
{memory_hint_block}
{context_block}
{caller_block}
""")

        # ---------- MODEL CALL ----------

        _t_start = time.time()
        raw_outputs = []
        if hasattr(self.model, "generate_parallel"):
            raw_outputs = self.model.generate_parallel(prompt, language)
        else:
            raw_outputs = [self.model.generate_fix(prompt, language)]
        _t_elapsed = time.time() - _t_start
        print(f"[ModelCall] Completed in {_t_elapsed:.1f}s, raw outputs: {len(raw_outputs)}")

        valid_fixes = []

        for raw_output in raw_outputs:
            if not raw_output or not str(raw_output).strip():
                continue

            # Normalize raw model output to clean code candidates.
            # normalize() returns a NormalizedOutput dataclass — iterate .candidates, not the object.
            norm_result: NormalizedOutput = ResponseNormalizer.normalize(raw_output, language)
            candidates_list = norm_result.candidates  # List[str]

            print(
                f"[CloudPipeline] normalized candidates count: {len(candidates_list)} "
                f"(format={norm_result.source_format}, partial={norm_result.is_partial})"
            )

            for fixed_code in candidates_list:
                if not fixed_code or not str(fixed_code).strip():
                    continue
                fixed_code = str(fixed_code)

                # Apply lightweight completion (closes truncated braces, etc.)
                fixed_code = PatchCompleter.complete(fixed_code, language)

                # Strip any BOS artifacts from generated code
                fixed_code = _strip_bos_artifacts(fixed_code).strip()

                # ---------- LANGUAGE SAFETY CHECK ----------
                if language == "cpp":
                    if "def " in fixed_code or "import " in fixed_code:
                        continue  # Skip this invalid patch

                if fixed_code and fixed_code not in valid_fixes:
                    valid_fixes.append(fixed_code)

        if not valid_fixes:
            raise Exception("No valid patch candidates were generated.")

        print(f"[PatchMode] {len(valid_fixes)} valid fix candidate(s) ready")
        return valid_fixes

    def store_successful_fix(
        self,
        error_info: dict,
        file_path: str,
        code_context: str,
        fixed_code: str
    ):

        error_type = error_info.get("error_type", "")

        function_signature = code_context.strip().split("\n")[0] if code_context else ""

        file_hash = "unknown"

        if file_path and os.path.exists(file_path):
            with open(file_path, "rb") as f:
                file_hash = hashlib.md5(f.read()).hexdigest()

        self.bug_memory.store_fix(
            error_type=error_type,
            file_hash=file_hash,
            function_signature=function_signature,
            bug_code=code_context,
            fixed_code=fixed_code
        )