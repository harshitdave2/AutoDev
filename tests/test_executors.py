import os
import subprocess
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from languages.python_lang.python_executor import PythonExecutor
from languages.cpp_lang.cpp_executor import CppExecutor
from languages.java_lang.java_executor import JavaExecutor


class PythonExecutorTests(unittest.TestCase):
    def test_executes_python_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source = os.path.join(temp_dir, "hello.py")
            with open(source, "w", encoding="utf-8") as stream:
                stream.write("print('hello')\n")
            result = PythonExecutor().execute(source)
        self.assertEqual(result["returncode"], 0)
        self.assertEqual(result["stdout"].strip(), "hello")

    def test_timeout_is_reported(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source = os.path.join(temp_dir, "loop.py")
            with open(source, "w", encoding="utf-8") as stream:
                stream.write("while True: pass\n")
            result = PythonExecutor(timeout=0.1).execute(source)
        self.assertEqual(result["returncode"], 124)
        self.assertTrue(result["timed_out"])


class CppExecutorTests(unittest.TestCase):
    @patch("languages.cpp_lang.cpp_executor.subprocess.run")
    def test_uses_temporary_binary_and_preserves_source(self, run):
        run.side_effect = [
            SimpleNamespace(returncode=0, stdout="", stderr=""),
            SimpleNamespace(returncode=0, stdout="ok\n", stderr=""),
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            source = os.path.join(temp_dir, "main.cpp")
            with open(source, "w", encoding="utf-8") as stream:
                stream.write("int main() { return 0; }")
            result = CppExecutor().execute(source)
            self.assertTrue(os.path.isfile(source))
            compile_args = run.call_args_list[0].args[0]
            binary_path = compile_args[-1]
            self.assertTrue(os.path.dirname(binary_path).startswith(tempfile.gettempdir()))
            self.assertNotEqual(os.path.dirname(binary_path), temp_dir)
        self.assertEqual(result["returncode"], 0)
        self.assertEqual(result["stdout"], "ok\n")

    @patch("languages.cpp_lang.cpp_executor.subprocess.run", side_effect=subprocess.TimeoutExpired("g++", 1))
    def test_compile_timeout_is_reported(self, _run):
        with tempfile.TemporaryDirectory() as temp_dir:
            source = os.path.join(temp_dir, "main.cpp")
            with open(source, "w", encoding="utf-8") as stream:
                stream.write("int main() { return 0; }")
            result = CppExecutor(compile_timeout=1).execute(source)
        self.assertEqual(result["returncode"], 124)
        self.assertTrue(result["timed_out"])


class JavaExecutorTests(unittest.TestCase):
    @patch("languages.java_lang.java_executor.subprocess.run")
    def test_compiles_and_runs_without_polluting_source_directory(self, run):
        run.side_effect = [
            SimpleNamespace(returncode=0, stdout="", stderr=""),
            SimpleNamespace(returncode=0, stdout="hello\n", stderr=""),
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            source = os.path.join(temp_dir, "Hello.java")
            with open(source, "w", encoding="utf-8") as stream:
                stream.write("public class Hello { public static void main(String[] args) { System.out.println(\"hello\"); } }")
            result = JavaExecutor().execute(source)
            self.assertEqual(os.listdir(temp_dir), ["Hello.java"])
            classpath = run.call_args_list[1].args[0][2]
            self.assertNotEqual(classpath, temp_dir)
        self.assertEqual(result["returncode"], 0)
        self.assertEqual(result["stdout"], "hello\n")

    def test_missing_class_is_reported(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source = os.path.join(temp_dir, "Broken.java")
            with open(source, "w", encoding="utf-8") as stream:
                stream.write("int value = 1;")
            result = JavaExecutor().execute(source)
        self.assertEqual(result["returncode"], 1)
        self.assertIn("class declaration", result["stderr"])


if __name__ == "__main__":
    unittest.main()
