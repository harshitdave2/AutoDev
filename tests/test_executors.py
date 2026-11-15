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


class ExecutorRobustnessTests(unittest.TestCase):
    """Regressions for crashes found during the audit."""

    def _write(self, directory, name, text):
        path = os.path.join(directory, name)
        with open(path, "w", encoding="utf-8") as stream:
            stream.write(text)
        return path

    def test_timeout_after_partial_output_does_not_crash(self):
        # TimeoutExpired.stdout/stderr are bytes; this used to raise
        # "TypeError: can't concat str to bytes".
        with tempfile.TemporaryDirectory() as temp_dir:
            source = self._write(temp_dir, "noisy.py",
                "import sys, time\n"
                "print('partial out', flush=True)\n"
                "print('partial err', file=sys.stderr, flush=True)\n"
                "time.sleep(30)\n")
            result = PythonExecutor(timeout=1).execute(source)
        self.assertTrue(result["timed_out"])
        self.assertIsInstance(result["stdout"], str)
        self.assertIsInstance(result["stderr"], str)
        self.assertIn("partial out", result["stdout"])
        self.assertIn("partial err", result["stderr"])
        self.assertIn("timed out", result["stderr"])

    def test_invalid_utf8_output_does_not_crash(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source = self._write(temp_dir, "bad.py",
                "import sys\nsys.stdout.buffer.write(b'ok \\xff done\\n')\n")
            result = PythonExecutor().execute(source)
        self.assertEqual(result["returncode"], 0)
        self.assertIn("ok", result["stdout"])

    def test_input_fails_fast_instead_of_blocking_on_terminal(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source = self._write(temp_dir, "ask.py", "input('name? ')\n")
            result = PythonExecutor(timeout=10).execute(source)
        self.assertNotEqual(result["returncode"], 0)
        self.assertIn("EOFError", result["stderr"])
        self.assertFalse(result.get("timed_out"))


class JavaClassSelectionTests(unittest.TestCase):
    def test_prefers_class_with_main_over_earlier_helper(self):
        from languages.java_lang.java_executor import _parse_class_name
        src = "class Helper {}\npublic class Main { public static void main(String[] a) {} }"
        self.assertEqual(_parse_class_name(src), "Main")

    def test_ignores_comments_and_strings(self):
        from languages.java_lang.java_executor import _parse_class_name
        src = ('// public class Old {}\n/* class Older {} */\n'
               'public class Real { public static void main(String[] a) { String s = "class Fake"; } }')
        self.assertEqual(_parse_class_name(src), "Real")

    def test_nested_class_is_not_selected(self):
        from languages.java_lang.java_executor import _parse_class_name
        src = "public class Outer { static class Inner {} public static void main(String[] a) {} }"
        self.assertEqual(_parse_class_name(src), "Outer")

    def test_non_public_main_class_after_helper(self):
        from languages.java_lang.java_executor import _parse_class_name
        src = "class A {}\nclass B { public static void main(String[] x) {} }"
        self.assertEqual(_parse_class_name(src), "B")

    def test_no_class_returns_empty(self):
        from languages.java_lang.java_executor import _parse_class_name
        self.assertEqual(_parse_class_name("int x = 1;"), "")


class LanguageRoutingTests(unittest.TestCase):
    def test_unsupported_language_is_a_value_error(self):
        from languages.language_router import LanguageRouter, UnsupportedLanguageError
        for name in ("script.js", "notes.txt", "noextension"):
            with self.assertRaises(UnsupportedLanguageError) as ctx:
                LanguageRouter.route(name)
            self.assertIsInstance(ctx.exception, ValueError)

    def test_extension_detection_is_case_insensitive_and_exact(self):
        from languages.language_detector import LanguageDetector
        self.assertEqual(LanguageDetector.detect("A.PY", quiet=True), "python")
        self.assertEqual(LanguageDetector.detect("a.CPP", quiet=True), "cpp")
        self.assertEqual(LanguageDetector.detect("a.py.backup", quiet=True), "unknown")
        self.assertFalse(LanguageDetector.is_supported("a.js"))
        self.assertTrue(LanguageDetector.is_supported("Main.java"))

    def test_quiet_detection_prints_nothing(self):
        import io
        from contextlib import redirect_stdout
        from languages.language_detector import LanguageDetector
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            LanguageDetector.detect("x.py", quiet=True)
        self.assertEqual(buffer.getvalue(), "")


if __name__ == "__main__":
    unittest.main()
