"""Cross-language AutoDev repair benchmark with executable output oracles.

Default mode is a no-model preflight:
  * each intentionally broken source must reproduce its declared failure, or
    produce the declared wrong output for the logical-bug case;
  * each reviewed reference implementation must execute successfully and
    match the exact expected output.

Pass --repair to spend model calls. AutoDev is run against a temporary copy of
each fixture and a repair counts as successful only when the patched program
matches the reference output exactly.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


BENCHMARK_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BENCHMARK_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.expected_output import output_matches
from core.runner import run_script
MANIFEST_PATH = BENCHMARK_DIR / "manifest.json"
RESULTS_DIR = BENCHMARK_DIR / "results"
AUTODEV_SCRIPT = PROJECT_ROOT / "autodev.py"
DEFAULT_TIMEOUT_SECONDS = 300


@dataclass(frozen=True)
class BenchmarkCase:
    name: str
    language: str
    source: Path
    reference: Path
    failure_mode: str
    initial_error_contains: str | None
    expected_stdout: str


@dataclass
class BenchmarkResult:
    name: str
    language: str
    status: str
    success: bool
    initial_returncode: int | None = None
    initial_error: str = ""
    reference_returncode: int | None = None
    reference_matches: bool = False
    repair_attempted: bool = False
    autodev_returncode: int | None = None
    patched_returncode: int | None = None
    output_matches: bool = False
    source_changed: bool = False
    attempts_used: int = 0
    model_used: str = ""
    confidence: str = ""
    elapsed_seconds: float = 0.0
    actual_stdout: str = ""
    error_message: str = ""

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["elapsed_seconds"] = round(self.elapsed_seconds, 3)
        return result


def normalize_output(value: str) -> str:
    """Normalize platform line endings and final newlines, not meaningful spaces."""
    return value.replace("\r\n", "\n").replace("\r", "\n").rstrip("\n")


def load_cases() -> list[BenchmarkCase]:
    try:
        raw = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Could not load benchmark manifest {MANIFEST_PATH}: {exc}") from exc

    if not isinstance(raw, dict) or not isinstance(raw.get("cases"), list):
        raise ValueError("Benchmark manifest must contain a 'cases' array.")

    cases: list[BenchmarkCase] = []
    seen: set[str] = set()
    for entry in raw["cases"]:
        if not isinstance(entry, dict):
            raise ValueError("Every benchmark case must be a JSON object.")
        required = ("name", "language", "source", "reference", "failure_mode", "expected_stdout")
        missing = [key for key in required if key not in entry]
        if missing:
            raise ValueError(f"Benchmark case is missing required fields: {', '.join(missing)}")
        if entry["language"] not in {"python", "cpp", "java"}:
            raise ValueError(f"Unsupported benchmark language: {entry['language']}")
        if entry["failure_mode"] not in {"runtime_error", "wrong_output"}:
            raise ValueError(f"Unsupported failure mode in case {entry['name']!r}.")
        if entry["name"] in seen:
            raise ValueError(f"Duplicate benchmark name: {entry['name']}")
        seen.add(entry["name"])

        source = (PROJECT_ROOT / entry["source"]).resolve()
        reference = (PROJECT_ROOT / entry["reference"]).resolve()
        if not source.is_relative_to(PROJECT_ROOT) or not reference.is_relative_to(PROJECT_ROOT):
            raise ValueError(f"Benchmark paths must remain inside the repository: {entry['name']}")
        if not source.is_file() or not reference.is_file():
            raise FileNotFoundError(
                f"Missing source/reference file for {entry['name']}: {source} / {reference}"
            )
        error_marker = entry.get("initial_error_contains")
        if error_marker is not None and not isinstance(error_marker, str):
            raise ValueError(f"initial_error_contains must be text or null for {entry['name']}")
        cases.append(BenchmarkCase(
            name=str(entry["name"]),
            language=entry["language"],
            source=source,
            reference=reference,
            failure_mode=entry["failure_mode"],
            initial_error_contains=error_marker,
            expected_stdout=str(entry["expected_stdout"]),
        ))
    return cases


class BenchmarkRunner:
    def __init__(
        self,
        language_filter: str | None = None,
        benchmark_filter: str | None = None,
        timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    ):
        if timeout_seconds < 1:
            raise ValueError("timeout_seconds must be greater than zero.")
        self.language_filter = language_filter
        self.benchmark_filter = benchmark_filter
        self.timeout_seconds = timeout_seconds

    def discover(self) -> list[BenchmarkCase]:
        cases = load_cases()
        if self.language_filter:
            cases = [case for case in cases if case.language == self.language_filter]
        if self.benchmark_filter:
            cases = [case for case in cases if self.benchmark_filter.lower() in case.name.lower()]
        return cases

    def run_all(
        self,
        *,
        repair: bool = False,
        dry_run: bool = False,
        max_retries: int = 3,
        thorough: bool = False,
        require_all_tools: bool = False,
    ) -> list[BenchmarkResult]:
        cases = self.discover()
        if not cases:
            print("No benchmark cases matched the requested filters.")
            return []

        mode = "LIVE REPAIR" if repair else "FIXTURE PREFLIGHT (no model calls)"
        print(f"AutoDev cross-language benchmark — {mode}")
        print(f"Cases: {len(cases)}")
        if dry_run:
            for case in cases:
                print(f"  {case.language:6} {case.name}: {case.source.relative_to(PROJECT_ROOT)}")
            return []

        results: list[BenchmarkResult] = []
        for index, case in enumerate(cases, 1):
            print(f"\n[{index}/{len(cases)}] {case.language.upper()} — {case.name}")
            result = self._run_case(
                case,
                repair=repair,
                max_retries=max_retries,
                thorough=thorough,
            )
            results.append(result)
            self._print_result(result)

        self._print_summary(results)
        self._save_results(results, repair=repair)
        return results

    def _run_case(
        self,
        case: BenchmarkCase,
        *,
        repair: bool,
        max_retries: int,
        thorough: bool,
    ) -> BenchmarkResult:
        result = BenchmarkResult(
            name=case.name,
            language=case.language,
            status="NOT_RUN",
            success=False,
        )
        started = time.monotonic()

        with tempfile.TemporaryDirectory(prefix=f"autodev-eval-{case.name}-") as temp:
            root = Path(temp)
            broken_dir = root / "broken"
            reference_dir = root / "reference"
            repair_dir = root / "repair"
            broken_dir.mkdir()
            reference_dir.mkdir()
            repair_dir.mkdir()

            broken_copy = broken_dir / case.source.name
            reference_copy = reference_dir / case.reference.name
            shutil.copy2(case.source, broken_copy)
            shutil.copy2(case.reference, reference_copy)

            initial = run_script(str(broken_copy))
            result.initial_returncode = int(initial.get("returncode", 1))
            stderr_lines = (initial.get("stderr") or "").strip().splitlines()
            result.initial_error = next(
                (line.strip() for line in stderr_lines if "Exception" in line or "Error" in line),
                stderr_lines[-1].strip() if stderr_lines else "",
            )

            combined_initial = (initial.get("stderr", "") or "") + "\\n" + (initial.get("stdout", "") or "")
            missing_toolchain = (
                result.initial_returncode == 127
                and any(token in combined_initial.lower() for token in (
                    "g++ was not found", "javac was not found", "java was not found",
                    "install a c++ compiler", "install a jdk",
                ))
            )
            if missing_toolchain:
                result.status = "SKIPPED_TOOLCHAIN"
                result.error_message = combined_initial.strip()
                result.elapsed_seconds = time.monotonic() - started
                return result

            if case.failure_mode == "runtime_error":
                reproduced = result.initial_returncode != 0
                if reproduced and case.initial_error_contains:
                    combined = (initial.get("stderr", "") or "") + "\n" + (initial.get("stdout", "") or "")
                    if case.initial_error_contains != "NONZERO":
                        reproduced = case.initial_error_contains in combined
            else:
                reproduced = (
                    result.initial_returncode == 0
                    and normalize_output(initial.get("stdout", "")) != normalize_output(case.expected_stdout)
                )

            if not reproduced:
                result.status = "FIXTURE_INVALID"
                result.error_message = (
                    "The intentionally buggy fixture did not reproduce its declared "
                    "runtime failure or wrong-output condition."
                )
                result.elapsed_seconds = time.monotonic() - started
                return result

            oracle = run_script(str(reference_copy))
            result.reference_returncode = int(oracle.get("returncode", 1))
            result.reference_matches = (
                result.reference_returncode == 0
                and output_matches(oracle.get("stdout", ""), case.expected_stdout)
            )
            if result.reference_returncode == 127:
                result.status = "SKIPPED_TOOLCHAIN"
                result.error_message = (oracle.get("stderr") or "Required compiler/runtime is unavailable.").strip()
                result.elapsed_seconds = time.monotonic() - started
                return result
            if not result.reference_matches:
                result.status = "ORACLE_INVALID"
                result.actual_stdout = oracle.get("stdout", "")
                result.error_message = (
                    "The reviewed reference implementation did not match the manifest's "
                    "expected output."
                )
                result.elapsed_seconds = time.monotonic() - started
                return result

            if not repair:
                result.status = "PREFLIGHT_PASS"
                result.success = True
                result.elapsed_seconds = time.monotonic() - started
                return result

            shutil.copy2(case.source, repair_dir / case.source.name)
            repair_target = repair_dir / case.source.name
            before = repair_target.read_bytes()
            expected_file = repair_dir / "expected_stdout.txt"
            expected_file.write_text(case.expected_stdout, encoding="utf-8")
            command = [
                sys.executable,
                str(AUTODEV_SCRIPT),
                "run",
                str(repair_target),
                "--max-retries",
                str(max_retries),
                "--expected-output-file",
                str(expected_file),
            ]
            if thorough:
                command.append("--no-fast")

            result.repair_attempted = True
            repair_started = time.monotonic()
            try:
                process = subprocess.run(
                    command,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=self.timeout_seconds,
                    cwd=str(PROJECT_ROOT),
                    check=False,
                )
                result.elapsed_seconds = time.monotonic() - repair_started
                result.autodev_returncode = process.returncode
                cli_output = process.stdout + "\n" + process.stderr
                result.attempts_used = self._parse_int(cli_output, r"Attempts Used:\s*(\d+)\s*/")
                result.model_used = self._parse_text(cli_output, r"Model Engine:\s*([^\r\n│]+)")
                result.confidence = self._parse_text(cli_output, r"Confidence:\s*([^\r\n│]+)")
            except subprocess.TimeoutExpired:
                result.status = "TIMEOUT"
                result.error_message = f"AutoDev exceeded the {self.timeout_seconds}s evaluation timeout."
                result.elapsed_seconds = time.monotonic() - repair_started
                return result
            except OSError as exc:
                result.status = "EVALUATION_ERROR"
                result.error_message = f"Could not start AutoDev: {type(exc).__name__}: {exc}"
                result.elapsed_seconds = time.monotonic() - repair_started
                return result

            result.source_changed = repair_target.read_bytes() != before
            final = run_script(str(repair_target))
            result.patched_returncode = int(final.get("returncode", 1))
            result.actual_stdout = final.get("stdout", "")
            result.output_matches = (
                result.patched_returncode == 0
                and output_matches(result.actual_stdout, case.expected_stdout)
            )

            if result.output_matches and result.source_changed and result.autodev_returncode == 0:
                result.status = "REPAIR_PASS"
                result.success = True
            elif result.output_matches and result.autodev_returncode != 0:
                result.status = "OUTPUT_CORRECT_BUT_AUTODEV_FAILED"
                result.error_message = "Output matches the oracle, but AutoDev returned a failure exit code."
            elif not result.source_changed:
                result.status = "NOT_REPAIRED"
                result.error_message = "AutoDev did not modify the isolated fixture."
            elif result.patched_returncode != 0:
                result.status = "PATCH_STILL_FAILS"
                result.error_message = (final.get("stderr") or "Patched program still exits with an error.").strip()
            else:
                result.status = "WRONG_OUTPUT"
                result.error_message = "Patched program runs but does not match the expected output."

        return result

    @staticmethod
    def _parse_int(text: str, pattern: str) -> int:
        match = re.search(pattern, text)
        return int(match.group(1)) if match else 0

    @staticmethod
    def _parse_text(text: str, pattern: str) -> str:
        match = re.search(pattern, text)
        return match.group(1).strip() if match else ""

    @staticmethod
    def _print_result(result: BenchmarkResult) -> None:
        elapsed = f"{result.elapsed_seconds:.2f}s"
        status = "PASS" if result.success else result.status
        print(f"  {status:34} {elapsed}")
        if result.initial_error:
            print(f"  initial: {result.initial_error}")
        if result.error_message:
            print(f"  detail: {result.error_message[:300]}")

    @staticmethod
    def _print_summary(results: list[BenchmarkResult]) -> None:
        total = len(results)
        passed = sum(result.success for result in results)
        repair_count = sum(result.repair_attempted for result in results)
        if repair_count:
            denominator = repair_count
            print(
                f"\nRepair score: {passed}/{denominator} "
                f"({passed / denominator * 100:.1f}%)"
            )
        else:
            print(f"\nFixture/oracle preflight: {passed}/{total} passed")
        for status in sorted({result.status for result in results}):
            count = sum(result.status == status for result in results)
            print(f"  {status}: {count}")

    @staticmethod
    def _save_results(results: list[BenchmarkResult], *, repair: bool) -> Path:
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        output = RESULTS_DIR / f"evaluation_{timestamp}.json"
        passed = sum(result.success for result in results)
        payload = {
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "mode": "repair" if repair else "preflight",
            "total": len(results),
            "passed": passed,
            "success_rate": round(passed / len(results) * 100, 2) if results else 0.0,
            "scoring_rule": (
                "A repair passes only if the copied source changes, AutoDev exits successfully, "
                "the final program exits successfully, and stdout exactly matches the reference oracle."
            ),
            "results": [result.to_dict() for result in results],
        }
        output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"Detailed report: {output.relative_to(PROJECT_ROOT)}")
        return output


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate and evaluate AutoDev repairs across Python, C++, and Java.")
    parser.add_argument("--dry-run", action="store_true", help="List selected cases without executing them.")
    parser.add_argument("--repair", action="store_true", help="Run AutoDev on isolated copies (uses configured model providers).")
    parser.add_argument("--language", choices=["python", "cpp", "java"], help="Run only one language.")
    parser.add_argument("--benchmark", help="Run cases whose name contains this text.")
    parser.add_argument("--max-retries", type=int, default=3, help="AutoDev retry budget (default: 3).")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT_SECONDS, help="Per-repair CLI timeout in seconds.")
    parser.add_argument("--thorough", action="store_true", help="Use AutoDev's non-fast multi-candidate mode.")
    parser.add_argument("--require-all-tools", action="store_true", help="Fail when any compiler/runtime required by a case is unavailable.")
    args = parser.parse_args(argv)

    if args.max_retries < 1:
        parser.error("--max-retries must be greater than zero.")
    if args.timeout < 1:
        parser.error("--timeout must be greater than zero.")

    try:
        runner = BenchmarkRunner(
            language_filter=args.language,
            benchmark_filter=args.benchmark,
            timeout_seconds=args.timeout,
        )
        results = runner.run_all(
            repair=args.repair,
            dry_run=args.dry_run,
            max_retries=args.max_retries,
            thorough=args.thorough,
            require_all_tools=args.require_all_tools,
        )
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"Benchmark evaluation failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    if args.dry_run:
        return 0
    if not results:
        return 1

    failed = [
        result for result in results
        if not result.success and (args.require_all_tools or result.status != "SKIPPED_TOOLCHAIN")
    ]
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
