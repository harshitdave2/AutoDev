import re
import ast
import os
from languages.cpp_lang.cpp_parser import parse_cpp_error


def parse_traceback(stderr: str) -> dict:

    cpp_error = parse_cpp_error(stderr)

    if cpp_error:
        return cpp_error

    result = {
        "file": "",
        "line": 0,
        "error_type": "",
        "error_message": ""
    }

    if not stderr or not stderr.strip():
        return result

    file_pattern = r'File\s+"([^"]+)",\s+line\s+(\d+)'
    file_matches = re.findall(file_pattern, stderr)

    if file_matches:
        last_match = file_matches[-1]
        result["file"] = last_match[0]
        result["line"] = int(last_match[1])

    lines = [line.strip() for line in stderr.splitlines() if line.strip()]
    if lines:
        last_line = lines[-1]
        error_pattern = r'^([A-Za-z0-9_.]+)(?::\s*(.*))?$'
        error_match = re.match(error_pattern, last_line)

        if error_match:
            result["error_type"] = error_match.group(1).strip()
            result["error_message"] = error_match.group(2).strip() if error_match.group(2) else ""
        else:
            result["error_type"] = "UnknownError"
            result["error_message"] = last_line

    return result


def extract_function_context(file_path: str, line_number: int) -> str:
    if not os.path.exists(file_path):
        return ""

    with open(file_path, "r", encoding="utf-8") as f:
        source_code = f.read()

    source_lines = source_code.splitlines()

    try:
        tree = ast.parse(source_code, filename=file_path)
    except SyntaxError:
        tree = None

    best_node = None
    min_size = float('inf')

    if tree:
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                if hasattr(node, "lineno") and hasattr(node, "end_lineno"):
                    if node.lineno <= line_number <= node.end_lineno:
                        size = node.end_lineno - node.lineno
                        if size < min_size:
                            min_size = size
                            best_node = node

    if best_node:
        start_idx = best_node.lineno - 1
        end_idx = best_node.end_lineno
        return "\n".join(source_lines[start_idx:end_idx])
    else:
        start_idx = max(0, line_number - 1 - 5)
        end_idx = min(len(source_lines), line_number + 5)
        return "\n".join(source_lines[start_idx:end_idx])


def extract_additional_context(file_path: str, stderr: str) -> dict:
    """
    Parses the full stack trace to find the exact broken function and its caller.
    """
    result = {
        "primary_function": "",
        "caller_function": None
    }

    # Regex to capture file, line, and function name from the stack trace
    pattern = r'File\s+"([^"]+)",\s+line\s+(\d+),\s+in\s+(\w+|<module>)'
    matches = re.findall(pattern, stderr)

    if not matches:
        return result

    # The last match in the stack trace is where the crash actually happened
    primary_match = matches[-1]
    result["primary_function"] = extract_function_context(primary_match[0], int(primary_match[1]))

    # The second-to-last match is the function that CALLED the broken function
    if len(matches) >= 2:
        caller_match = matches[-2]
        # Ignore module-level calls (meaning it was called directly in the script body)
        if caller_match[2] != '<module>':
            result["caller_function"] = extract_function_context(caller_match[0], int(caller_match[1]))

    return result