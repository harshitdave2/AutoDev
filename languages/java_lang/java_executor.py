"""Java compile-and-run executor."""
import os
import re
import subprocess
import tempfile

from languages.process_utils import RUN_KWARGS, timeout_result


def _parse_package(source: str) -> str:
    match = re.search(r'^\s*package\s+([\w.]+)\s*;', source, re.MULTILINE)
    return match.group(1) if match else ""


_STRIP_PATTERN = re.compile(
    r'''"""[\s\S]*?"""|"(?:\\.|[^"\\\n])*"|\'(?:\\.|[^\'\\\n])*\'|//[^\n]*|/\*[\s\S]*?\*/''',
)


def _strip_comments_and_strings(source: str) -> str:
    """Blank out comments and string/char literals, keeping offsets and newlines."""
    return _STRIP_PATTERN.sub(lambda m: re.sub(r"[^\n]", " ", m.group(0)), source)


def _parse_class_name(source: str) -> str:
    """Pick the top-level class to run.

    Preference order: the top-level class that declares ``main``, then the
    public top-level class, then the first top-level class. Comments and string
    literals are ignored so text such as ``// public class Old`` is not matched.
    """
    code = _strip_comments_and_strings(source)
    decl = re.compile(r"\b(?:class|interface|enum|record)\s+(\w+)")
    top_level = []  # (name, start, end, is_public)
    depth = 0
    pos = 0
    open_decl = None
    for match in decl.finditer(code):
        depth += code.count("{", pos, match.start()) - code.count("}", pos, match.start())
        pos = match.start()
        if depth != 0:
            continue
        prefix = code[max(0, match.start() - 40):match.start()]
        # Skip things like `Foo.class` or generic `Class<...>` usages.
        if prefix.rstrip().endswith("."):
            continue
        brace = code.find("{", match.end())
        if brace == -1:
            continue
        level, i = 0, brace
        while i < len(code):
            if code[i] == "{":
                level += 1
            elif code[i] == "}":
                level -= 1
                if level == 0:
                    break
            i += 1
        is_public = bool(re.search(r"\bpublic\b[^;{}]*$", prefix))
        top_level.append((match.group(1), brace, i, is_public))

    if not top_level:
        return ""
    main_re = re.compile(r"\bstatic\b[^;{}()]*\bvoid\s+main\s*\(")
    for name, begin, finish, _public in top_level:
        if main_re.search(code, begin, finish):
            return name
    for name, _b, _f, is_public in top_level:
        if is_public:
            return name
    return top_level[0][0]


class JavaExecutor:
    def __init__(self, compile_timeout: float = 30.0, run_timeout: float = 15.0):
        self.compile_timeout = compile_timeout
        self.run_timeout = run_timeout

    def execute(self, file_path: str) -> dict:
        source_path = os.path.abspath(file_path)
        if not os.path.isfile(source_path):
            return {"returncode": 1, "stdout": "", "stderr": f"Source file not found: {source_path}"}
        try:
            with open(source_path, "r", encoding="utf-8") as stream:
                source = stream.read()
        except (OSError, UnicodeError) as exc:
            return {"returncode": 1, "stdout": "", "stderr": str(exc)}

        class_name = _parse_class_name(source)
        if not class_name:
            return {"returncode": 1, "stdout": "", "stderr": "Could not identify a Java class declaration."}
        package_name = _parse_package(source)
        fq_class = f"{package_name}.{class_name}" if package_name else class_name

        # Compile into an isolated temporary output directory. javac can infer
        # the package directory from the source; no .class files pollute projects.
        with tempfile.TemporaryDirectory(prefix="autodev-java-") as classpath_root:
            try:
                compile_result = subprocess.run(
                    ["javac", "-encoding", "UTF-8", "-d", classpath_root, source_path],
                    timeout=self.compile_timeout, **RUN_KWARGS,
                )
            except FileNotFoundError:
                return {"returncode": 127, "stdout": "", "stderr": "javac was not found. Install a JDK and ensure javac/java are on PATH."}
            except OSError as exc:
                return {"returncode": 127, "stdout": "", "stderr": f"Could not start javac: {exc}"}
            except subprocess.TimeoutExpired:
                return {"returncode": 124, "stdout": "", "stderr": f"Java compilation timed out after {self.compile_timeout:g}s.", "timed_out": True}

            if compile_result.returncode:
                return {"returncode": compile_result.returncode, "stdout": "", "stderr": compile_result.stderr}

            try:
                run_result = subprocess.run(
                    ["java", "-cp", classpath_root, fq_class],
                    timeout=self.run_timeout, **RUN_KWARGS,
                )
                return {
                    "returncode": run_result.returncode,
                    "stdout": run_result.stdout,
                    "stderr": run_result.stderr,
                }
            except subprocess.TimeoutExpired as exc:
                return timeout_result(exc, f"Java program timed out after {self.run_timeout:g}s.")
            except FileNotFoundError:
                return {"returncode": 127, "stdout": "", "stderr": "java was not found. Install a JDK/JRE and ensure java is on PATH."}
            except OSError as exc:
                return {"returncode": 126, "stdout": "", "stderr": f"Could not run java: {exc}"}
