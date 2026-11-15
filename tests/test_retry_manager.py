import io
import tempfile
import unittest
from pathlib import Path
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
