import json
import tempfile
import unittest
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import patch

from benchmarks.benchmark_runner import (
    BenchmarkCase,
    BenchmarkRunner,
    load_cases,
    normalize_output,
)


class BenchmarkManifestTests(unittest.TestCase):
    def test_manifest_has_cases_for_all_supported_languages(self):
        cases = load_cases()
        self.assertEqual({case.language for case in cases}, {"python", "cpp", "java"})
        self.assertGreaterEqual(len(cases), 8)

    def test_expected_output_normalizes_line_endings_not_other_whitespace(self):
        self.assertEqual(normalize_output("value  \r\nnext\r\n"), "value  \nnext")
        self.assertNotEqual(normalize_output("value \n"), normalize_output("value\n"))


class BenchmarkPreflightTests(unittest.TestCase):
    def test_preflight_requires_runtime_failure_and_matching_reference(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            broken = root / "broken.py"
            reference = root / "reference.py"
            broken.write_text("raise TypeError('bad')\n", encoding="utf-8")
            reference.write_text("print('expected')\n", encoding="utf-8")
            case = BenchmarkCase(
                name="sample",
                language="python",
                source=broken,
                reference=reference,
                failure_mode="runtime_error",
                initial_error_contains="TypeError",
                expected_stdout="expected\n",
            )
            runner = BenchmarkRunner()
            outcomes = [
                {"returncode": 1, "stdout": "", "stderr": "TypeError: bad"},
                {"returncode": 0, "stdout": "expected\n", "stderr": ""},
            ]
            with patch("benchmarks.benchmark_runner.run_script", side_effect=outcomes) as execute:
                result = runner._run_case(case, repair=False, max_retries=1, thorough=False)

            self.assertEqual(result.status, "PREFLIGHT_PASS")
            self.assertTrue(result.success)
            self.assertEqual(execute.call_count, 2)

    def test_preflight_rejects_reference_output_mismatch(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            broken = root / "broken.py"
            reference = root / "reference.py"
            broken.write_text("raise TypeError('bad')\n", encoding="utf-8")
            reference.write_text("print('wrong')\n", encoding="utf-8")
            case = BenchmarkCase(
                name="sample",
                language="python",
                source=broken,
                reference=reference,
                failure_mode="runtime_error",
                initial_error_contains="TypeError",
                expected_stdout="expected\n",
            )
            outcomes = [
                {"returncode": 1, "stdout": "", "stderr": "TypeError: bad"},
                {"returncode": 0, "stdout": "wrong\n", "stderr": ""},
            ]
            with patch("benchmarks.benchmark_runner.run_script", side_effect=outcomes):
                result = BenchmarkRunner()._run_case(
                    case, repair=False, max_retries=1, thorough=False
                )

            self.assertEqual(result.status, "ORACLE_INVALID")
            self.assertFalse(result.success)


    def test_live_repair_passes_oracle_file_and_scores_exact_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            broken = root / "broken.py"
            reference = root / "reference.py"
            broken.write_text("raise TypeError('bad')\\n", encoding="utf-8")
            reference.write_text("print('expected')\\n", encoding="utf-8")
            case = BenchmarkCase(
                name="sample",
                language="python",
                source=broken,
                reference=reference,
                failure_mode="runtime_error",
                initial_error_contains="TypeError",
                expected_stdout="expected\\n",
            )
            calls = [
                {"returncode": 1, "stdout": "", "stderr": "TypeError: bad"},
                {"returncode": 0, "stdout": "expected\\n", "stderr": ""},
                {"returncode": 0, "stdout": "expected\\n", "stderr": ""},
            ]

            def fake_autodev(command, **kwargs):
                self.assertIn("--expected-output-file", command)
                oracle_path = Path(command[command.index("--expected-output-file") + 1])
                self.assertEqual(oracle_path.read_text(encoding="utf-8"), "expected\\n")
                target = Path(command[3])
                target.write_text("print('expected')\\n", encoding="utf-8")
                return SimpleNamespace(
                    returncode=0,
                    stdout="Final Status: SUCCESS",
                    stderr="",
                )

            with patch("benchmarks.benchmark_runner.run_script", side_effect=calls), \\
                 patch("benchmarks.benchmark_runner.subprocess.run", side_effect=fake_autodev):
                result = BenchmarkRunner()._run_case(
                    case, repair=True, max_retries=1, thorough=False
                )

            self.assertEqual(result.status, "REPAIR_PASS")
            self.assertTrue(result.success)
            self.assertTrue(result.source_changed)
            self.assertTrue(result.output_matches)

    def test_manifest_source_and_reference_are_distinct_files(self):
        for case in load_cases():
            self.assertNotEqual(case.source, case.reference)
            self.assertTrue(case.source.is_file())
            self.assertTrue(case.reference.is_file())


if __name__ == "__main__":
    unittest.main()
