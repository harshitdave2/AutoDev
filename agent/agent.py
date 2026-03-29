import os
import sys
import hashlib
import re

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from models.base_model import BaseModel
from core.bug_memory import BugMemory
from core.sanitizer import sanitize_llm_output


def strip_rich_tags(text: str):
    return re.sub(r"\[/?[a-zA-Z0-9#]+\]", "", text)


def extract_signature(code: str):
    match = re.search(r"(def\s+\w+\(.*?\))", code)
    return match.group(1) if match else ""


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
        full_file_content=""
    ):

        error_type = error_info.get("error_type", "")

        function_signature = extract_signature(code_context)

        cached_fix = self.bug_memory.retrieve_fix(error_type, function_signature)

        if cached_fix:
            return [cached_fix]

        # ---------- LANGUAGE SPECIFIC RULES ----------

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

        if full_file_mode:

            instruction = """
Return ONLY this JSON format:

{
"fixed_code": "FULL VALID C++ SOURCE CODE"
}

Do not include explanations.
Do not include markdown.
Do not convert to another language.
"""

            target_block = f"Full File Content:\n{full_file_content}"

        else:

            instruction = """
Return ONLY JSON:
{ "fixed_code": "<corrected code>" }
"""

            target_block = f"Broken Code:\n{code_context}"

        caller_block = ""

        if caller_context:
            caller_block = f"\nCaller Function:\n{caller_context}"

        # ---------- PROMPT ----------

        prompt = strip_rich_tags(f"""
{language_header}

{instruction}

{rules}

Error Type: {error_info.get('error_type')}
Error Message: {error_info.get('error_message')}

{caller_block}

{target_block}
""")

        # ---------- MODEL CALL ----------

        raw_outputs = []
        if hasattr(self.model, "generate_parallel"):
            raw_outputs = self.model.generate_parallel(prompt)
        else:
            raw_outputs = [self.model.generate_fix(prompt)]

        valid_fixes = []
        for raw_output in raw_outputs:
            fixed_code = sanitize_llm_output(raw_output)
            fixed_code = strip_rich_tags(fixed_code)
            fixed_code = fixed_code.replace("\\n", "\n").replace("\\t", "\t")

            # ---------- LANGUAGE SAFETY CHECK ----------

            if language == "cpp":

                if "def " in fixed_code or "import " in fixed_code:
                    continue  # Skip this invalid patch
            
            if fixed_code and fixed_code not in valid_fixes:
                valid_fixes.append(fixed_code)

        if not valid_fixes:
            raise Exception("No valid patch candidates were generated.")

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