"""
benchmarks/benchmark_runner.py
-------------------------------
AutoDev benchmark suite runner.

Runs all benchmark scripts through the AutoDev repair pipeline and
tracks success rates, latency, and model effectiveness.

Usage:
    python benchmarks/benchmark_runner.py
    python benchmarks/benchmark_runner.py --dry-run
    python benchmarks/benchmark_runner.py --language python
    python benchmarks/benchmark_runner.py --benchmark zero_div
"""

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any

try:
    from rich.console import Console
    from rich.table import Table
    from rich.panel import Panel
    from rich import box
    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False

# Resolve paths relative to this file
BENCHMARK_DIR = Path(__file__).parent
AUTODEV_ROOT = BENCHMARK_DIR.parent
RESULTS_DIR = BENCHMARK_DIR / "results"
AUTODEV_SCRIPT = AUTODEV_ROOT / "autodev.py"


# ---------------------------------------------------------------------------
# Benchmark record
# ---------------------------------------------------------------------------

class BenchmarkResult:
    def __init__(self, name: str, language: str, file_path: str):
        self.name = name
        self.language = language
        self.file_path = file_path
        self.success = False
        self.attempts_used = 0
        self.elapsed_seconds = 0.0
        self.initial_error = ""
        self.final_status = "NOT_RUN"
        self.model_used = ""
        self.confidence = ""
        self.error_message = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "language": self.language,
            "file": self.file_path,
            "success": self.success,
            "attempts_used": self.attempts_used,
            "elapsed_seconds": round(self.elapsed_seconds, 2),
            "initial_error": self.initial_error,
            "final_status": self.final_status,
            "model_used": self.model_used,
            "confidence": self.confidence,
            "error_message": self.error_message,
        }


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

