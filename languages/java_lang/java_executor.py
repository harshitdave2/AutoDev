import subprocess
import os

class JavaExecutor:

    def execute(self, file_path):

        classname = os.path.splitext(os.path.basename(file_path))[0]

        compile_process = subprocess.run(
            ["javac", file_path],
            capture_output=True,
            text=True
        )

        if compile_process.returncode != 0:
            return {
                "returncode": 1,
                "stdout": "",
                "stderr": compile_process.stderr
            }

        run_process = subprocess.run(
            ["java", classname],
            capture_output=True,
            text=True
        )

        return {
            "returncode": run_process.returncode,
            "stdout": run_process.stdout,
            "stderr": run_process.stderr
        }