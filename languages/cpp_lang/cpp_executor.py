import subprocess
import os
from .cpp_parser import parse_cpp_error


class CppExecutor:

    def execute(self, file_path: str):

        binary = file_path.replace(".cpp", ".exe")

        compile_process = subprocess.run(
            ["g++", file_path, "-std=c++17", "-O2", "-o", binary],
            capture_output=True,
            text=True
        )

        if compile_process.returncode != 0:

            error = parse_cpp_error(compile_process.stderr)

            return {
                "returncode": 1,
                "stdout": "",
                "stderr": compile_process.stderr,
                "traceback": error
            }

        run_process = subprocess.run(
            [binary],
            capture_output=True,
            text=True
        )

        return {
            "returncode": run_process.returncode,
            "stdout": run_process.stdout,
            "stderr": run_process.stderr
        }