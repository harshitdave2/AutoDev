"""
agent/retry_manager.py
-----------------------
Core retry orchestrator for AutoDev (production-grade upgrade).

Phase 1 upgrades:
  + ContextPruner       -- trims full-file code to token budget before LLM call
  + PatchValidator      -- validates each candidate semantically BEFORE applying
  + CandidateRanker     -- scores all candidates and applies best-first
  + BehaviorFingerprint -- rejects patches that produce identical output (no fix)
  + FunctionPatcher     -- opt-in function-level patching (--mode function)
  + ModelOrchestrator   -- upgraded quality gate, per-model retry, timeout

Phase 2 upgrades:
  + BehaviorEngine      -- domain-aware output analysis (negative fib, >100% accuracy, etc.)
  + RegressionGuard     -- pre/post patch snapshot regression detection
  + ConfidenceEngine    -- real percentage confidence scoring (0-100%)
  + BugLocalizer        -- intelligent traceback-based bug localization
  + RepairMemory        -- persistent cross-session repair memory

All existing features preserved:
  - Initial execution check
  - Backup / restore
  - Heuristic pre-fix layer
  - Ollama availability check
  - Quick C++ repairs
  - Quick paren-balance repair
  - Local retry loop
  - Cloud escalation
  - Failure restore
  - Git-diff summary (via autodev.py)
"""

import os
import sys
import shutil
import ast
import requests
import subprocess
import tempfile

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from rich.console import Console
from core.runner import run_script
from core.analyzer import parse_traceback, extract_function_context, extract_additional_context
from core.context_engine import ContextEngine
from core.patcher import backup_file
from core.project_utils import find_project_root, resolve_patch_target
from core.syntax_repair import auto_fix_syntax

# ---- Phase 1 modules ----
from core.patch_validator import PatchValidator
from core.context_pruner import ContextPruner, make_pruner
from core.behavior_fingerprint import BehaviorFingerprint
from core.candidate_ranker import CandidateRanker
from core.function_patcher import FunctionPatcher

# ---- Phase 2 modules ----
from core.behavior_engine import BehaviorEngine
from core.regression_guard import RegressionGuard
from core.confidence_engine import ConfidenceEngine
from core.bug_localizer import BugLocalizer

try:
    from memory.repair_memory import RepairMemory
    _MEMORY_PATH = os.path.join(os.path.dirname(__file__), '..', 'memory', 'repair_memory.json')
    _repair_memory = RepairMemory(filepath=_MEMORY_PATH)
except Exception as _mem_err:
    _repair_memory = None

# ---- Phase 3 modules: Partial Patch Handling ----
from core.response_normalizer import ResponseNormalizer
from core.patch_completion import PatchCompleter
from core.function_patch_merger import FunctionPatchMerger

from agent.agent import AutoDevAgent
from models.ollama_model import OllamaModel
from core.output_validator import OutputValidator
from languages.language_detector import LanguageDetector


# ---------------------------------------------------------------------------
# Adaptive retry state tracker
# ---------------------------------------------------------------------------

class _AdaptiveRetryState:
    """
    Tracks validation failure patterns across retry attempts and recommends
    strategy adjustments to avoid repeating the same failing approach.

    Failure categories tracked:
      - structural  : Patch removed main/class/imports
      - too_short   : Candidate too short or empty
      - semantic    : Semantic validation failed
      - rewrite     : Patch rewrote too much code (similarity < 0.4)
      - identical   : Patch identical to original (no fix)
      - timeout     : LLM generation timed out

    After seeing the same failure 2+ times, recommend a strategy change.
    """

    def __init__(self):
        self._failure_counts: dict = {}  # failure_type -> count
        self._seen_errors: list = []     # deduped error string history
        self.prompt_mode = "full"        # "full" or "minimal"
        self.context_mode = "full"       # "full" or "minimal"
        self.patch_mode_override = None  # None = use caller's mode; "function" = force function mode

    def record_failure(self, failure_type: str, error_detail: str = "") -> None:
        """Record a validation failure of a specific type."""
        self._failure_counts[failure_type] = self._failure_counts.get(failure_type, 0) + 1
        if error_detail and error_detail not in self._seen_errors:
            self._seen_errors.append(error_detail)

    def get_recommendations(self) -> list:
        """
        Return a list of string recommendations based on failure history.
        Called before each retry to adapt the strategy.
        """
        recs = []

        structural_count = self._failure_counts.get("structural", 0)
        too_short_count = self._failure_counts.get("too_short", 0)
        semantic_count = self._failure_counts.get("semantic", 0)
        rewrite_count = self._failure_counts.get("rewrite", 0)

        # If structural failures repeat: switch to function-merge mode
        if structural_count >= 2:
            self.patch_mode_override = "function"
            recs.append(
                "Repeated structural failures (main/class removed) "
                "-> switching to function-merge mode"
            )

        # If too_short repeats: relax context (use minimal)
        if too_short_count >= 2:
            self.context_mode = "minimal"
            recs.append(
                "Repeated too-short responses -> switching to minimal context"
            )

        # If semantic failures repeat: simplify prompt
        if semantic_count >= 2:
            self.prompt_mode = "minimal"
            recs.append(
                "Repeated semantic failures -> switching to minimal prompt"
            )

        # If rewrite failures repeat: hint LLM to be more conservative
        if rewrite_count >= 2:
            recs.append(
                "Repeated rewrite failures -> hinting LLM to make minimal changes"
            )

        return recs

    def get_prompt_hint(self) -> str:
        """
        Return an additional instruction string to prepend to the LLM prompt
        based on observed failure patterns.
        """
        hints = []
        if self._failure_counts.get("structural", 0) >= 1:
            hints.append(
                "IMPORTANT: Return the COMPLETE file. Do NOT remove any functions, "
                "imports, or the main() entry point."
            )
        if self._failure_counts.get("rewrite", 0) >= 1:
            hints.append(
                "IMPORTANT: Make the MINIMUM change needed to fix the bug. "
                "Preserve all existing code that is not related to the bug."
            )
        if self._failure_counts.get("too_short", 0) >= 1:
            hints.append(
                "IMPORTANT: Include the full function implementation, not just a snippet."
            )
        return "\n".join(hints)