class BenchmarkRunner:

    # Timeout per benchmark in seconds
    TIMEOUT_SECONDS = 300  # 5 minutes per script

    def __init__(self, language_filter: Optional[str] = None, benchmark_filter: Optional[str] = None):
        self.language_filter = language_filter
        self.benchmark_filter = benchmark_filter
        self.console = Console() if RICH_AVAILABLE else None

    def discover(self) -> List[BenchmarkResult]:
        """Discover all benchmark files."""
        results = []
        lang_dirs = {
            "python": (BENCHMARK_DIR / "python", [".py"]),
            "cpp": (BENCHMARK_DIR / "cpp", [".cpp", ".cc"]),
            "java": (BENCHMARK_DIR / "java", [".java"]),
        }

        for lang, (dir_path, extensions) in lang_dirs.items():
            if self.language_filter and lang != self.language_filter:
                continue
            if not dir_path.exists():
                continue
            for ext in extensions:
                for file in sorted(dir_path.glob(f"*{ext}")):
                    # Skip backup files
                    if ".backup" in file.name:
                        continue
                    if self.benchmark_filter and self.benchmark_filter not in file.name:
                        continue
                    results.append(BenchmarkResult(
                        name=file.stem,
                        language=lang,
                        file_path=str(file),
                    ))
        return results

    def run_all(
        self,
        dry_run: bool = False,
        max_retries: int = 3,
    ) -> List[BenchmarkResult]:
        """Run all discovered benchmarks."""
        benchmarks = self.discover()
        if not benchmarks:
            self._print("[yellow]No benchmarks found.[/yellow]")
            return []

        self._print(f"\n[bold cyan]AutoDev Benchmark Suite[/bold cyan]")
        self._print(f"Found {len(benchmarks)} benchmark(s)\n")

        if dry_run:
            self._print_discovery(benchmarks)
            return benchmarks

        results = []
        for i, bench in enumerate(benchmarks, 1):
            self._print(f"[bold][ {i}/{len(benchmarks)} ][/bold] {bench.language.upper()} — {bench.name}")
            result = self._run_single(bench, max_retries=max_retries)
            results.append(result)
            self._print_result_line(result)

        self._print_summary(results)
        self._save_results(results)
        return results

    def _run_single(
        self, bench: BenchmarkResult, max_retries: int = 3
    ) -> BenchmarkResult:
        """Run a single benchmark through autodev.py."""
        # First: capture the initial error
        bench.initial_error = self._get_initial_error(bench.file_path, bench.language)

        # Then: run through AutoDev
        cmd = [
            sys.executable,
            str(AUTODEV_SCRIPT),
            "run",
            bench.file_path,
            "--max-retries", str(max_retries),
        ]

        start = time.time()
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.TIMEOUT_SECONDS,
                cwd=str(AUTODEV_ROOT),
            )
            bench.elapsed_seconds = time.time() - start
            output = proc.stdout + proc.stderr

            # Parse AutoDev output for summary info
            bench.success = "Final Status:  SUCCESS" in output or "Status:  SUCCESS" in output
            bench.final_status = "SUCCESS" if bench.success else "FAILED"

            # Extract attempts used
            for line in output.splitlines():
                if "Attempts Used:" in line:
                    parts = line.split(":")[-1].strip().split("/")
                    try:
                        bench.attempts_used = int(parts[0].strip())
                    except (ValueError, IndexError):
                        pass
                if "Model Engine:" in line:
                    bench.model_used = line.split(":", 1)[-1].strip().strip("| ")
                if "Confidence:" in line and "%" in line:
                    bench.confidence = line.split(":")[-1].strip().strip("| ")

        except subprocess.TimeoutExpired:
            bench.elapsed_seconds = time.time() - start
            bench.final_status = "TIMEOUT"
            bench.error_message = f"Timed out after {self.TIMEOUT_SECONDS}s"
        except Exception as e:
            bench.elapsed_seconds = time.time() - start
            bench.final_status = "ERROR"
            bench.error_message = str(e)

        return bench

    def _get_initial_error(
        self, file_path: str, language: str
    ) -> str:
        """Run the file directly to capture the initial error type."""
        try:
            if language == "python":
                proc = subprocess.run(
                    [sys.executable, file_path],
                    capture_output=True, text=True, timeout=10,
                )
                stderr = proc.stderr.strip()
                # Extract error type from last line
                for line in reversed(stderr.splitlines()):
                    line = line.strip()
                    if line and ":" in line and not line.startswith("File "):
                        return line.split(":")[0].strip()
            elif language == "cpp":
                return "CompileError/RuntimeError"
            elif language == "java":
                return "RuntimeException"
        except Exception:
            pass
        return "Unknown"

    def _print(self, msg: str) -> None:
        if self.console:
            self.console.print(msg)
        else:
            print(msg.replace("[bold]", "").replace("[/bold]", "")
                  .replace("[yellow]", "").replace("[/yellow]", "")
                  .replace("[cyan]", "").replace("[/cyan]", ""))

    def _print_result_line(self, result: BenchmarkResult) -> None:
        icon = "OK" if result.success else "X"
        elapsed = f"{result.elapsed_seconds:.1f}s"
        color = "green" if result.success else "red"
        self._print(
            f"  [{color}]{icon}[/{color}] {result.final_status} | "
            f"{elapsed} | error={result.initial_error}"
        )

    def _print_discovery(self, benchmarks: List[BenchmarkResult]) -> None:
        self._print("[bold]Discovered benchmarks:[/bold]")
        for b in benchmarks:
            self._print(f"  [{b.language}] {b.name} — {b.file_path}")

    def _print_summary(self, results: List[BenchmarkResult]) -> None:
        total = len(results)
        successes = sum(1 for r in results if r.success)
        timeouts = sum(1 for r in results if r.final_status == "TIMEOUT")
        avg_time = sum(r.elapsed_seconds for r in results) / total if total > 0 else 0

        if RICH_AVAILABLE and self.console:
            table = Table(
                title="Benchmark Summary",
                box=box.ROUNDED,
                show_lines=True,
            )
            table.add_column("#", justify="right", style="dim")
            table.add_column("Name", style="bold")
            table.add_column("Lang", justify="center")
            table.add_column("Status", justify="center")
            table.add_column("Initial Error")
            table.add_column("Attempts", justify="right")
            table.add_column("Time", justify="right")

            for i, r in enumerate(results, 1):
                status_color = "green" if r.success else ("yellow" if r.final_status == "TIMEOUT" else "red")
                table.add_row(
                    str(i),
                    r.name,
                    r.language,
                    f"[{status_color}]{r.final_status}[/{status_color}]",
                    r.initial_error[:30],
                    str(r.attempts_used),
                    f"{r.elapsed_seconds:.1f}s",
                )

            self.console.print()
            self.console.print(table)
            self.console.print(Panel(
                f"[bold]Total:[/bold] {total}  "
                f"[green]Passed:[/green] {successes}  "
                f"[red]Failed:[/red] {total - successes - timeouts}  "
                f"[yellow]Timeout:[/yellow] {timeouts}  "
                f"[cyan]Success Rate:[/cyan] {successes/total*100:.1f}%  "
                f"[dim]Avg Time:[/dim] {avg_time:.1f}s",
                title="Results",
                border_style="cyan",
            ))
        else:
            print(f"\n=== Benchmark Results ===")
            print(f"Total: {total} | Passed: {successes} | Failed: {total - successes}")
            print(f"Success Rate: {successes/total*100:.1f}% | Avg Time: {avg_time:.1f}s")

    def _save_results(self, results: List[BenchmarkResult]) -> None:
        """Save results to JSON file."""
        RESULTS_DIR.mkdir(exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_file = RESULTS_DIR / f"run_{timestamp}.json"
        data = {
            "timestamp": datetime.now().isoformat(),
            "total": len(results),
            "successes": sum(1 for r in results if r.success),
            "success_rate": sum(1 for r in results if r.success) / len(results) * 100 if results else 0,
            "results": [r.to_dict() for r in results],
        }
        try:
            with open(output_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            print(f"Results saved to: {output_file}")
        except Exception as e:
            print(f"Warning: Could not save results: {e}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="AutoDev Benchmark Suite Runner"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List benchmarks without running them",
    )
    parser.add_argument(
        "--language",
        choices=["python", "cpp", "java"],
        help="Run only benchmarks for a specific language",
    )
    parser.add_argument(
        "--benchmark",
        type=str,
        help="Filter benchmarks by filename pattern",
    )
    parser.add_argument(
        "--max-retries",
        type=int,
        default=3,
        help="Maximum retries per benchmark (default: 3)",
    )
    args = parser.parse_args()

    runner = BenchmarkRunner(
        language_filter=args.language,
        benchmark_filter=args.benchmark,
    )
    runner.run_all(
        dry_run=args.dry_run,
        max_retries=args.max_retries,
    )


if __name__ == "__main__":
    main()
