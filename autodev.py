import argparse
import sys
import os
import difflib
from rich.console import Console
from rich.panel import Panel

from agent.retry_manager import RetryManager


def main():
    # 1. Setup Argparse Command Structure
    parser = argparse.ArgumentParser(description="AutoDev - Autonomous AI Debugger")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # "run" command configuration
    run_parser = subparsers.add_parser("run", help="Run a script and auto-fix bugs.")
    run_parser.add_argument("script_path", type=str, help="Path to the target Python script.")
    run_parser.add_argument("--max-retries", type=int, default=3, help="Maximum AI fix attempts.")
    run_parser.add_argument("--dry-run", action="store_true", help="Generate AI fix without applying it.")
    run_parser.add_argument("--verbose", action="store_true", help="Enable verbose output.")

    args = parser.parse_args()
    console = Console()

    # 2. Command Execution
    if args.command == "run":
        if not os.path.exists(args.script_path):
            console.print(f"[bold red]Error: File '{args.script_path}' not found.[/bold red]")
            sys.exit(1)

        from models.model_loader import load_model
        model = load_model()
        manager = RetryManager(model)

        # Call the manager with the new dry_run argument
        result = manager.attempt_fix(args.script_path, max_retries=args.max_retries, dry_run=args.dry_run)

        # --- FEATURE: Git-Style Diff Preview ---
        if result.get("old_code") and result.get("new_code"):
            console.print("\n[bold cyan]=== AI Patch Diff ===[/bold cyan]")

            diff = difflib.unified_diff(
                result["old_code"].splitlines(),
                result["new_code"].splitlines(),
                fromfile='Original',
                tofile='AI_Fixed',
                lineterm=''
            )

            for line in diff:
                if line.startswith('+') and not line.startswith('+++'):
                    console.print(f"[green]{line}[/green]")
                elif line.startswith('-') and not line.startswith('---'):
                    console.print(f"[red]{line}[/red]")
                elif line.startswith('@@'):
                    console.print(f"[cyan]{line}[/cyan]")
                else:
                    console.print(line)

        # --- FEATURE: Confidence Indicator ---
        attempts = result.get("attempts_used", 1)
        status = result.get("status", "FAILED")
        old_code = result.get("old_code", "")

        provided_conf = result.get("confidence")
        if provided_conf == "HIGH":
            confidence = "[bold green]HIGH[/bold green]"
        elif provided_conf == "MEDIUM":
            confidence = "[bold yellow]MEDIUM[/bold yellow]"
        elif provided_conf == "LOW":
            confidence = "[bold red]LOW[/bold red]"
        elif status == "SUCCESS" and attempts == 1 and not old_code:
            confidence = "[blue]N/A (No Bugs Found)[/blue]"
        elif attempts == 1:
            confidence = "[bold green]HIGH[/bold green]"
        elif attempts == 2:
            confidence = "[bold yellow]MEDIUM[/bold yellow]"
        else:
            confidence = "[bold red]LOW[/bold red]"

        # Format Status Color
        if status == "SUCCESS":
            status_text = "[bold green]SUCCESS[/bold green]"
        elif status == "DRY_RUN":
            status_text = "[bold yellow]DRY RUN COMPLETE[/bold yellow]"
        else:
            status_text = "[bold red]FAILED[/bold red]"

        # --- FEATURE: Final Summary Panel ---
        summary_text = (
            f"[bold]Target Script:[/bold] {args.script_path}\n"
            f"[bold]Model Engine:[/bold]  {result.get('model', 'Unknown')}\n"
            f"[bold]Attempts Used:[/bold] {attempts}/{result.get('max_retries', args.max_retries)}\n"
            f"[bold]Confidence:[/bold]    {confidence}\n"
            f"---------------------------------\n"
            f"[bold]Final Status:[/bold]  {status_text}"
        )

        console.print("\n")
        console.print(Panel(summary_text, title="[bold white]AutoDev Execution Summary[/bold white]", expand=False,
                            border_style="blue"))


if __name__ == "__main__":
    main()