import re
import json


def _extract_json_block(text: str) -> str:
    """
    Scan for the first complete balanced JSON object in text.
    Returns the JSON string or empty string if not found.
    This is safer than a greedy regex because it handles nested braces.
    """
    start = text.find('{')
    if start == -1:
        return ""

    depth = 0
    in_string = False
    escape_next = False

    for i, ch in enumerate(text[start:], start):
        if escape_next:
            escape_next = False
            continue
        if ch == '\\' and in_string:
            escape_next = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == '{':
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0:
                return text[start:i + 1]

    return ""


def _strip_bos_artifacts(text: str) -> str:
    """
    Remove all known BOS/EOS sentinel tokens and XML-like processing artifacts
    that LLMs (especially DeepSeek) sometimes inject into their output.
    """
    # DeepSeek BOS: clean form and garbled forms with ? replacing spaces/chars
    text = re.sub(r'<[?/]?begin[^>]*of[^>]*sentence[^>]*>', '', text, flags=re.IGNORECASE)
    # LLaMA-style pipe-delimited special tokens like <|begin_of_text|>
    text = re.sub(r'<\|[^|>]+\|>', '', text)
    # Generic XML processing instructions: <?...?>
    text = re.sub(r'<\?[^>]*\?>', '', text)
    # Generic single-word special tokens wrapped in angle brackets
    # that are NOT real HTML tags (no slash, no space, just token names)
    text = re.sub(r'<(s|/s|pad|bos|eos|unk|sep|cls|mask)>', '', text, flags=re.IGNORECASE)
    return text


def sanitize_llm_output(text: str) -> str:
    if not text:
        return ""

    original_text = text

    # Strip BOS/EOS sentinel artifacts first (before JSON parsing)
    text = _strip_bos_artifacts(text)

    # Step 1: Try to parse a well-formed JSON block
    json_str = _extract_json_block(text)

    if json_str:
        try:
            parsed_data = json.loads(json_str)

            if "fixed_code" in parsed_data:
                code = str(parsed_data["fixed_code"])

                # Decode escape sequences embedded in the JSON value
                code = code.replace("\\n", "\n").replace("\\t", "\t")

                # Strip markdown code fences that may be inside the value
                code = re.sub(r'```(?:\w+)?\n?', '', code, flags=re.IGNORECASE)
                code = code.replace('```', '')

                # Strip BOS artifacts again in case they were inside the JSON string
                code = _strip_bos_artifacts(code)

                code = code.strip()

                if code != original_text.strip():
                    print("Sanitized LLM output successfully.")

                return code
        except json.JSONDecodeError:
            pass

    # Step 2: Fallback - the JSON is malformed (e.g. unterminated string)
    # Try to pull out just the value after "fixed_code":
    fc_match = re.search(
        r'"fixed_code"\s*:\s*"(.*?)(?:"\s*\}?\s*$|$)',
        text,
        re.DOTALL,
    )
    if fc_match:
        code = fc_match.group(1)
        # Unescape sequences that the LLM may have written literally
        code = code.replace("\\n", "\n").replace("\\t", "\t")
        code = code.replace('\\"', '"').replace("\\'", "'")
        # Strip trailing JSON noise
        code = re.sub(r'"\s*\}?\s*$', '', code).strip()
    else:
        # Last resort: strip all JSON wrapper tokens and return whatever is left
        code = text
        code = re.sub(r'^\s*\{\s*\n?', '', code)
        code = re.sub(r'\n?\s*\}\s*$', '', code)
        code = re.sub(r'^\s*"fixed_code"\s*:\s*"?', '', code)
        code = re.sub(r'"?\s*$', '', code).strip()

    # Common cleanup regardless of path taken
    code = code.replace("\\n", "\n").replace("\\t", "\t")
    code = re.sub(r'```(?:\w+)?\n?', '', code, flags=re.IGNORECASE)
    code = code.replace('```', '')
    code = re.sub(r'</?code>', '', code)
    code = re.sub(r'</?pre>', '', code)

    # Strip all BOS/EOS artifact variants
    code = _strip_bos_artifacts(code)

    # Drop prose lines that slipped through
    clean_lines = [
        ln for ln in code.split("\n")
        if not ln.strip().startswith(("Here", "Explanation", "Sure"))
    ]
    code = "\n".join(clean_lines).strip()

    if code != original_text.strip():
        print("Sanitized LLM output successfully.")

    return code


def extract_json_from_text(raw_text: str) -> str:
    """
    Extract a JSON string with a 'fixed_code' or multi-candidate field from messy
    model output. Parses the JSON directly without running the whole raw text
    through sanitize_llm_output, so C++/Java code is never mangled by
    Python-specific cleanup.
    """
    if not raw_text:
        return json.dumps({"fixed_code": ""})

    # Strip BOS/EOS sentinel tokens that live outside the JSON block
    cleaned = _strip_bos_artifacts(raw_text)

    # Try to extract a balanced JSON object
    json_str = _extract_json_block(cleaned)
    if json_str:
        try:
            parsed = json.loads(json_str)
            # If the model returned a multi-candidate dict, pass it through as-is
            # (agent.py knows how to unpack candidate_1/2/3)
            if any(k.startswith("candidate_") for k in parsed):
                return json.dumps(parsed)
            # Single fixed_code path: minimal cleanup only
            if "fixed_code" in parsed:
                code = str(parsed["fixed_code"])
                code = code.replace("\\n", "\n").replace("\\t", "\t")
                code = re.sub(r'```(?:\w+)?\n?', '', code, flags=re.IGNORECASE).replace('```', '')
                code = _strip_bos_artifacts(code).strip()
                return json.dumps({"fixed_code": code})
            # Unknown JSON shape — return as-is and let the caller handle it
            return json_str
        except json.JSONDecodeError:
            pass

    # Fallback: try regex extraction of fixed_code value
    fc_match = re.search(
        r'"fixed_code"\s*:\s*"(.*?)(?:"\s*\}?\s*$|$)',
        cleaned,
        re.DOTALL,
    )
    if fc_match:
        code = fc_match.group(1)
        code = code.replace("\\n", "\n").replace("\\t", "\t")
        code = code.replace('\\"', '"').replace("\\'" , "'")
        code = re.sub(r'"\s*\}?\s*$', '', code).strip()
        return json.dumps({"fixed_code": code})

    # Last resort: return raw text wrapped in fixed_code with minimal fence stripping
    code = cleaned
    code = re.sub(r'```(?:\w+)?\n?', '', code, flags=re.IGNORECASE).replace('```', '')
    code = _strip_bos_artifacts(code).strip()
    return json.dumps({"fixed_code": code})


def clean_python_code(raw_code: str) -> str:
    """
    Clean AI-generated Python code and return executable code.
    """
    return sanitize_llm_output(raw_code)

def clean_code_by_language(code: str, language: str) -> str:
    if language == "python":
        return clean_python_code(code)
    else:
        # Ensure C++ sanitization does NOT remove braces, semiconductors etc
        code = code.replace("\\n", "\n").replace("\\t", "\t")
        import re
        code = re.sub(r'```(?:\w+)?\n?', '', code, flags=re.IGNORECASE).replace('```', '')
        # Drop prose lines
        clean_lines = [
            ln for ln in code.split("\n")
            if not ln.strip().startswith(("Here", "Explanation", "Sure"))
        ]
        return "\n".join(clean_lines).strip()