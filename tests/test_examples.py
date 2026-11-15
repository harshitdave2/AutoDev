import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ReproducibleExampleTests(unittest.TestCase):
    def _run_fixture(self, relative_path):
        return subprocess.run(
            [sys.executable, str(ROOT / relative_path)],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )

    def test_broken_python_example_executes_and_reproduces_type_error(self):
        result = self._run_fixture("examples/broken_python.py")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("TypeError", result.stderr)

    def test_zero_division_fixture_executes_and_reproduces_zero_division(self):
        result = self._run_fixture("test_scripts/zero_div.py")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("ZeroDivisionError", result.stderr)


if __name__ == "__main__":
    unittest.main()
