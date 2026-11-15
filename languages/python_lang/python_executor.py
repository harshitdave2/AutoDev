"""Python source executor with bounded runtime."""
import subprocess
import sys


class PythonExecutor:
    def __init__(self, timeout: float = 15.0):
        self.timeout = timeout

    def execute(self, file_path: str) -> dict:
        try:
            process = subprocess.run(
                [sys.executable, file_path],
                capture_output=True,
                text=True,
                timeout=self.timeout,
                check=False,
            )
            return {
                "stdout": process.stdout,
                "stderr": process.stderr,
                "returncode": process.returncode,
            }
        except subprocess.TimeoutExpired as exc:
            return {
                "stdout": exc.stdout or "",
                "stderr": (exc.stderr or "") + f"\nExecution timed out after {self.timeout:g}s.",
                "returncode": 124,
                "timed_out": True,
            }
        except OSError as exc:
            return {"stdout": "", "stderr": str(exc), "returncode": 127}
