import io
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from rich.console import Console

from agent.retry_manager import RetryManager
from core.patcher import backup_file


class RetryManagerSafetyTests(unittest.TestCase):
    def _manager(self, verbose=False):
        with patch("agent.retry_manager.AutoDevAgent", return_value=object()):
            return RetryManager(model=object(), verbose=verbose)

    def test_literal_output_does_not_parse_rich_markup(self):
        manager = self._manager()
        output = io.StringIO()
        manager.console = Console(file=output, force_terminal=False, color_system=None)

        manager._print_literal("[bold red]this is program output[/bold red]")

        self.assertIn("[bold red]this is program output[/bold red]", output.getvalue())

    def test_unexpected_exception_restores_original_file(self):
        manager = self._manager()
        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir) / "target.py"
            target.write_text("print('original')\n", encoding="utf-8")

            def fail_after_mutation(script_path, **kwargs):
                manager._active_backup_paths.append(backup_file(str(target)))
                target.write_text("print('partially patched')\n", encoding="utf-8")
                raise RuntimeError("simulated unexpected failure")

            with patch.object(manager, "_attempt_fix_impl", side_effect=fail_after_mutation):
                with self.assertRaisesRegex(RuntimeError, "simulated unexpected failure"):
                    manager.attempt_fix(str(target))

            self.assertEqual(target.read_text(encoding="utf-8"), "print('original')\n")


    def test_successful_exit_with_wrong_expected_output_enters_repair_path(self):
        manager = self._manager()
        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir) / "logic_bug.py"
            original = "print('actual')\n"
            target.write_text(original, encoding="utf-8")

            with patch("agent.retry_manager.run_script", return_value={
                    "returncode": 0,
                    "stdout": "actual\n",
                    "stderr": "",
                }) as execute, \
                 patch("agent.retry_manager.BugLocalizer.localize", return_value=SimpleNamespace(
                    primary_target=None,
                    suspicious_funcs=[],
                )), \
                 patch("agent.retry_manager.requests.get", return_value=SimpleNamespace(status_code=503)), \
                 patch("agent.retry_manager._repair_memory", None), \
                 patch.dict(os.environ, {"GROQ_API_KEY": "", "GEMINI_API_KEY": ""}):
                result = manager.attempt_fix(
                    str(target),
                    max_retries=1,
                    expected_output="expected\n",
                )

            self.assertEqual(result["status"], "FAILED")
            self.assertEqual(execute.call_count, 1)
            self.assertEqual(target.read_text(encoding="utf-8"), original)


    def test_model_candidate_must_match_expected_output_to_be_accepted(self):
        manager = self._manager()
        fake_model = SimpleNamespace(last_successful_model="fake-model")
        manager.agent = SimpleNamespace(
            model=fake_model,
            request_fix=lambda **kwargs: ["print('expected')\n"],
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir) / "logic_bug.py"
            target.write_text("print('actual')\n", encoding="utf-8")

            with patch("agent.retry_manager.BugLocalizer.localize", return_value=SimpleNamespace(
                    primary_target=None,
                    suspicious_funcs=[],
                )), \
                 patch("agent.retry_manager.requests.get", return_value=SimpleNamespace(status_code=200)), \
                 patch("agent.retry_manager._repair_memory", None), \
                 patch.object(manager, "_build_pruned_context", return_value="print('actual')\n"):
                result = manager.attempt_fix(
                    str(target),
                    max_retries=1,
                    expected_output="expected\n",
                )

            self.assertEqual(result["status"], "SUCCESS")
            self.assertEqual(result["confidence"], "VERIFIED")
            self.assertEqual(target.read_text(encoding="utf-8"), "print('expected')\n")

    def test_expected_output_error_includes_expected_and_actual_values(self):
        mismatch = RetryManager._expected_output_error("expected\n", "actual\n")
        self.assertIn("Expected stdout:", mismatch)
        self.assertIn("expected", mismatch)
        self.assertIn("Actual stdout:", mismatch)
        self.assertIn("actual", mismatch)

    def test_verbose_exception_logging_includes_traceback(self):
        manager = self._manager(verbose=True)
        output = io.StringIO()
        manager.console = Console(file=output, force_terminal=False, color_system=None)

        try:
            raise RuntimeError("diagnostic detail")
        except RuntimeError as exc:
            manager._log_exception("test phase", exc)

        self.assertIn("diagnostic detail", output.getvalue())
        self.assertIn("Traceback (most recent call last)", output.getvalue())


if __name__ == "__main__":
    unittest.main()
