import io
import os
import pathlib
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

import autodev
from autodev import describe_confidence, positive_int


class ConfidenceLabelTests(unittest.TestCase):
    def test_clean_first_run_is_unverified_not_no_repair_needed(self):
        label = describe_confidence({"status": "SUCCESS", "attempts_used": 0, "confidence": "UNVERIFIED"})
        self.assertTrue(label.startswith("UNVERIFIED"))

    def test_heuristic_patch_with_zero_model_attempts_is_not_called_no_repair(self):
        label = describe_confidence({"status": "SUCCESS", "attempts_used": 0,
                                     "old_code": "a/b", "new_code": "a/b if b else 0"})
        self.assertTrue(label.startswith("HEURISTIC"))

    def test_no_patch_no_attempts_is_na(self):
        self.assertTrue(describe_confidence({"status": "SUCCESS", "attempts_used": 0}).startswith("N/A"))

    def test_percentage_grades(self):
        self.assertEqual(describe_confidence({"confidence": "95%"}), "95% (A)")
        self.assertEqual(describe_confidence({"confidence": "50%"}), "50% (D)")
        self.assertEqual(describe_confidence({"confidence": "5%"}), "5% (F)")
        self.assertEqual(describe_confidence({"confidence": "nan%"}), "nan%")
        self.assertEqual(describe_confidence({"confidence": "abc%"}), "abc%")

    def test_expected_output_confidence_is_verified(self):
        label = describe_confidence({"status": "SUCCESS", "attempts_used": 0, "confidence": "VERIFIED"})
        self.assertEqual(label, "VERIFIED (stdout matched explicit expected-output oracle)")

    def test_failed_run_has_no_confidence(self):
        self.assertEqual(describe_confidence({"status": "FAILED", "attempts_used": 3}), "Not established")


class ArgumentTests(unittest.TestCase):
    def test_positive_int(self):
        self.assertEqual(positive_int("3"), 3)
        for bad in ("0", "-1", "x", "1.5"):
            with self.assertRaises(Exception):
                positive_int(bad)


class MainTests(unittest.TestCase):
    def _run(self, argv):
        out = io.StringIO()
        with patch("sys.argv", ["autodev.py"] + argv), redirect_stdout(out):
            code = autodev.main()
        return code, out.getvalue()

    def test_missing_file_exits_2(self):
        code, _ = self._run(["run", "/definitely/not/here.py"])
        self.assertEqual(code, 2)

    def test_unsupported_extension_exits_2_without_traceback(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "script.js")
            pathlib.Path(path).write_text("console.log(1)")
            code, out = self._run(["run", path])
        self.assertEqual(code, 2)
        self.assertIn("unsupported", out.lower())
        self.assertNotIn("Traceback", out)

    def test_diff_with_rich_markup_text_does_not_crash(self):
        fake = {"status": "SUCCESS", "attempts_used": 1, "confidence": "HIGH", "model": "m[/x]",
                "old_code": 'print("[/x]")\n', "new_code": 'print("[/x] [red]")\n'}
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "a.py")
            pathlib.Path(path).write_text("print(1)")
            with patch("models.model_loader.load_model", return_value=object()), \
                 patch.object(autodev.RetryManager, "__init__", return_value=None), \
                 patch.object(autodev.RetryManager, "attempt_fix", return_value=fake):
                code, out = self._run(["run", path])
        self.assertEqual(code, 0)
        self.assertIn("[/x]", out)  # shown literally, not parsed as markup

    def test_unexpected_error_is_reported_with_exit_1(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "a.py")
            pathlib.Path(path).write_text("print(1)")
            with patch("models.model_loader.load_model", return_value=object()), \
                 patch.object(autodev.RetryManager, "__init__", return_value=None), \
                 patch.object(autodev.RetryManager, "attempt_fix", side_effect=KeyError("boom")):
                code, out = self._run(["run", path])
        self.assertEqual(code, 1)
        self.assertIn("unexpectedly", out)
        self.assertIn("--verbose", out)


    def test_verbose_flag_is_forwarded_to_retry_manager(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "a.py")
            pathlib.Path(path).write_text("print(1)")
            model = object()
            fake_result = {
                "status": "SUCCESS",
                "attempts_used": 0,
                "max_retries": 3,
                "confidence": "UNVERIFIED",
                "model": "test",
                "old_code": "",
                "new_code": "",
            }
            with patch("models.model_loader.load_model", return_value=model), \
                 patch.object(autodev, "RetryManager") as manager_class:
                manager_class.return_value.attempt_fix.return_value = fake_result
                code, _ = self._run(["run", path, "--verbose"])

            self.assertEqual(code, 0)
            manager_class.assert_called_once_with(model, verbose=True)


    def test_expected_output_file_is_forwarded_to_retry_manager(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "a.py")
            expected_path = os.path.join(d, "expected.txt")
            pathlib.Path(path).write_text("print('wrong')", encoding="utf-8")
            pathlib.Path(expected_path).write_text("right\n", encoding="utf-8")
            model = object()
            fake_result = {
                "status": "SUCCESS",
                "attempts_used": 0,
                "max_retries": 3,
                "confidence": "VERIFIED",
                "model": "test",
                "old_code": "",
                "new_code": "",
            }
            with patch("models.model_loader.load_model", return_value=model), \
                 patch.object(autodev, "RetryManager") as manager_class:
                manager_class.return_value.attempt_fix.return_value = fake_result
                code, _ = self._run(["run", path, "--expected-output-file", expected_path])

            self.assertEqual(code, 0)
            manager_class.return_value.attempt_fix.assert_called_once_with(
                path,
                max_retries=3,
                dry_run=False,
                patch_mode="full",
                fast_mode=True,
                expected_output="right\n",
            )

    def test_missing_expected_output_file_exits_2(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "a.py")
            pathlib.Path(path).write_text("print(1)")
            code, out = self._run(["run", path, "--expected-output-file", os.path.join(d, "missing.txt")])
        self.assertEqual(code, 2)
        self.assertIn("expected-output file not found", out.lower())

    def test_keyboard_interrupt_exits_130(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "a.py")
            pathlib.Path(path).write_text("print(1)")
            with patch("models.model_loader.load_model", return_value=object()), \
                 patch.object(autodev.RetryManager, "__init__", return_value=None), \
                 patch.object(autodev.RetryManager, "attempt_fix", side_effect=KeyboardInterrupt):
                code, _ = self._run(["run", path])
        self.assertEqual(code, 130)


if __name__ == "__main__":
    unittest.main()

