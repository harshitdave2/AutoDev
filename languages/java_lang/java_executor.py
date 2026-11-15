"""Java compile-and-run executor."""
import os
import re
import subprocess
import tempfile


def _parse_package(source: str) -> str:
    match = re.search(r'^\s*package\s+([\w.]+)\s*;', source, re.MULTILINE)
    return match.group(1) if match else ""


def _parse_class_name(source: str) -> str:
    match = re.search(r'\bpublic\s+(?:final\s+|abstract\s+)?class\s+(\w+)', source)
    if match:
        return match.group(1)
    match = re.search(r'\bclass\s+(\w+)', source)
    return match.group(1) if match else ""


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
                    ["javac", "-d", classpath_root, source_path],
                    capture_output=True, text=True, timeout=self.compile_timeout, check=False,
                )
            except FileNotFoundError:
                return {"returncode": 127, "stdout": "", "stderr": "javac was not found. Install a JDK and ensure javac/java are on PATH."}
            except subprocess.TimeoutExpired:
                return {"returncode": 124, "stdout": "", "stderr": f"Java compilation timed out after {self.compile_timeout:g}s.", "timed_out": True}

            if compile_result.returncode:
                return {"returncode": compile_result.returncode, "stdout": "", "stderr": compile_result.stderr}

            try:
                run_result = subprocess.run(
                    ["java", "-cp", classpath_root, fq_class],
                    capture_output=True, text=True, timeout=self.run_timeout, check=False,
                )
                return {
                    "returncode": run_result.returncode,
                    "stdout": run_result.stdout,
                    "stderr": run_result.stderr,
                }
            except subprocess.TimeoutExpired as exc:
                return {
                    "returncode": 124,
                    "stdout": exc.stdout or "",
                    "stderr": (exc.stderr or "") + f"\nJava program timed out after {self.run_timeout:g}s.",
                    "timed_out": True,
                }
