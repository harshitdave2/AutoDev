import argparse
import sys
import os
import difflib
from rich.console import Console
from rich.panel import Panel

from agent.retry_manager import RetryManager


def positive_int(value):
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be an integer") from exc
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return parsed


def main():
    parser = argparse.ArgumentParser(description="AutoDev - Autonomous AI Debugger")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="Run a script and auto-fix bugs.")
    run_parser.add_argument("script_path", type=str, help="Path to the target source file.")
    run_parser.add_argument("--max-retries", type=positive_int, default=3, help="Maximum AI fix attempts.")
    run_parser.add_argument("--dry-run", action="store_true", help="Generate a fix without modifying source files.")
    run_parser.add_argument("--verbose", action="store_true", help="Enable verbose output.")
    run_parser.add_argument(
        "--mode", type=str, default="full", choices=["full", "function"],
        help="Patching mode: full-file replacement or a surgical function-level patch.",
    )
    run_parser.add_argument(
        "--fast", action="store_true", default=True,
        help="Speed-first repair mode (enabled by default).",
    )
    run_parser.add_argument(
        "--no-fast", dest="fast", action="store_false",
        help="Disable fast mode and use thorough multi-candidate repair.",
    )

    args = parser.parse_args()
    console = Console()

    if args.command == "run":
        script_path = os.path.abspath(os.path.expanduser(args.script_path))
        if not os.path.isfile(script_path):
            console.print(f"[bold red]Error: '{args.script_path}' is not a regular file.[/bold red]")
            return 2

        from models.model_loader import load_model
        try:
            model = load_model()
            manager = RetryManager(model)
            result = manager.attempt_fix(
                script_path,
                max_retries=args.max_retries,
                dry_run=args.dry_run,
                patch_mode=args.mode,
                fast_mode=args.fast,
            )
        except (FileNotFoundError, ValueError, RuntimeError) as exc:
            console.print(f"[bold red]AutoDev configuration error: {exc}[/bold red]")
            return 2

        if args.fast:
            console.print("[bold cyan][FastMode] Speed-first repair mode enabled[/bold cyan]")

        if result.get("old_code") and result.get("new_code"):
            console.print("\n[bold cyan]=== AI Patch Diff ===[/bold cyan]")
            diff = difflib.unified_diff(
                result["old_code"].splitlines(),
                result["new_code"].splitlines(),
                fromfile="Original",
                tofile="AI_Fixed",
                lineterm="",
            )
            for line in diff:
                if line.startswith("+") and not line.startswith("+++"):
                    console.print(f"[green]{line}[/green]")
                elif line.startswith("-") and not line.startswith("---"):
                    console.print(f"[red]{line}[/red]")
                elif line.startswith("@@"):
                    console.print(f"[cyan]{line}[/cyan]")
                else:
                    console.print(line)

        attempts = result.get("attempts_used", 0)
        status = result.get("status", "FAILED")
        provided_conf = result.get("confidence")

        if isinstance(provided_conf, str) and "%" in provided_conf:
            try:
                pct_val = float(provided_conf.replace("%", "").strip())
                grade = "A" if pct_val >= 90 else "B" if pct_val >= 75 else "C" if pct_val >= 60 else "D" if pct_val >= 40 else "F"
                confidence = f"{provided_conf} ({grade})"
            except ValueError:
                confidence = provided_conf
        elif status == "SUCCESS" and attempts == 0:
            confidence = "N/A (No repair needed)"
        elif status == "SUCCESS" and provided_conf in {"HIGH", "MEDIUM", "LOW"}:
            confidence = provided_conf
        elif provided_conf == "UNVERIFIED":
            confidence = "UNVERIFIED (execution passed; logic not oracle-checked)"
        else:
            confidence = "Not established"

        status_text = (
            "[bold green]SUCCESS[/bold green]" if status == "SUCCESS"
            else "[bold yellow]DRY RUN COMPLETE[/bold yellow]" if status == "DRY_RUN"
            else "[bold red]FAILED[/bold red]"
        )
        summary_text = (
            f"[bold]Target Script:[/bold] {script_path}\n"
            f"[bold]Model Engine:[/bold]  {result.get('model', 'Unknown')}\n"
            f"[bold]Attempts Used:[/bold] {attempts}/{result.get('max_retries', args.max_retries)}\n"
            f"[bold]Confidence:[/bold]    {confidence}\n"
            "---------------------------------\n"
            f"[bold]Final Status:[/bold]  {status_text}"
        )
        console.print("\n")
        console.print(Panel(summary_text, title="[bold white]AutoDev Execution Summary[/bold white]", expand=False, border_style="blue"))
        return 0 if status in {"SUCCESS", "DRY_RUN"} else 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
