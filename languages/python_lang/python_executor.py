"""Python source executor with bounded runtime."""
import subprocess
import sys

from languages.process_utils import RUN_KWARGS, timeout_result


class PythonExecutor:
    def __init__(self, timeout: float = 15.0):
        self.timeout = timeout

    def execute(self, file_path: str) -> dict:
        try:
            process = subprocess.run(
                [sys.executable, file_path],
                timeout=self.timeout,
                **RUN_KWARGS,
            )
            return {
                "stdout": process.stdout,
                "stderr": process.stderr,
                "returncode": process.returncode,
            }
        except subprocess.TimeoutExpired as exc:
            return timeout_result(exc, f"Execution timed out after {self.timeout:g}s.")
        except OSError as exc:
            return {"stdout": "", "stderr": str(exc), "returncode": 127}