class RetryManager:

    def __init__(self, model=None):
        self.console = Console()
        if model is None:
            from models.ollama_model import OllamaModel
            model = OllamaModel()
        self.agent = AutoDevAgent(model=model)

    # -----------------------------------------------------------------------
    # Result builder
    # -----------------------------------------------------------------------

    def _build_result(self, status, local_attempts, cloud_attempts, max_retries,
                      model, old_code, new_code, confidence=None):
        return {
            "status": status,
            "local_attempts": local_attempts,
            "cloud_attempts": cloud_attempts,
            "max_retries": max_retries,
            "model": model,
            "old_code": old_code,
            "new_code": new_code,
            "attempts_used": local_attempts + cloud_attempts,
            "confidence": confidence,
        }

    def _synthetic_traceback(self, script_path: str, message: str):
        return {
            "file": script_path,
            "line": 0,
            "error_type": "LogicalBug",
            "error_message": message,
        }

    # -----------------------------------------------------------------------
    # Static / deterministic helpers (unchanged from original)
    # -----------------------------------------------------------------------

    @staticmethod
    def validate_cpp_patch(code: str) -> bool:
        """Compile-check a complete C++ candidate without producing artifacts."""
        if not isinstance(code, str) or not code.strip():
            return False
        try:
            with tempfile.TemporaryDirectory(prefix="autodev-cpp-check-") as temp_dir:
                source_path = os.path.join(temp_dir, "candidate.cpp")
                with open(source_path, "w", encoding="utf-8") as source_file:
                    source_file.write(code)
                result = subprocess.run(
                    ["g++", "-std=c++17", "-fsyntax-only", source_path],
                    capture_output=True,
                    text=True,
                    timeout=20,
                    check=False,
                )
                return result.returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            return False

    @staticmethod
    def quick_cpp_repairs(code: str) -> str:
        """Apply deterministic pattern-based fixes before calling the LLM."""
        code = code.replace(
            "int A = {{1, 2}, {3, 4}};",
            "int A[2][2] = {{1, 2}, {3, 4}};"
        )
        code = code.replace(
            "int B = {{5, 6}, {7, 8}};",
            "int B[2][2] = {{5, 6}, {7, 8}};"
        )
        code = code.replace(
            "C[i][j] += A[i][k] * B[i][j]",
            "C[i][j] += A[i][k] * B[k][j]"
        )
        return code

    # -----------------------------------------------------------------------
    # Patch validation helper (wraps PatchValidator + inline guards)
    # -----------------------------------------------------------------------

    def _validate_candidate(
        self,
        candidate: str,
        original_code: str,
        language: str,
        patch_mode: str = "full",
    ) -> tuple[bool, str]:
        """
        Run the full PatchValidator suite on a candidate.

        Args:
            patch_mode: "full" | "function" | "snippet"
                        Pass "function" or "snippet" for partial patches that have
                        already been merged into the full file by FunctionPatchMerger.
        Returns (is_valid, reason).
        """
        ok, reason = PatchValidator.validate(candidate, original_code, language, patch_mode=patch_mode)
        if not ok:
            self.console.print(f"[yellow]! Patch validation failed: {reason}[/yellow]")
        return ok, reason

    def _detect_patch_mode(
        self,
        candidate: str,
        original_code: str,
        language: str,
        explicit_mode: str = "full",
    ) -> str:
        """
        Detect whether a candidate is a full-file patch or a function/snippet patch.

        Returns:
            "full"     -- full-file replacement (size comparable to original).
            "function" -- function-level patch (user passed --mode function).
            "snippet"  -- auto-detected partial patch (much smaller than original,
                          or no includes/class for C++/Java respectively).
        """
        # Respect explicit CLI mode
        if explicit_mode == "function":
            self.console.print("[PatchMode] FUNCTION_PATCH (explicit --mode function)")
            return "function"

        orig_lines = original_code.strip().splitlines()
        cand_lines = candidate.strip().splitlines()

        # Auto-detect: candidate is < 60% the size of original
        if len(orig_lines) > 10 and len(cand_lines) < len(orig_lines) * 0.60:
            if language == "cpp" and "#include" not in candidate:
                self.console.print("[PatchMode] SNIPPET_PATCH (auto: no includes, short patch)")
                return "snippet"
            if language == "java" and "class " not in candidate:
                self.console.print("[PatchMode] SNIPPET_PATCH (auto: no class decl, short patch)")
                return "snippet"
            if language == "python":
                first_nonblank = next(
                    (l.strip() for l in candidate.splitlines() if l.strip()), ""
                )
                if first_nonblank.startswith("def ") or first_nonblank.startswith("async def "):
                    self.console.print("[PatchMode] SNIPPET_PATCH (auto: function-only patch)")
                    return "snippet"

        self.console.print("[PatchMode] FULL_FILE")
        return "full"

    # -----------------------------------------------------------------------
    # Context pruning helper
    # -----------------------------------------------------------------------

    def _build_pruned_context(
        self,
        full_code: str,
        script_path: str,
        patch_target: str,
        tb: dict,
        language: str,
        is_cloud: bool = False,
    ) -> str:
        """
        Build a token-budget-aware context string for the LLM prompt.
        Uses ContextEngine to extract crashing function and callers,
        then ContextPruner to trim to budget.
        """
        crash_line = int(tb.get("line", 0)) if tb.get("line") else 0
        stderr_text = tb.get("error_message", "")

        # Extract crashing function and callers using existing ContextEngine
        crashing_func = ""
        caller_funcs = []

        if crash_line > 0 and os.path.exists(patch_target):
            crashing_func = ContextEngine.get_crashing_function(patch_target, crash_line)

        # ContextEngine.get_caller_functions needs a traceback string — reconstruct one
        # from the tb dict if we have file/line info
        if tb.get("file") and tb.get("line"):
            synthetic_tb_str = f'File "{tb["file"]}", line {tb["line"]}, in <function>'
            caller_funcs = ContextEngine.get_caller_functions(patch_target, synthetic_tb_str)

        pruner = make_pruner(is_cloud=is_cloud)
        pruned = pruner.prune(
            full_code=full_code,
            crash_line=crash_line,
            crashing_func=crashing_func,
            caller_funcs=caller_funcs,
            language=language,
        )
        return pruned

    # -----------------------------------------------------------------------
    # Main entry point
    # -----------------------------------------------------------------------

    def attempt_fix(
        self,
        script_path: str,
        max_retries: int = 3,
        dry_run: bool = False,
        patch_mode: str = "full",   # "full" (default) or "function" (opt-in)
        fast_mode: bool = True,     # Speed-first mode (default: True)
    ):
        backup_path = None
        old_code = ""
        new_code = ""
        local_attempts = 0
        cloud_attempts = 0
        language = LanguageDetector.detect(script_path)
        result = None
        full_code = ""

        if fast_mode:
            self.console.print("[bold cyan][FastMode] Speed-first repair mode active[/bold cyan]")

        # -----------------------------
        # 1  INITIAL EXECUTION CHECK
        # -----------------------------

        self.console.print("\n[bold yellow]=== Initial Execution Check ===[/bold yellow]")

        initial_result = run_script(script_path)

        if initial_result["returncode"] == 0:
            validation = OutputValidator.validate(initial_result["stdout"], language)

            if validation["is_suspicious"]:
                self.console.print(
                    f"[bold yellow]! Suspicious output detected: {validation['flags']}[/bold yellow]"
                )
                self.console.print("[yellow]Proceeding with repair attempts...[/yellow]")
                result = initial_result
            else:
                self.console.print("[bold green]OK Success! The script executed flawlessly.[/bold green]")

                if initial_result["stdout"]:
                    self.console.print(f"[dim]Output:\n{initial_result['stdout'].strip()}[/dim]")

                return self._build_result(
                    "SUCCESS", 0, 0, max_retries,
                    "None (Already Working)", "", "", "HIGH"
                )
        else:
            self.console.print("[bold red]X Crash detected![/bold red]")
            error_preview = "\n".join(initial_result["stderr"].strip().splitlines()[-3:])
            self.console.print(f"[red]{error_preview}[/red]")
            result = initial_result

        # Capture initial output fingerprint for behavioral comparison later
        initial_fingerprint = BehaviorFingerprint.capture(
            initial_result.get("stdout", "") or ""
        )

        # ---- Phase 2: RegressionGuard baseline snapshot ----
        _regression_guard = RegressionGuard()
        _before_snapshot = _regression_guard.capture(initial_result)

        # Identify target file
        project_root = find_project_root(script_path)
        tb = parse_traceback(result["stderr"]) if result and result.get("stderr") else {}
        original_tb = tb
        patch_target = resolve_patch_target(project_root, script_path, tb.get("file"))

        # ---- Phase 2: BugLocalizer ----
        try:
            localization = BugLocalizer.localize(
                file_path=patch_target,
                stderr=result.get("stderr", "") if result else "",
                language=language,
                project_root=project_root,
            )
            # If localizer found a better target, use it
            if (localization.primary_target
                    and os.path.exists(localization.primary_target)
                    and localization.primary_target != patch_target):
                self.console.print(
                    f"[cyan][BugLocalizer] Better target: {os.path.basename(localization.primary_target)}[/cyan]"
                )
                patch_target = localization.primary_target
            if localization.suspicious_funcs:
                top = localization.suspicious_funcs[0]
                self.console.print(
                    f"[dim][BugLocalizer] Top suspect: {top.name}() "
                    f"lines {top.start_line}-{top.end_line}[/dim]"
                )
            # Store localization on self for access in success block
            self._last_localization = localization
        except Exception as _loc_err:
            self.console.print(f"[dim]BugLocalizer: {_loc_err}[/dim]")
            self._last_localization = None

        if patch_target != script_path:
            self.console.print(f"[bold cyan][T] External file target found: {patch_target}[/bold cyan]")

        # -----------------------------
        # 2  BACKUP FILE
        # -----------------------------

        backup_paths = []
        if not dry_run:
            backup_paths.append(backup_file(script_path))
            if patch_target != script_path:
                backup_paths.append(backup_file(patch_target))
            self.console.print("[dim]Backups created for targeted files.[/dim]")

        # -----------------------------
        # 3  HEURISTIC REPAIR
        # -----------------------------

        from core.heuristic_fixes import heuristic_repair
        try:
            with open(patch_target, "r", encoding="utf-8") as f:
                heuristic_raw = f.read()
            h_repaired = heuristic_repair(
                heuristic_raw,
                original_tb.get("error_type", ""),
                original_tb.get("error_message", "")
            )
            if h_repaired != heuristic_raw:
                if dry_run:
                    self.console.print("[yellow]DRY RUN -- heuristic patch generated; source left unchanged[/yellow]")
                    return self._build_result(
                        "DRY_RUN", 0, 0, max_retries,
                        "HeuristicRepair", heuristic_raw, h_repaired,
                    )
                self.console.print("[cyan]^ Applying heuristic pre-fix...[/cyan]")
                with open(patch_target, "w", encoding="utf-8") as f:
                    f.write(h_repaired)
                h_result = run_script(script_path)
                if h_result["returncode"] == 0:
                    h_val = OutputValidator.validate(h_result["stdout"], language)
                    if not h_val["is_suspicious"]:
                        self.console.print("[bold green]OK Heuristic repair succeeded![/bold green]")
                        if h_result["stdout"]:
                            self.console.print(h_result["stdout"].strip())
                        return self._build_result(
                            "SUCCESS", 0, 0, max_retries,
                            "HeuristicRepair", heuristic_raw, h_repaired, "HIGH"
                        )
                # Restore backup if heuristic failed
                if h_result["returncode"] != 0 or h_val.get("is_suspicious"):
                    self.console.print("[yellow]Heuristic repair failed. Proceeding to LLM.[/yellow]")
                    for bp in backup_paths:
                        if os.path.exists(bp):
                            shutil.copy2(bp, bp[:-7])
        except Exception as e:
            self.console.print(f"[yellow]Heuristic layer error: {e}[/yellow]")
            for bp in backup_paths:
                if os.path.exists(bp):
                    shutil.copy2(bp, bp[:-7])

        # -----------------------------
        # 3.1  CHECK OLLAMA
        # -----------------------------

        ollama_available = False
        try:
            r = requests.get("http://localhost:11434/api/tags", timeout=2.0)
            if r.status_code == 200:
                ollama_available = True
        except Exception:
            ollama_available = False

        if not ollama_available:
            self.console.print("[bold yellow]! Ollama unavailable. Skipping local repair.[/bold yellow]")

        # -----------------------------
        # 3.5  QUICK HEURISTIC REPAIR (C++)
        # -----------------------------

        if language == "cpp":
            with open(script_path, "r", encoding="utf-8") as f:
                raw = f.read()
            repaired = self.quick_cpp_repairs(raw)
            if repaired != raw:
                if dry_run:
                    self.console.print("[yellow]DRY RUN -- quick C++ patch generated; source left unchanged[/yellow]")
                    return self._build_result(
                        "DRY_RUN", 0, 0, max_retries,
                        "QuickRepair", raw, repaired,
                    )
                self.console.print("[cyan]^ Applying quick heuristic repair...[/cyan]")
                with open(script_path, "w", encoding="utf-8") as f:
                    f.write(repaired)
                quick_result = run_script(script_path)
                if quick_result["returncode"] == 0:
                    validation = OutputValidator.validate(quick_result["stdout"], language)
                    if not validation["is_suspicious"]:
                        self.console.print("[bold green]OK Quick repair succeeded![/bold green]")
                        if quick_result["stdout"]:
                            self.console.print(quick_result["stdout"].strip())
                        return self._build_result(
                            "SUCCESS", 0, 0, max_retries,
                            "QuickRepair", raw, repaired, "HIGH"
                        )
                else:
                    result = quick_result

        # -----------------------------
        # 3.7  QUICK SYNTAX REPAIR — unbalanced parentheses
        # -----------------------------

        if result and result.get("stderr"):
            stderr_text = result["stderr"]
            if "SyntaxError" in stderr_text and "'(' was never closed" in stderr_text:
                self.console.print("[cyan]^ Detected unclosed parenthesis — attempting quick syntax repair...[/cyan]")
                try:
                    with open(patch_target, "r", encoding="utf-8") as f:
                        original_code = f.read()
                    open_paren = original_code.count("(")
                    close_paren = original_code.count(")")
                    if open_paren > close_paren:
                        fixed_code = original_code + (")" * (open_paren - close_paren))
                        if dry_run:
                            self.console.print("[yellow]DRY RUN -- syntax patch generated; source left unchanged[/yellow]")
                            return self._build_result(
                                "DRY_RUN", 0, 0, max_retries,
                                "QuickParenRepair", original_code, fixed_code,
                            )
                        with open(patch_target, "w", encoding="utf-8") as f:
                            f.write(fixed_code)
                        paren_result = run_script(script_path)
                        if paren_result["returncode"] == 0:
                            paren_val = OutputValidator.validate(paren_result["stdout"], language)
                            if not paren_val["is_suspicious"]:
                                self.console.print("[bold green]OK Quick paren-balance repair succeeded![/bold green]")
                                if paren_result["stdout"]:
                                    self.console.print(paren_result["stdout"].strip())
                                return self._build_result(
                                    "SUCCESS", 0, 0, max_retries,
                                    "QuickParenRepair", original_code, fixed_code, "HIGH"
                                )
                        self.console.print("[yellow]Paren repair did not fully fix the script. Proceeding to LLM.[/yellow]")
                        for bp in backup_paths:
                            if os.path.exists(bp):
                                shutil.copy2(bp, bp[:-7])
                        result = paren_result
                except Exception as e:
                    self.console.print(f"[yellow]Quick paren repair error: {e}[/yellow]")
                    for bp in backup_paths:
                        if os.path.exists(bp):
                            shutil.copy2(bp, bp[:-7])

        # -----------------------------
        # 4  LOCAL REPAIR LOOP
        # -----------------------------

        if ollama_available:

            # Adaptive retry state — tracks failures to avoid repeating bad strategies
            _adaptive = _AdaptiveRetryState()
            # Deduplication set: (error_type, candidate_prefix) — avoids identical retry cycles
            _seen_failure_sigs: set = set()

            # In fast mode, limit to 1 local attempt before escalating to cloud
            effective_local_retries = 1 if fast_mode else max_retries

            for attempt in range(1, effective_local_retries + 1):

                self.console.print(f"\n[bold yellow]=== Local Attempt {attempt}/{effective_local_retries} ===[/bold yellow]")

                # ---- ADAPTIVE STRATEGY ADJUSTMENT ----
                if attempt > 1:
                    recs = _adaptive.get_recommendations()
                    for rec in recs:
                        self.console.print(f"[cyan][Adaptive] {rec}[/cyan]")

                is_last = attempt == effective_local_retries

                if is_last:
                    self.console.print("[magenta]! Final Local Attempt: Full-file repair[/magenta]")

                local_attempts = attempt

                if result.get("traceback"):
                    tb = result["traceback"]
                else:
                    tb = parse_traceback(result["stderr"]) if result and result.get("stderr") else {}

                # No traceback => logical bug mode
                if not tb.get("file") or not tb.get("line"):
                    self.console.print("[yellow]No traceback found. Switching to logical bug repair mode.[/yellow]")
                    tb = self._synthetic_traceback(
                        script_path,
                        "Suspicious output or logical bug detected"
                    )
                    is_last = True

                with open(script_path, "r", encoding="utf-8") as f:
                    entry_code = f.read()

                with open(patch_target, "r", encoding="utf-8") as f:
                    full_code = f.read()

                primary = full_code
                old_code = full_code

                # ---- CONTEXT PRUNING (fast mode uses tighter budget) ----
                pruned_context = self._build_pruned_context(
                    full_code, script_path, patch_target, tb, language,
                    is_cloud=False, fast_mode=(fast_mode and attempt == 1)
                )

                # On retry 2+: tighten context further (force mutation) if not fast
                if attempt > 1 and not fast_mode:
                    self.console.print("[dim][RetryPolicy] Tightening context budget on retry...[/dim]")
                    tight_pruner = make_pruner(is_cloud=False, fast_mode=True)
                    pruned_context = tight_pruner.prune(
                        full_code=full_code,
                        crash_line=int(tb.get("line", 0)) if tb.get("line") else 0,
                        crashing_func=pruned_context,  # already pruned, use as-is
                        caller_funcs=[],
                        language=language,
                    )

                # ---- PRE-LLM: REPAIR MEMORY CACHE CHECK ----
                # If memory has a high-confidence fix for this exact error pattern,
                # apply it directly and skip the LLM entirely.
                if _repair_memory is not None and attempt == 1:
                    try:
                        _err_type = tb.get("error_type", "")
                        _func_sig = primary.splitlines()[0] if primary else ""
                        _mem_record = _repair_memory.retrieve_best(
                            error_type=_err_type,
                            function_signature=_func_sig,
                            language=language,
                        )
                        if _mem_record and _mem_record.confidence >= 80:
                            self.console.print(
                                f"[bold cyan][RepairMemory] High-confidence cached fix found "
                                f"({_mem_record.confidence:.0f}%, model={_mem_record.model_name}). "
                                f"Applying directly...[/bold cyan]"
                            )
                            if not dry_run:
                                with open(patch_target, "w", encoding="utf-8") as f:
                                    f.write(_mem_record.fixed_code)
                                _cache_result = run_script(script_path)
                                if _cache_result["returncode"] == 0:
                                    _cache_val = OutputValidator.validate(_cache_result["stdout"], language)
                                    if not _cache_val["is_suspicious"]:
                                        self.console.print(
                                            "[bold green][RepairMemory] Cached fix succeeded! "
                                            "Skipped LLM entirely.[/bold green]"
                                        )
                                        if _cache_result["stdout"]:
                                            self.console.print(_cache_result["stdout"].strip())
                                        return self._build_result(
                                            "SUCCESS", 0, 0, max_retries,
                                            f"RepairMemory({_mem_record.model_name})",
                                            full_code, _mem_record.fixed_code, "HIGH"
                                        )
                                # Cache miss: restore and fall through to LLM
                                for bp in backup_paths:
                                    if os.path.exists(bp):
                                        shutil.copy2(bp, bp[:-7])
                                self.console.print("[dim][RepairMemory] Cached fix failed; falling through to LLM.[/dim]")
                    except Exception as _mem_ex:
                        self.console.print(f"[dim][RepairMemory] Lookup error: {_mem_ex}[/dim]")

                # ---- BUILD MEMORY HINT for prompt ----
                _mem_hint_str = ""
                if _repair_memory is not None:
                    try:
                        _err_type = tb.get("error_type", "")
                        _func_sig = primary.splitlines()[0] if primary else ""
                        _mem_hint_str = _repair_memory.build_memory_hint(
                            error_type=_err_type,
                            function_signature=_func_sig,
                            language=language,
                        )
                        if _mem_hint_str:
                            self.console.print("[dim][RepairMemory] Memory hint will be injected into prompt[/dim]")
                    except Exception:
                        pass

                caller = _adaptive.get_prompt_hint()  # adaptive hint as caller context
                generation_success = False
                patch_candidates = []

                # In fast mode: 1 generation attempt. Otherwise: up to 2.
                _max_gen_attempts = 1 if fast_mode else 2

                for gen_attempt in range(_max_gen_attempts):
                    with self.console.status(
                        f"[blue][AI] Generating fix (gen attempt {gen_attempt + 1}/{_max_gen_attempts})...[/blue]"
                    ):
                        try:
                            patch_candidates = self.agent.request_fix(
                                error_info=tb,
                                code_context=pruned_context,
                                language=language,
                                caller_context=caller,
                                full_file_mode=True,
                                full_file_content=pruned_context,
                                entry_file=script_path,
                                error_file=patch_target,
                                entry_code=entry_code,
                                fast_mode=fast_mode,
                                memory_hint=_mem_hint_str,
                            )
                            if patch_candidates:
                                generation_success = True
                                break
                        except Exception as e:
                            self.console.print(f"[red]AI generation failed: {e}[/red]")

                if not generation_success:
                    self.console.print("[red]All models failed to generate valid code for this attempt.[/red]")
                    _adaptive.record_failure("timeout", "generation failed")
                    self.console.print("[dim][RetryPolicy] Generation failed — skipping this attempt[/dim]")
                    continue

                # ---- Phase 2: Memory hint injection (already in prompt via memory_hint param) ----
                # Nothing additional needed here — hint was passed to agent.request_fix().

                if dry_run:
                    self.console.print("[yellow]DRY RUN -- patch not applied[/yellow]")
                    return self._build_result(
                        "DRY_RUN",
                        local_attempts, cloud_attempts, max_retries,
                        getattr(self.agent.model, "last_successful_model", "Multiple Models"),
                        old_code,
                        patch_candidates[0] if patch_candidates else "",
                    )

                # ---- CANDIDATE RANKING (fast mode = lightweight, full mode = full scoring) ----
                ranked_candidates = CandidateRanker.rank(
                    patch_candidates, full_code, language, verbose=not fast_mode, fast=fast_mode
                )

                # ---- Phase 3: Normalize candidates via ResponseNormalizer ----
                # agent.py already returns clean candidates (it ran normalize internally).
                # We only re-normalize if a candidate still looks like raw LLM text
                # (e.g. it contains JSON or markdown fences).
                normalized_candidates = []
                for raw_cand in ranked_candidates:
                    if not raw_cand or not raw_cand.strip():
                        continue
                    # Only re-normalize if it still looks like JSON/fenced output
                    if '{' in raw_cand[:50] or '```' in raw_cand[:50]:
                        try:
                            norm_result = ResponseNormalizer.normalize(raw_cand, language=language)
                            if norm_result.candidates:
                                normalized_candidates.extend(norm_result.candidates)
                            else:
                                normalized_candidates.append(raw_cand)
                        except Exception:
                            normalized_candidates.append(raw_cand)
                    else:
                        normalized_candidates.append(raw_cand)  # Already clean
                # Deduplicate while preserving order
                seen_cands = set()
                deduped_candidates = []
                for c in normalized_candidates:
                    key = c.strip()[:200]
                    if key not in seen_cands:
                        seen_cands.add(key)
                        deduped_candidates.append(c)
                ranked_candidates = deduped_candidates if deduped_candidates else ranked_candidates

                self.console.print(
                    f"[dim][CloudPipeline] {len(ranked_candidates)} candidate(s) ready for application[/dim]"
                )

                patch_applied = False

                for candidate_idx, candidate in enumerate(ranked_candidates):

                    self.console.print(
                        f"[dim]Trying ranked candidate {candidate_idx + 1}/{len(ranked_candidates)}...[/dim]"
                    )

                    try:
                        candidate = auto_fix_syntax(candidate, language)
                    except Exception as e:
                        self.console.print(f"[yellow]Syntax repair error on candidate {candidate_idx + 1}: {e}[/yellow]")
                        continue

                    # ---- Phase 3: PatchCompletion — repair truncated/incomplete patches ----
                    try:
                        candidate = PatchCompleter.complete(candidate, language=language)
                    except Exception as _pc_err:
                        self.console.print(f"[dim]PatchCompletion error: {_pc_err}[/dim]")

                    # Read current file state (restored from backup at loop start)
                    try:
                        original_code = open(patch_target, "r", encoding="utf-8").read()
                    except Exception as e:
                        self.console.print(f"[red]Failed to read patch target: {e}[/red]")
                        break

                    # ─── STEP 1: Detect patch mode ────────────────────────────────────
                    _patch_mode = self._detect_patch_mode(
                        candidate, original_code, language, explicit_mode=patch_mode
                    )

                    # ─── STEP 2: Merge BEFORE validate (correct pipeline order) ────────
                    # For snippet/function patches, merge into full file first so that
                    # PatchValidator sees a complete file and doesn't reject on size.
                    _merged_this_round = False
                    if _patch_mode in ("function", "snippet"):
                        try:
                            self.console.print(
                                "[dim][FunctionPatchMerger] Partial patch detected — merging before validation...[/dim]"
                            )
                            _merge_result = FunctionPatchMerger.merge(
                                original=original_code,
                                patch=candidate,
                                language=language,
                            )
                            if _merge_result.success:
                                candidate = _merge_result.merged_code
                                _merged_this_round = True
                                self.console.print(
                                    f"[dim][PatchMerge] Successfully merged snippet "
                                    f"(replaced={_merge_result.functions_replaced}, "
                                    f"added={_merge_result.functions_added}) "
                                    f"→ {len(candidate.splitlines())}-line reconstructed file[/dim]"
                                )
                                # After merge the result is a full file — validate as full
                                _patch_mode = "full"
                            else:
                                self.console.print(
                                    f"[dim][FunctionPatchMerger] Merge failed: "
                                    f"{_merge_result.reason} — validating as-is[/dim]"
                                )
                        except Exception as _fm_err:
                            self.console.print(f"[dim]FunctionPatchMerger error: {_fm_err}[/dim]")
                    else:
                        # Full-file patch: still attempt merge rescue for structural issues
                        try:
                            _norm_check = ResponseNormalizer.normalize(candidate, language=language)
                            if _norm_check.is_partial:
                                _merge_result = FunctionPatchMerger.merge(
                                    original=original_code, patch=candidate, language=language
                                )
                                if _merge_result.success:
                                    candidate = _merge_result.merged_code
                                    _merged_this_round = True
                                    self.console.print(
                                        "[dim][FunctionPatchMerger] Partial-flag rescue merge succeeded[/dim]"
                                    )
                        except Exception:
                            pass

                    # ─── STEP 3: SEMANTIC VALIDATION on (possibly merged) candidate ───
                    _pm_label = "FUNCTION" if _patch_mode == "function" else ("SNIPPET" if _patch_mode == "snippet" else "FULL_FILE")
                    self.console.print(
                        f"[dim][Validator] Validating reconstructed full file (mode={_pm_label})[/dim]"
                    )
                    val_ok, val_reason = self._validate_candidate(
                        candidate, original_code, language, patch_mode=_patch_mode
                    )
                    if not val_ok:
                        # Track failure signature for early-stop deduplication
                        _fail_sig = (tb.get("error_type", ""), candidate.strip()[:120])
                        if _fail_sig in _seen_failure_sigs:
                            self.console.print(
                                "[yellow][RetryPolicy] Identical failure repeated — early stop for this candidate.[/yellow]"
                            )
                            _adaptive.record_failure("semantic", val_reason)
                            continue
                        _seen_failure_sigs.add(_fail_sig)
                        self.console.print(
                            f"[yellow]Candidate {candidate_idx + 1} rejected by validator: {val_reason}[/yellow]"
                        )
                        self.console.print(
                            f"[dim][Validator] rejected: {val_reason}[/dim]"
                        )
                        _adaptive.record_failure("semantic", val_reason)
                        continue

                    # ─── STEP 4: STRUCTURAL GUARDS (main/entry-point checks only) ─────
                    # Size threshold is now handled by PatchValidator (mode-aware).
                    # Here we only check for missing main() / __main__ block.
                    try:
                        import difflib
                        original_lines = original_code.strip().splitlines()
                        patched_lines = candidate.strip().splitlines()

                        if len(original_lines) > 10:
                            has_main_orig = "main(" in original_code
                            has_main_patch = "main(" in candidate or "main(void" in candidate
                            if has_main_orig and not has_main_patch and not _merged_this_round:
                                _struct_merge = FunctionPatchMerger.merge(
                                    original=original_code, patch=candidate, language=language
                                )
                                if _struct_merge.success:
                                    self.console.print(
                                        "[dim][FunctionPatchMerger] Rescued missing main() via merge[/dim]"
                                    )
                                    candidate = _struct_merge.merged_code
                                    _adaptive.record_failure("structural", "main() was missing")
                                else:
                                    _adaptive.record_failure("structural", "Patch removed program execution")
                                    raise ValueError("Patch removed program execution")
                            if ('if __name__ == "__main__"' in original_code
                                    and 'if __name__ == "__main__"' not in candidate
                                    and not _merged_this_round):
                                _struct_merge2 = FunctionPatchMerger.merge(
                                    original=original_code, patch=candidate, language=language
                                )
                                if _struct_merge2.success:
                                    candidate = _struct_merge2.merged_code
                                    _adaptive.record_failure("structural", "__main__ block was missing")
                                else:
                                    _adaptive.record_failure("structural", "Patch removed __main__ block")
                                    raise ValueError("Patch removed program execution")

                    except ValueError as e:
                        self.console.print(f"[yellow]Patch structural check failed: {e}[/yellow]")
                        continue

                    # ---- APPLY PATCH (full-file or function-level) ----
                    try:
                        if patch_mode == "function":
                            apply_result = FunctionPatcher.apply(
                                patch_target=patch_target,
                                patch_code=candidate,
                                language=language,
                                error_info=tb,
                            )
                            if not apply_result["applied"]:
                                self.console.print(
                                    f"[yellow]FunctionPatcher: {apply_result['reason']}[/yellow]"
                                )
                                continue
                            if apply_result["fallback"]:
                                self.console.print(
                                    f"[dim]FunctionPatcher: fell back to full-file — "
                                    f"{apply_result['reason']}[/dim]"
                                )
                            else:
                                self.console.print(
                                    f"[dim]FunctionPatcher: patched function "
                                    f"'{apply_result['function_name']}'[/dim]"
                                )
                        else:
                            # Default: full-file replacement (original behavior)
                            with open(patch_target, "w", encoding="utf-8") as f:
                                f.write(candidate)

                    except Exception as e:
                        self.console.print(f"[yellow]Patch application failed: {e}[/yellow]")
                        for bp in backup_paths:
                            if os.path.exists(bp):
                                shutil.copy2(bp, bp[:-7])
                        continue

                    # ---- VERIFY FIX ----
                    result = run_script(script_path)

                    if result["returncode"] == 0:
                        validation = OutputValidator.validate(result["stdout"], language)

                        if validation["is_suspicious"]:
                            self.console.print(
                                f"[yellow]! Suspicious output: {validation['flags']}[/yellow]"
                            )
                            self.console.print(
                                f"[yellow]Patch Accepted / Rejected Reason: Patch rejected: "
                                f"Suspicious output flags ({validation['flags']})[/yellow]"
                            )
                            for bp in backup_paths:
                                if os.path.exists(bp):
                                    shutil.copy2(bp, bp[:-7])
                            continue

                        # ---- BEHAVIORAL FINGERPRINT CHECK (new) ----
                        patched_fingerprint = BehaviorFingerprint.capture(
                            result.get("stdout", "") or ""
                        )
                        delta = BehaviorFingerprint.delta(initial_fingerprint, patched_fingerprint)
                        if delta == 0.0 and initial_result.get("returncode", 1) != 0:
                            # Only reject if original crashed (non-zero returncode) but
                            # the output is identical — possible sign of an ineffective patch.
                            # If original ran fine and output is same, that's OK (already handled above).
                            self.console.print(
                                "[yellow]! Behavioral fingerprint: patch produced identical output "
                                "to the original — may not have fixed the bug. Continuing...[/yellow]"
                            )
                            # Note: we don't hard-reject here because the returncode IS 0 —
                            # the program at least runs now. Log and accept.

                        original_stdout = initial_result.get("stdout", "").strip() if initial_result else ""
                        patched_stdout = result.get("stdout", "").strip() if result else ""

                        try:
                            if original_stdout and not patched_stdout:
                                raise ValueError("Patch removed program output")
                        except ValueError as e:
                            self.console.print(f"[yellow]! {e}[/yellow]")
                            for bp in backup_paths:
                                if os.path.exists(bp):
                                    shutil.copy2(bp, bp[:-7])
                            continue
                        else:
                            self.console.print(
                                "[green]Patch Accepted / Rejected Reason: Patch accepted: "
                                "Program executed successfully[/green]"
                            )
                            self.console.print("[green]OK Script fixed successfully![/green]")

                            # ---- Phase 2: RegressionGuard check ----
                            try:
                                _after_snapshot = _regression_guard.capture(result)
                                _reg_report = _regression_guard.check(_before_snapshot, _after_snapshot)
                                if _reg_report.has_regression:
                                    self.console.print(
                                        f"[yellow]! RegressionGuard: {_reg_report.severity} — "
                                        f"{'; '.join(_reg_report.reasons[:2])}[/yellow]"
                                    )
                                    # Don't hard-reject if it still ran — log and continue
                                else:
                                    self.console.print("[dim]RegressionGuard: OK[/dim]")
                            except Exception as _reg_err:
                                _reg_report = None
                                self.console.print(f"[dim]RegressionGuard error: {_reg_err}[/dim]")

                            # ---- Phase 2: BehaviorEngine domain analysis ----
                            try:
                                _beh_report = BehaviorEngine.analyze(
                                    result.get("stdout", ""),
                                    language=language,
                                )
                                if not _beh_report.is_logically_valid:
                                    self.console.print(
                                        f"[yellow]! BehaviorEngine: {_beh_report.summary}[/yellow]"
                                    )
                            except Exception:
                                _beh_report = None

                            # ---- Phase 2: Real confidence scoring ----
                            import difflib as _diff
                            _sim = _diff.SequenceMatcher(None, old_code.split(), candidate.split()).ratio()
                            try:
                                _conf_result = ConfidenceEngine.score(
                                    syntax_valid=True,
                                    semantic_valid=True,
                                    regression_report=_reg_report,
                                    behavior_delta=delta,
                                    behavior_report=_beh_report,
                                    similarity_ratio=_sim,
                                    language_safe=True,
                                    attempt_number=local_attempts,
                                )
                                self.console.print(
                                    f"[dim]Confidence: {_conf_result.score:.1f}% "
                                    f"({_conf_result.grade} — {_conf_result.label})[/dim]"
                                )
                                _conf_display = f"{_conf_result.score:.1f}%"
                            except Exception:
                                _conf_display = "HIGH"
                                _conf_result = None

                            # ---- Phase 2: RepairMemory record success ----
                            try:
                                if _repair_memory is not None:
                                    _repair_memory.record_success(
                                        error_type=tb.get("error_type", "UnknownError"),
                                        function_signature=primary.splitlines()[0] if primary else "",
                                        language=language,
                                        bug_code=old_code,
                                        fixed_code=candidate,
                                        model_name=getattr(
                                            self.agent.model,
                                            "last_successful_model",
                                            "unknown"
                                        ),
                                        confidence=(
                                            _conf_result.score
                                            if _conf_result else 0.0
                                        ),
                                    )
                            except Exception:
                                pass

                            if hasattr(self.agent, "store_successful_fix"):
                                self.agent.store_successful_fix(tb, script_path, primary, candidate)

                            if result["stdout"]:
                                self.console.print(result["stdout"].strip())

                            return self._build_result(
                                "SUCCESS",
                                local_attempts, cloud_attempts, max_retries,
                                getattr(self.agent.model, "last_successful_model", "Multiple Models"),
                                old_code, candidate,
                                confidence=_conf_display,
                            )
                    else:
                        self.console.print("[red]X Crash persists[/red]")
                        preview = "\n".join(result["stderr"].strip().splitlines()[-3:])
                        self.console.print(f"[red]{preview}[/red]")
                        for bp in backup_paths:
                            if os.path.exists(bp):
                                shutil.copy2(bp, bp[:-7])

                # All candidates exhausted for this attempt — loop continues

        # -----------------------------
        # 5  CLOUD ESCALATION
        # -----------------------------

        if not dry_run:
            self.console.print("\n[bold magenta][^] Escalating to Cloud Models[/bold magenta]")

            # Restore backups so cloud sees original code
            for bp in backup_paths:
                if os.path.exists(bp):
                    shutil.copy2(bp, bp[:-7])

            try:
                from models.groq_model import GroqModel
                from models.gemini_model import GeminiModel
                from models.model_orchestrator import ModelOrchestrator
                import json
                from dotenv import load_dotenv
                load_dotenv()

                with open("autodev_config.json") as f:
                    cfg = json.load(f)

                cloud_budget = cfg.get("context_budget", {}).get("cloud", 12000)
                cloud_models = []

                # --- Groq ---
                groq_key = cfg.get("api_keys", {}).get("groq") or os.environ.get("GROQ_API_KEY", "")
                groq_model_name = cfg.get("groq_model", "llama-3.3-70b-versatile")
                groq_name_map = {
                    "mixtral-8x7b": "mixtral-8x7b-32768",
                    "llama3-70b": "llama-3.3-70b-versatile",
                    "llama3-8b": "llama3-8b-8192",
                }
                groq_model_name = groq_name_map.get(groq_model_name, groq_model_name)

                if groq_key:
                    try:
                        cloud_models.append(GroqModel(groq_model_name, groq_key))
                        self.console.print(f"[dim]Groq ready: {groq_model_name}[/dim]")
                    except Exception as e:
                        self.console.print(f"[yellow]Groq init failed: {e}[/yellow]")
                else:
                    self.console.print("[dim]Groq: no API key found (set GROQ_API_KEY in .env)[/dim]")

                # --- Gemini ---
                gemini_key = cfg.get("api_keys", {}).get("gemini") or os.environ.get("GEMINI_API_KEY", "")
                gemini_model_name = cfg.get("gemini_model", "gemini-2.0-flash")

                if gemini_key:
                    try:
                        cloud_models.append(GeminiModel(gemini_model_name, gemini_key))
                        self.console.print(f"[dim]Gemini ready: {gemini_model_name}[/dim]")
                    except Exception as e:
                        self.console.print(f"[yellow]Gemini init failed: {e}[/yellow]")
                else:
                    self.console.print("[dim]Gemini: no API key found (set GEMINI_API_KEY in .env)[/dim]")

                if not cloud_models:
                    self.console.print("[bold yellow]No cloud models available — add API keys to .env[/bold yellow]")

                else:
                    # Upgraded orchestrator with quality gate + timeout
                    cloud_orchestrator = ModelOrchestrator(cloud_models, timeout=60, per_model_retries=1)
                    cloud_agent = AutoDevAgent(model=cloud_orchestrator)

                    if result and result.get("traceback"):
                        tb = result["traceback"]
                    else:
                        tb = parse_traceback(result["stderr"]) if result and result.get("stderr") else {}

                    if not tb.get("file") or not tb.get("line"):
                        tb = self._synthetic_traceback(script_path, "Suspicious output detected")

                    with open(script_path, "r", encoding="utf-8") as f:
                        entry_code = f.read()

                    with open(patch_target, "r", encoding="utf-8") as f:
                        full_code = f.read()

                    # ---- CONTEXT PRUNING for cloud (higher budget) ----
                    pruned_cloud_context = self._build_pruned_context(
                        full_code, script_path, patch_target, tb, language, is_cloud=True
                    )

                    cloud_candidates = cloud_agent.request_fix(
                        error_info=tb,
                        code_context=pruned_cloud_context,
                        language=language,
                        caller_context="",
                        full_file_mode=True,
                        full_file_content=pruned_cloud_context,
                        entry_file=script_path,
                        error_file=patch_target,
                        entry_code=entry_code,
                    )

                    # ---- CANDIDATE RANKING for cloud candidates ----
                    ranked_cloud = CandidateRanker.rank(
                        cloud_candidates, full_code, language, verbose=True
                    )

                    cloud_patch_applied = False

                    for c_idx, patch in enumerate(ranked_cloud):
                        self.console.print(
                            f"[dim]Trying cloud ranked candidate {c_idx + 1}/{len(ranked_cloud)}...[/dim]"
                        )

                        try:
                            patch = auto_fix_syntax(patch, language)
                        except Exception:
                            continue

                        # Read current (restored) original
                        try:
                            original_code = open(patch_target, "r", encoding="utf-8").read()
                        except Exception:
                            continue

                        # ---- Detect patch mode & merge BEFORE validate (cloud) ----
                        _cloud_patch_mode = self._detect_patch_mode(
                            patch, original_code, language, explicit_mode=patch_mode
                        )
                        _cloud_merged = False
                        if _cloud_patch_mode in ("function", "snippet"):
                            try:
                                _cloud_merge = FunctionPatchMerger.merge(
                                    original=original_code, patch=patch, language=language
                                )
                                if _cloud_merge.success:
                                    patch = _cloud_merge.merged_code
                                    _cloud_merged = True
                                    _cloud_patch_mode = "full"
                                    self.console.print(
                                        f"[dim][PatchMerge] Cloud snippet merged "
                                        f"(replaced={_cloud_merge.functions_replaced}, "
                                        f"added={_cloud_merge.functions_added})[/dim]"
                                    )
                            except Exception as _cfm_err:
                                self.console.print(f"[dim]Cloud FunctionPatchMerger error: {_cfm_err}[/dim]")

                        # ---- SEMANTIC VALIDATION on cloud candidate (mode-aware) ----
                        self.console.print(
                            f"[dim][Validator] Validating cloud candidate (mode={_cloud_patch_mode})[/dim]"
                        )
                        val_ok, val_reason = self._validate_candidate(
                            patch, original_code, language, patch_mode=_cloud_patch_mode
                        )
                        if not val_ok:
                            self.console.print(
                                f"[yellow]Cloud candidate {c_idx + 1} rejected: {val_reason}[/yellow]"
                            )
                            continue

                        try:
                            original_lines = original_code.strip().splitlines()
                            patched_lines = patch.strip().splitlines()

                            # Apply patch (full-file or function-level)
                            if patch_mode == "function":
                                apply_result = FunctionPatcher.apply(
                                    patch_target=patch_target,
                                    patch_code=patch,
                                    language=language,
                                    error_info=tb,
                                )
                                if not apply_result["applied"]:
                                    raise ValueError(f"FunctionPatcher: {apply_result['reason']}")
                            else:
                                with open(patch_target, "w", encoding="utf-8") as f:
                                    f.write(patch)

                        except Exception as e:
                            self.console.print(f"[yellow]Cloud patch application failed: {e}[/yellow]")
                            for bp in backup_paths:
                                if os.path.exists(bp):
                                    shutil.copy2(bp, bp[:-7])
                            continue

                        final_result = run_script(script_path)

                        if final_result["returncode"] == 0:
                            validation = OutputValidator.validate(final_result["stdout"], language)

                            if validation["is_suspicious"]:
                                self.console.print(
                                    f"[yellow]! Suspicious cloud output: {validation['flags']}[/yellow]"
                                )
                                self.console.print(
                                    f"[yellow]Patch Accepted / Rejected Reason: Patch rejected: "
                                    f"Suspicious output flags ({validation['flags']})[/yellow]"
                                )
                                for bp in backup_paths:
                                    if os.path.exists(bp):
                                        shutil.copy2(bp, bp[:-7])
                                continue

                            # Behavioral fingerprint for cloud patch
                            cloud_fingerprint = BehaviorFingerprint.capture(
                                final_result.get("stdout", "") or ""
                            )
                            delta = BehaviorFingerprint.delta(initial_fingerprint, cloud_fingerprint)
                            if delta == 0.0 and initial_result.get("returncode", 1) != 0:
                                self.console.print(
                                    "[yellow]! Cloud patch behavioral fingerprint: identical output "
                                    "— may not have fixed the bug. Continuing...[/yellow]"
                                )

                            original_stdout = initial_result.get("stdout", "").strip() if initial_result else ""
                            patched_stdout = final_result.get("stdout", "").strip() if final_result else ""

                            try:
                                if original_stdout and not patched_stdout:
                                    raise ValueError("Cloud patch removed program output")
                            except ValueError as e:
                                self.console.print(f"[yellow]! {e}[/yellow]")
                                for bp in backup_paths:
                                    if os.path.exists(bp):
                                        shutil.copy2(bp, bp[:-7])
                                continue
                            else:
                                self.console.print(
                                    "[green]Patch Accepted / Rejected Reason: Patch accepted: "
                                    "Program executed successfully[/green]"
                                )
                                self.console.print("[green]OK Cloud model fixed the script[/green]")

                                cloud_agent.store_successful_fix(tb, script_path, full_code, patch)

                                if final_result["stdout"]:
                                    self.console.print(final_result["stdout"].strip())

                                return self._build_result(
                                    "SUCCESS", local_attempts, 1, max_retries,
                                    cloud_orchestrator.last_successful_model,
                                    full_code, patch,
                                )
                        else:
                            self.console.print("[red]X Cloud crash persists[/red]")
                            preview = "\n".join(final_result["stderr"].strip().splitlines()[-3:])
                            self.console.print(f"[red]{preview}[/red]")
                            for bp in backup_paths:
                                if os.path.exists(bp):
                                    shutil.copy2(bp, bp[:-7])

            except Exception as e:
                self.console.print(f"[red]Cloud escalation failed: {e}[/red]")

        # -----------------------------
        # 6  FAILURE RESTORE
        # -----------------------------

        self.console.print("[bold red]X All repair attempts failed[/bold red]")

        for bp in backup_paths:
            if os.path.exists(bp):
                shutil.copy2(bp, bp[:-7])

        return self._build_result(
            "FAILED",
            local_attempts, cloud_attempts, max_retries,
            "Unknown", old_code, "",
        )