import argparse
import os
import difflib
import traceback
import math
from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
from rich.text import Text

from agent.retry_manager import RetryManager
from languages.language_detector import LanguageDetector


def positive_int(value):
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be an integer") from exc
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return parsed


def describe_confidence(result: dict) -> str:
    """Human-readable confidence line for the summary panel.

    Order matters: more specific cases must be tested before generic ones.
    """
    status = result.get("status", "FAILED")
    attempts = result.get("attempts_used", 0)
    provided = result.get("confidence")
    old_code, new_code = result.get("old_code"), result.get("new_code")
    patched = bool(old_code and new_code and old_code != new_code)

    if isinstance(provided, str) and "%" in provided:
        try:
            pct = float(provided.replace("%", "").strip())
            if not math.isfinite(pct):
                return provided
            grade = "A" if pct >= 90 else "B" if pct >= 75 else "C" if pct >= 60 else "D" if pct >= 40 else "F"
            return f"{provided} ({grade})"
        except ValueError:
            return provided
    if provided == "UNVERIFIED":
        return "UNVERIFIED (execution passed; logic not oracle-checked)"
    if status == "SUCCESS" and attempts == 0 and patched:
        # Rule-based repairs use zero model attempts but DID change the source.
        return "HEURISTIC (rule-based patch; logic not oracle-checked)"
    if status == "SUCCESS" and attempts == 0:
        return "N/A (No repair needed)"
    if status == "SUCCESS" and provided in {"HIGH", "MEDIUM", "LOW"}:
        return provided
    return "Not established"


def main():
    parser = argparse.ArgumentParser(description="AutoDev - Autonomous AI Debugger")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="Run a script and auto-fix bugs.")
    run_parser.add_argument("script_path", type=str, help="Path to the target source file.")
    run_parser.add_argument("--max-retries", type=positive_int, default=3, help="Maximum AI fix attempts.")
    run_parser.add_argument("--dry-run", action="store_true", help="Generate a fix without modifying source files.")
    run_parser.add_argument("--verbose", action="store_true", help="Show full tracebacks for unexpected errors.")
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
            console.print(f"[bold red]Error: '{escape(args.script_path)}' is not a regular file.[/bold red]")
            return 2

        if not LanguageDetector.is_supported(script_path):
            console.print(
                f"[bold red]Error: unsupported file type for '{escape(args.script_path)}'. "
                f"Supported extensions: {', '.join(LanguageDetector.supported_extensions())}[/bold red]"
            )
            return 2

        from models.model_loader import load_model
        try:
            model = load_model()
        except (FileNotFoundError, ValueError, RuntimeError) as exc:
            console.print(f"[bold red]AutoDev configuration error: {escape(str(exc))}[/bold red]")
            return 2

        try:
            manager = RetryManager(model)
            result = manager.attempt_fix(
                script_path,
                max_retries=args.max_retries,
                dry_run=args.dry_run,
                patch_mode=args.mode,
                fast_mode=args.fast,
            )
        except KeyboardInterrupt:
            console.print("\n[bold yellow]Interrupted. If a repair was in progress, "
                          "verify the target file before using it.[/bold yellow]")
            return 130
        except Exception as exc:  # unexpected failure: report, don't hide
            console.print(f"[bold red]AutoDev failed unexpectedly: {escape(type(exc).__name__)}: "
                          f"{escape(str(exc))}[/bold red]")
            if args.verbose:
                console.print(escape(traceback.format_exc()), highlight=False)
            else:
                console.print("[dim]Re-run with --verbose for the full traceback.[/dim]")
            return 1

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
                    console.print(Text(line, style="green"))
                elif line.startswith("-") and not line.startswith("---"):
                    console.print(Text(line, style="red"))
                elif line.startswith("@@"):
                    console.print(Text(line, style="cyan"))
                else:
                    console.print(Text(line))

        attempts = result.get("attempts_used", 0)
        status = result.get("status", "FAILED")
        confidence = escape(describe_confidence(result))

        status_text = (
            "[bold green]SUCCESS[/bold green]" if status == "SUCCESS"
            else "[bold yellow]DRY RUN COMPLETE[/bold yellow]" if status == "DRY_RUN"
            else "[bold red]FAILED[/bold red]"
        )
        summary_text = (
            f"[bold]Target Script:[/bold] {escape(script_path)}\n"
            f"[bold]Model Engine:[/bold]  {escape(str(result.get('model', 'Unknown')))}\n"
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
