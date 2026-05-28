import re


def parse_java_error(stderr: str) -> dict:
    """
    Parses Java output to extract error file, line, and message.

    Handles two cases:
    1. Compiler errors (javac):
       e.g.  DataProcessor.java:8: error: cannot find symbol
    2. Runtime exceptions (java):
       e.g.  Exception in thread "main" java.lang.NullPointerException
             at test_scripts.DataProcessor.process(DataProcessor.java:8)
    """

    if not stderr:
        return {}

    # ── Case 1: Compiler error ────────────────────────────────────────────────
    # javac writes lines like:  path/to/File.java:17: error: some message
    compile_pattern = r'([^\s:]+\.java):(\d+): error: (.+)'
    compile_match = re.search(compile_pattern, stderr)
    if compile_match:
        return {
            "file": compile_match.group(1),
            "line": int(compile_match.group(2)),
            "error_type": "JavaCompileError",
            "error_message": compile_match.group(3).strip(),
        }

    # ── Case 2: Runtime exception ─────────────────────────────────────────────
    # Stack trace lines look like:
    #   Exception in thread "main" java.lang.NullPointerException
    #   at com.example.Foo.bar(Foo.java:42)
    #
    # We want the DEEPEST frame (the last "at" line in the trace) and
    # the exception type from the first line.

    # Extract exception type from "Exception in thread ... ExceptionType: msg"
    exc_match = re.search(
        r'Exception in thread "[^"]*"\s+([\w.]+(?:Exception|Error))\s*:?\s*(.*)',
        stderr
    )
    if not exc_match:
        # Broader fallback: just look for any Exception/Error line
        exc_match = re.search(r'([\w.]+(?:Exception|Error))\s*:?\s*(.*)', stderr)

    error_type = exc_match.group(1).rsplit('.', 1)[-1] if exc_match else "JavaRuntimeError"
    error_message = exc_match.group(2).strip() if exc_match else ""

    # Find all "at ..." stack frames
    at_pattern = r'at\s+[\w.$]+\((\w+\.java):(\d+)\)'
    at_matches = re.findall(at_pattern, stderr)

    if at_matches:
        # Use the FIRST (deepest user-visible) frame
        file_name, line_no = at_matches[0]
        return {
            "file": file_name,
            "line": int(line_no),
            "error_type": error_type,
            "error_message": error_message or error_type,
        }

    # ── Case 3: ClassNotFoundException (wrong class name / classpath) ─────────
    cnf_match = re.search(r'ClassNotFoundException:\s*(\S+)', stderr)
    if cnf_match:
        return {
            "file": "",
            "line": 0,
            "error_type": "ClassNotFoundException",
            "error_message": f"Could not find class: {cnf_match.group(1)}",
        }

    return {}