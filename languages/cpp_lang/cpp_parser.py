import re

def parse_cpp_error(stderr: str):

    pattern = r"(.+\.cpp):(\d+):(\d+): error: (.+)"

    match = re.search(pattern, stderr)

    if not match:
        return {}

    return {
        "file": match.group(1),
        "line": int(match.group(2)),
        "column": int(match.group(3)),
        "error_type": "CppCompileError",
        "error_message": match.group(4)
    }