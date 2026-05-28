import subprocess
import os
import re
import tempfile


def _parse_package(source: str) -> str:
    """Extract the package name from Java source, e.g. 'test_scripts'."""
    match = re.search(r'^\s*package\s+([\w.]+)\s*;', source, re.MULTILINE)
    return match.group(1) if match else ""


def _parse_class_name(source: str) -> str:
    """
    Extract the public class name from Java source.
    Falls back to the first class name found if no public class is declared.
    """
    # Try to find 'public class Foo'
    match = re.search(r'\bpublic\s+class\s+(\w+)', source)
    if match:
        return match.group(1)
    # Fallback: any class declaration
    match = re.search(r'\bclass\s+(\w+)', source)
    if match:
        return match.group(1)
    return ""


class JavaExecutor:

    def execute(self, file_path: str) -> dict:
        file_path = os.path.abspath(file_path)

        # Read the source once to inspect package & class name
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                source = f.read()
        except Exception as e:
            return {"returncode": 1, "stdout": "", "stderr": str(e)}

        package_name = _parse_package(source)
        class_name = _parse_class_name(source)

        if not class_name:
            # Last resort: use the file's base name (may be wrong case, but we try)
            class_name = os.path.splitext(os.path.basename(file_path))[0]

        # Build fully-qualified class name for the `java` invocation
        if package_name:
            fq_class = f"{package_name}.{class_name}"
        else:
            fq_class = class_name

        # Determine the classpath root.
        # If the file has a package (e.g. test_scripts.DataProcessor) the .class
        # files must be placed at a root that is *above* the package directory so
        # that `java test_scripts.DataProcessor` can find them.
        if package_name:
            # Walk up one directory per package component
            depth = len(package_name.split("."))
            classpath_root = file_path
            for _ in range(depth + 1):          # +1 to get above the package dir
                classpath_root = os.path.dirname(classpath_root)
        else:
            classpath_root = os.path.dirname(file_path)

        # Ensure the classpath root exists (edge-case: file is in root dir)
        if not classpath_root:
            classpath_root = "."

        # ── Compile ──────────────────────────────────────────────────────────
        compile_result = subprocess.run(
            ["javac", "-d", classpath_root, file_path],
            capture_output=True,
            text=True,
            cwd=classpath_root,
        )

        if compile_result.returncode != 0:
            return {
                "returncode": 1,
                "stdout": "",
                "stderr": compile_result.stderr,
            }

        # ── Run ──────────────────────────────────────────────────────────────
        run_result = subprocess.run(
            ["java", "-cp", classpath_root, fq_class],
            capture_output=True,
            text=True,
            cwd=classpath_root,
        )

        return {
            "returncode": run_result.returncode,
            "stdout": run_result.stdout,
            "stderr": run_result.stderr,
        }