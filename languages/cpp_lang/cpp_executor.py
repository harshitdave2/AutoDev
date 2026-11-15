"""C++ compile-and-run executor."""
import os
import subprocess
import tempfile

from .cpp_parser import parse_cpp_error


class CppExecutor:
    def __init__(self, compile_timeout: float = 30.0, run_timeout: float = 15.0):
        self.compile_timeout = compile_timeout
        self.run_timeout = run_timeout

    def execute(self, file_path: str) -> dict:
        source = os.path.abspath(file_path)
        if not os.path.isfile(source):
            return {"returncode": 1, "stdout": "", "stderr": f"Source file not found: {source}"}

        # Keep generated binaries out of the source tree and avoid replacing
        # a user's existing .exe/.out file.
        with tempfile.TemporaryDirectory(prefix="autodev-cpp-") as temp_dir:
            binary = os.path.join(temp_dir, "program.exe" if os.name == "nt" else "program")
            try:
                compile_process = subprocess.run(
                    ["g++", source, "-std=c++17", "-O2", "-o", binary],
                    capture_output=True, text=True, timeout=self.compile_timeout, check=False,
                )
            except FileNotFoundError:
                return {"returncode": 127, "stdout": "", "stderr": "g++ was not found. Install a C++ compiler and ensure it is on PATH."}
            except subprocess.TimeoutExpired:
                return {"returncode": 124, "stdout": "", "stderr": f"C++ compilation timed out after {self.compile_timeout:g}s.", "timed_out": True}

            if compile_process.returncode:
                return {
                    "returncode": compile_process.returncode,
                    "stdout": "",
                    "stderr": compile_process.stderr,
                    "traceback": parse_cpp_error(compile_process.stderr),
                }

            try:
                run_process = subprocess.run(
                    [binary], capture_output=True, text=True,
                    timeout=self.run_timeout, check=False,
                )
                return {
                    "returncode": run_process.returncode,
                    "stdout": run_process.stdout,
                    "stderr": run_process.stderr,
                }
            except subprocess.TimeoutExpired as exc:
                return {
                    "returncode": 124,
                    "stdout": exc.stdout or "",
                    "stderr": (exc.stderr or "") + f"\nC++ program timed out after {self.run_timeout:g}s.",
                    "timed_out": True,
                }
