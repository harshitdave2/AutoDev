import subprocess
import sys

class PythonExecutor:

    def execute(self, file_path):

        process = subprocess.run(
            [sys.executable, file_path],
            capture_output=True,
            text=True
        )

        return {
            "stdout": process.stdout,
            "stderr": process.stderr,
            "returncode": process.returncode
        }