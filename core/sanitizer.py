import json
import re


def sanitize_llm_output(text: str) -> str:

    if not text:
        return ""

    # remove markdown
    text = re.sub(r"```.*?```", "", text, flags=re.DOTALL)

    # remove html/code artifacts
    text = re.sub(r"</?code>", "", text)
    text = re.sub(r"</?pre>", "", text)

    # remove weird tokens
    text = text.replace("<beginofsentence>", "")

    # remove explanations before code
    lines = text.split("\n")

    clean_lines = []

    for line in lines:

        if line.strip().startswith(("Here", "Explanation", "Sure")):
            continue

        clean_lines.append(line)

    text = "\n".join(clean_lines)

    return text.strip()


def extract_json_from_text(raw_text: str) -> str:
    """
    Extract a safe JSON string with a 'fixed_code' field from messy model output.
    """
    code = sanitize_llm_output(raw_text)
    return json.dumps({"fixed_code": code})


def clean_python_code(raw_code: str) -> str:
    """
    Clean AI-generated Python code and return executable code.
    """
    return sanitize_llm_output(raw_code)