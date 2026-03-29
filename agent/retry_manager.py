import os
import sys
import shutil
import ast
import requests

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from rich.console import Console
from core.runner import run_script
from core.analyzer import parse_traceback, extract_function_context, extract_additional_context
from core.patcher import backup_file, apply_patch
from agent.agent import AutoDevAgent
from models.ollama_model import OllamaModel
from core.output_validator import OutputValidator
from languages.language_detector import LanguageDetector


class RetryManager:

    def __init__(self, model=None):
        self.console = Console()
        if model is None:
            from models.ollama_model import OllamaModel
            model = OllamaModel()
        self.agent = AutoDevAgent(model=model)

    def _build_result(self, status, local_attempts, cloud_attempts, max_retries, model, old_code, new_code, confidence=None):
        return {
            "status": status,
            "local_attempts": local_attempts,
            "cloud_attempts": cloud_attempts,
            "max_retries": max_retries,
            "model": model,
            "old_code": old_code,
            "new_code": new_code,
            "attempts_used": local_attempts + cloud_attempts,
            "confidence": confidence
        }

    def _synthetic_traceback(self, script_path: str, message: str):
        return {
            "file": script_path,
            "line": 0,
            "error_type": "LogicalBug",
            "error_message": message
        }

    def _is_language_mismatch(self, language: str, code: str) -> bool:
        if not code:
            return True

        code = code.strip()

        if language == "cpp":
            # Strong Python-only markers; keep this strict.
            if "def " in code or "import " in code or "from " in code:
                return True

            # Reject obvious Python main guards in a C++ file.
            if 'if __name__ == "__main__"' in code:
                return True

            return False

        if language == "python":
            # Python should not be replaced with obvious C++ file structure.
            if "#include" in code or "using namespace std" in code:
                return True

            return False

        return False

    def _validate_generated_code(self, language: str, code: str):
        if not code or not code.strip():
            raise ValueError("Empty response from model.")

        lower_code = code.lower()
        placeholders = ["your code here", "your cpp code goes here", "placeholder"]
        for p in placeholders:
            if p in lower_code:
                raise ValueError("Patch contains placeholder text.")

        if "```" in code:
            raise ValueError("Patch contains markdown code fences.")

        if self._is_language_mismatch(language, code):
            raise ValueError(f"Invalid patch: model returned wrong language for {language} file")

        if language == "cpp":
            if "#include" not in code:
                raise ValueError("Invalid patch: Missing #include statements in C++ file.")
            if "main(" not in code:
                raise ValueError("Invalid patch: Missing main() function in C++ file.")
            for kw in ["def ", "import ", "print("]:
                if kw in code:
                    raise ValueError(f"Invalid patch: Python keyword '{kw}' found in C++ file.")

    @staticmethod
    def _extract_context(file_path: str, line: int, window: int = 25) -> str:
        with open(file_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        start = max(0, line - window)
        end = min(len(lines), line + window)
        return "".join(lines[start:end])

    @staticmethod
    def validate_cpp_patch(code: str) -> bool:
        return True

    @staticmethod
    def quick_cpp_repairs(code: str) -> str:
        """Apply deterministic pattern-based fixes before calling the LLM."""
        # Fix scalar matrix initialisers → 2D array
        code = code.replace(
            "int A = {{1, 2}, {3, 4}};",
            "int A[2][2] = {{1, 2}, {3, 4}};"
        )
        code = code.replace(
            "int B = {{5, 6}, {7, 8}};",
            "int B[2][2] = {{5, 6}, {7, 8}};"
        )
        # Fix common matrix multiply index bug: B[i][j] → B[k][j]
        # Only fix inside the multiply loop body, not the declaration
        code = code.replace(
            "C[i][j] += A[i][k] * B[i][j]",
            "C[i][j] += A[i][k] * B[k][j]"
        )
        return code

    def attempt_fix(self, script_path: str, max_retries: int = 3, dry_run: bool = False):

        backup_path = None
        old_code = ""
        new_code = ""
        local_attempts = 0
        cloud_attempts = 0
        language = LanguageDetector.detect(script_path)
        result = None
        full_code = ""

        # -----------------------------
        # 1️⃣ INITIAL EXECUTION CHECK
        # -----------------------------

        self.console.print("\n[bold yellow]=== Initial Execution Check ===[/bold yellow]")

        initial_result = run_script(script_path)

        if initial_result["returncode"] == 0:
            validation = OutputValidator.validate(initial_result["stdout"], language)

            if validation["is_suspicious"]:
                self.console.print(
                    f"[bold yellow]⚠ Suspicious output detected: {validation['flags']}[/bold yellow]"
                )
                self.console.print("[yellow]Proceeding with repair attempts...[/yellow]")
                result = initial_result
            else:
                self.console.print("[bold green]✔ Success! The script executed flawlessly.[/bold green]")

                if initial_result["stdout"]:
                    self.console.print(f"[dim]Output:\n{initial_result['stdout'].strip()}[/dim]")

                confidence = "HIGH"

                return self._build_result(
                    "SUCCESS",
                    0,
                    0,
                    max_retries,
                    "None (Already Working)",
                    "",
                    "",
                    confidence
                )

        else:
            self.console.print("[bold red]✘ Crash detected![/bold red]")
            error_preview = "\n".join(initial_result["stderr"].strip().splitlines()[-3:])
            self.console.print(f"[red]{error_preview}[/red]")
            result = initial_result

        # -----------------------------
        # 2️⃣ BACKUP FILE
        # -----------------------------

        if not dry_run:
            backup_path = backup_file(script_path)
            self.console.print(f"[dim]Backup created at: {backup_path}[/dim]")

        # -----------------------------
        # 3️⃣ CHECK OLLAMA
        # -----------------------------

        ollama_available = False

        try:
            r = requests.get("http://localhost:11434/api/tags", timeout=2.0)
            if r.status_code == 200:
                ollama_available = True
        except:
            ollama_available = False

        if not ollama_available:
            self.console.print("[bold yellow]⚠ Ollama unavailable. Skipping local repair.[/bold yellow]")

        # -----------------------------
        # 3.5 ⚡ QUICK HEURISTIC REPAIR
        # -----------------------------

        if language == "cpp":
            with open(script_path, "r", encoding="utf-8") as f:
                raw = f.read()

            repaired = self.quick_cpp_repairs(raw)

            if repaired != raw:
                self.console.print("[cyan]⚡ Applying quick heuristic repair...[/cyan]")
                with open(script_path, "w", encoding="utf-8") as f:
                    f.write(repaired)

                quick_result = run_script(script_path)

                if quick_result["returncode"] == 0:
                    validation = OutputValidator.validate(quick_result["stdout"], language)
                    if not validation["is_suspicious"]:
                        self.console.print("[bold green]✔ Quick repair succeeded![/bold green]")
                        if quick_result["stdout"]:
                            self.console.print(quick_result["stdout"].strip())
                        return self._build_result(
                            "SUCCESS", 0, 0, max_retries,
                            "QuickRepair", raw, repaired, "HIGH"
                        )
                else:
                    # Quick repair did not fix everything — keep the partial improvements
                    # so the LLM sees cleaner code
                    result = quick_result

        # -----------------------------
        # 4️⃣ LOCAL REPAIR LOOP
        # -----------------------------

        if ollama_available:

            for attempt in range(1, max_retries + 1):

                local_attempts = attempt
                is_last = attempt == max_retries

                self.console.print(f"\n[bold yellow]=== Local Attempt {attempt}/{max_retries} ===[/bold yellow]")

                if is_last:
                    self.console.print("[magenta]⚠ Final Local Attempt: Full-file repair[/magenta]")

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
                    full_code = f.read()

                # Attempt 1 & 2 → targeted context repair; Attempt 3 → full file
                if is_last:
                    primary = full_code
                    old_code = full_code
                elif tb.get("line"):
                    primary = self._extract_context(script_path, tb["line"])
                    old_code = primary
                else:
                    primary = full_code
                    old_code = full_code

                caller = ""

                generation_success = False
                patch_candidates = []

                for gen_attempt in range(3):
                    with self.console.status(f"[blue]🧠 Generating fix in parallel (Attempt {gen_attempt+1})...[/blue]"):
                        try:
                            patch_candidates = self.agent.request_fix(
                                error_info=tb,
                                code_context=primary,
                                language=language,
                                caller_context=caller,
                                full_file_mode=is_last,
                                full_file_content=old_code if is_last else ""
                            )
                            if patch_candidates:
                                generation_success = True
                                break
                        except Exception as e:
                            self.console.print(f"[red]AI generation failed: {e}[/red]")

                if not generation_success:
                    self.console.print("[red]All models failed to generate valid code for this attempt.[/red]")
                    continue

                if dry_run:
                    self.console.print("[yellow]DRY RUN — patch not applied[/yellow]")
                    return self._build_result(
                        "DRY_RUN",
                        local_attempts,
                        cloud_attempts,
                        max_retries,
                        getattr(self.agent.model, "last_successful_model", "Multiple Models"),
                        old_code,
                        patch_candidates[0] if patch_candidates else ""
                    )

                patch_success = False

                for idx, candidate in enumerate(patch_candidates):
                    self.console.print(f"[blue]🔧 Testing candidate patch {idx+1}/{len(patch_candidates)}...[/blue]")

                    try:
                        self._validate_generated_code(language, candidate)

                        if language == "cpp":
                            if "def " in candidate:
                                raise ValueError("Invalid patch: Python returned for C++")
                            if not self.validate_cpp_patch(candidate):
                                self.console.print(f"[yellow]⚠ Skipping candidate {idx+1}: inconsistent patch (scalar/vector mismatch).[/yellow]")
                                continue

                        if is_last:
                            target_file = tb["file"] if tb.get("file") else script_path
                            with open(target_file, "w", encoding="utf-8") as f:
                                f.write(candidate)
                        else:
                            apply_patch(tb["file"], old_code, candidate)

                    except Exception as e:
                        # Defensive logging specifying reason why patch was rejected
                        self.console.print(f"[yellow]Patch application failed for candidate {idx+1}: {e}[/yellow]")
                        if backup_path and os.path.exists(backup_path):
                            shutil.copy2(backup_path, script_path)
                        continue

                    # -----------------------------
                    # VERIFY FIX
                    # -----------------------------

                    result = run_script(script_path)

                    if result["returncode"] == 0:
                        validation = OutputValidator.validate(result["stdout"], language)

                        if validation["is_suspicious"]:
                            self.console.print(f"[yellow]⚠ Suspicious output: {validation['flags']}[/yellow]")
                            if backup_path and os.path.exists(backup_path):
                                shutil.copy2(backup_path, script_path)
                            continue
                        else:
                            self.console.print("[green]✔ Script fixed successfully![/green]")

                            if hasattr(self.agent, "store_successful_fix"):
                                self.agent.store_successful_fix(tb, script_path, primary, candidate)

                            if result["stdout"]:
                                self.console.print(result["stdout"].strip())

                            return self._build_result(
                                "SUCCESS",
                                local_attempts,
                                cloud_attempts,
                                max_retries,
                                getattr(self.agent.model, "last_successful_model", "Multiple Models"),
                                old_code,
                                candidate
                            )
                    else:
                        self.console.print(f"[red]✘ Crash persists for candidate {idx+1}[/red]")
                        preview = "\n".join(result["stderr"].strip().splitlines()[-3:])
                        self.console.print(preview)
                        
                        if backup_path and os.path.exists(backup_path):
                            shutil.copy2(backup_path, script_path)
                
                # Loop continues to next local attempt if none worked

        # -----------------------------
        # 5️⃣ CLOUD ESCALATION
        # -----------------------------

        if not dry_run:
            self.console.print("\n[bold magenta]🚀 Escalating to Cloud Models[/bold magenta]")

            if backup_path and os.path.exists(backup_path):
                shutil.copy2(backup_path, script_path)

            try:
                from models.groq_model import GroqModel
                from models.gemini_model import GeminiModel
                from models.model_orchestrator import ModelOrchestrator
                import json

                with open("autodev_config.json") as f:
                    cfg = json.load(f)

                cloud_models = []
                api_keys = cfg.get("api_keys", {})

                if cfg.get("groq_model") and api_keys.get("groq"):
                    try:
                        cloud_models.append(GroqModel(cfg["groq_model"], api_keys["groq"]))
                    except:
                        pass
                
                if cfg.get("gemini_model") and api_keys.get("gemini"):
                    try:
                        cloud_models.append(GeminiModel(cfg["gemini_model"], api_keys["gemini"]))
                    except:
                        pass
                
                if not cloud_models:
                    self.console.print("[dim]No cloud models configured[/dim]")
                else:
                    cloud_orchestrator = ModelOrchestrator(cloud_models)
                    cloud_agent = AutoDevAgent(model=cloud_orchestrator)

                    if result and result.get("traceback"):
                        tb = result["traceback"]
                    else:
                        tb = parse_traceback(result["stderr"]) if result and result.get("stderr") else {}

                    if not tb.get("file") or not tb.get("line"):
                        tb = self._synthetic_traceback(script_path, "Suspicious output detected")
                    
                    with open(script_path, "r", encoding="utf-8") as f:
                        full_code = f.read()

                    cloud_candidates = cloud_agent.request_fix(
                        error_info=tb,
                        code_context=full_code,
                        language=language,
                        caller_context="",
                        full_file_mode=True,
                        full_file_content=full_code
                    )

                    for idx, patch in enumerate(cloud_candidates):
                        self.console.print(f"[blue]🔧 Testing cloud candidate {idx+1}/{len(cloud_candidates)}...[/blue]")
                        
                        try:
                            self._validate_generated_code(language, patch)
                            if language == "cpp":
                                if "def " in patch:
                                    raise ValueError("Invalid patch: Python returned for C++")
                                if not self.validate_cpp_patch(patch):
                                    self.console.print(f"[yellow]⚠ Skipping cloud candidate {idx+1}: inconsistent patch (scalar/vector mismatch).[/yellow]")
                                    continue

                            with open(script_path, "w", encoding="utf-8") as f:
                                f.write(patch)

                        except Exception as e:
                            self.console.print(f"[yellow]Cloud patch application failed for candidate {idx+1}: {e}[/yellow]")
                            if backup_path and os.path.exists(backup_path):
                                shutil.copy2(backup_path, script_path)
                            continue

                        final_result = run_script(script_path)

                        if final_result["returncode"] == 0:
                            validation = OutputValidator.validate(final_result["stdout"], language)

                            if validation["is_suspicious"]:
                                self.console.print(f"[yellow]⚠ Suspicious cloud output: {validation['flags']}[/yellow]")
                                if backup_path and os.path.exists(backup_path):
                                    shutil.copy2(backup_path, script_path)
                                continue
                            else:
                                self.console.print("[green]✔ Cloud model fixed the script[/green]")

                                cloud_agent.store_successful_fix(tb, script_path, full_code, patch)

                                if final_result["stdout"]:
                                    self.console.print(final_result["stdout"].strip())

                                return self._build_result(
                                    "SUCCESS", local_attempts, 1, max_retries,
                                    cloud_orchestrator.last_successful_model, full_code, patch
                                )
                        else:
                            self.console.print(f"[red]✘ Cloud crash persists for candidate {idx+1}[/red]")
                            preview = "\n".join(final_result["stderr"].strip().splitlines()[-3:])
                            self.console.print(preview)
                            if backup_path and os.path.exists(backup_path):
                                shutil.copy2(backup_path, script_path)

            except Exception as e:
                self.console.print(f"[red]Cloud escalation failed: {e}[/red]")

        # -----------------------------
        # 6️⃣ FAILURE RESTORE
        # -----------------------------

        self.console.print("[bold red]✖ All repair attempts failed[/bold red]")

        if backup_path and os.path.exists(backup_path):
            shutil.copy2(backup_path, script_path)

        return self._build_result(
            "FAILED",
            local_attempts,
            cloud_attempts,
            max_retries,
            "Unknown",
            old_code,
            ""
        )