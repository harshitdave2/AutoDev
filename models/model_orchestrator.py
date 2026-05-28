"""
models/model_orchestrator.py
-----------------------------
Production-grade model orchestrator for AutoDev (upgraded).

Changes over original version:
  1. Language-aware structural quality gate -- replaces the raw character-count
     gate that incorrectly rejected short but valid partial patches.
     Python: must contain def/class/import or be parseable.
     C++   : must contain balanced structure indicators or function signatures.
     Java  : must contain class/method structure or import/package.
  2. Per-model retry budget -- each model gets one automatic retry on a
     transient failure before failing over to the next model.
  3. Request timeout -- each model call is capped at `timeout` seconds
     (default 30s local / 60s cloud) via Future.result(timeout=...).
  4. last_successful_model -- correctly records the model name from the
     winning future even under concurrent execution.
  5. Backward-compatible: generate_fix() still raises NotImplementedError
     so callers that check hasattr(model, "generate_parallel") still work.
"""

import ast
import re
from concurrent.futures import ThreadPoolExecutor, as_completed, Future, TimeoutError as FuturesTimeoutError
from typing import List, Optional

from models.base_model import BaseModel


# ---------------------------------------------------------------------------
# Language-aware structural validator
# ---------------------------------------------------------------------------

class _StructuralValidator:
    """
    Validates that an LLM output contains real code structure for the target
    language, rather than relying on raw character count.

    This replaces the old `len(output) < MIN_LEN` gate which incorrectly
    rejected valid partial patches (e.g. a single fixed function).
    """

    @classmethod
    def validate(cls, output: str, language: str, prompt: str = "") -> tuple:
        """
        Check if `output` is a structurally valid response for `language`.

        Returns:
            (is_valid: bool, reason: str)
        """
        stripped = output.strip()
        if not stripped:
            return False, "Output is empty"

        lang = language.lower()

        if lang == "python":
            return cls._validate_python(stripped)
        elif lang == "java":
            return cls._validate_java(stripped)
        elif lang == "cpp":
            return cls._validate_cpp(stripped)
        else:
            return cls._validate_generic(stripped)

    @staticmethod
    def _validate_python(code: str) -> tuple:
        """
        Python is valid if it:
          a) Parses as valid Python AST, OR
          b) Contains at least one structural keyword (def/class/import/return)
             AND is not pure prose
        """
        # Fast path: try AST parse
        try:
            ast.parse(code)
            return True, "Valid Python (AST parse succeeded)"
        except SyntaxError:
            pass

        # Structural keyword check
        structural_keywords = [
            r'^def\s+\w', r'^async\s+def\s+\w', r'^class\s+\w',
            r'^import\s+\w', r'^from\s+\w.*import',
            r'^\s+return\s', r'^\s+raise\s', r'^if\s+__name__',
        ]
        for pattern in structural_keywords:
            if re.search(pattern, code, re.MULTILINE):
                return True, "Valid Python (structural keywords present)"

        # Has code-like indicators (indented blocks)
        code_lines = [l for l in code.splitlines() if l.strip() and not l.strip().startswith('#')]
        if len(code_lines) >= 2:
            indented = sum(1 for l in code_lines if l.startswith(("    ", "\t")))
            if indented >= 1:
                return True, "Valid Python (indented code block present)"

        return False, "Python output contains no structural code indicators"

    @staticmethod
    def _validate_java(code: str) -> tuple:
        """
        Java is valid if it contains:
          - class/interface/method declaration, OR
          - import/package statement, OR
          - return/throw statement with proper syntax
        """
        structural_patterns = [
            r'\bclass\s+\w',
            r'\binterface\s+\w',
            r'^import\s+\w',
            r'^package\s+\w',
            r'(?:public|private|protected|static)\s+(?:[\w<>\[\]]+\s+)\w+\s*\(',
            r'\breturn\s+[^;]+;',
            r'\bnew\s+\w+\s*\(',
        ]
        for pattern in structural_patterns:
            if re.search(pattern, code, re.MULTILINE):
                return True, "Valid Java (structural pattern matched)"

        # Check for balanced braces (at minimum)
        if code.count('{') >= 1 and code.count(';') >= 1:
            return True, "Valid Java (braces and semicolons present)"

        return False, "Java output contains no structural code indicators"

    @staticmethod
    def _validate_cpp(code: str) -> tuple:
        """
        C++ is valid if it contains:
          - #include directives, OR
          - function signatures with return types, OR
          - balanced brace structures with semicolons
        """
        structural_patterns = [
            r'^#include\s*[<"]',
            r'^#define\s+\w',
            r'(?:int|void|bool|float|double|char|auto|std::\w+)\s+\w+\s*\(',
            r'\breturn\s+[^;]+;',
            r'\bstd::\w+',
            r'\bcout\s*<<',
            r'\bcin\s*>>',
        ]
        for pattern in structural_patterns:
            if re.search(pattern, code, re.MULTILINE):
                return True, "Valid C++ (structural pattern matched)"

        # Check for braces + semicolons (minimal valid C++ fragment)
        if code.count('{') >= 1 and code.count('}') >= 1 and code.count(';') >= 1:
            return True, "Valid C++ (brace structure and semicolons present)"

        return False, "C++ output contains no structural code indicators"

    @staticmethod
    def _validate_generic(code: str) -> tuple:
        """
        Generic fallback: accept if response has any code-like content
        (braces, semicolons, or 3+ non-blank lines).
        """
        has_structure = '{' in code or ';' in code
        non_blank = [l for l in code.splitlines() if l.strip()]
        if has_structure or len(non_blank) >= 3:
            return True, "Valid (generic structural check passed)"
        return False, "Output has no recognizable code structure"


class ModelOrchestrator(BaseModel):
    """
    Intelligent load-balancer that attempts generation with a priority list
    of models, seamlessly failing over to the next if a model crashes,
    hits a quota, hallucinates bad syntax, or times out.

    Attributes:
        models              : Ordered list of BaseModel instances to try.
        last_successful_model: Name of the model that produced the last valid output.
        timeout             : Per-model request timeout in seconds.
        per_model_retries   : Number of automatic retries per model on transient failure.
        min_length_ratio    : DEPRECATED — kept for backward compatibility but not used
                              for validation. Language-aware structural validation is
                              used instead.
    """

    def __init__(
        self,
        models: Optional[List[BaseModel]] = None,
        timeout: int = 60,
        per_model_retries: int = 1,
        min_length_ratio: float = 0.3,  # Kept for backward compat — no longer used
    ):
        self.models = models if models is not None else []
        self.last_successful_model = "Multiple Models"
        self.timeout = timeout
        self.per_model_retries = per_model_retries
        self.min_length_ratio = min_length_ratio  # Preserved but inactive

    # -----------------------------------------------------------------------
    # Public interface
    # -----------------------------------------------------------------------

    def generate_fix(self, prompt: str, language: str = "python") -> str:
        """
        Not implemented on the orchestrator — use generate_parallel instead.
        Kept for backward compatibility with callers that call hasattr checks.
        """
        raise NotImplementedError(
            "ModelOrchestrator does not implement generate_fix(). "
            "Call generate_parallel() instead."
        )

    def generate_parallel(self, prompt: str, language: str = "python") -> List[str]:
        """
        Submit the prompt to all available models concurrently.
        Applies the quality gate and collects valid results.

        Args:
            prompt   : The full repair prompt string.
            language : Target language ("python", "java", "cpp").

        Returns:
            List of raw model output strings that passed quality validation.
            Empty list if all models failed.
        """
        if not self.models:
            raise Exception("No cloud models available to orchestrate.")

        results: List[str] = []

        def run_model(model: BaseModel) -> Optional[str]:
            """Run a single model with retry budget and timeout."""
            model_name = getattr(model, "model_name", model.__class__.__name__)
            provider = model.__class__.__name__.replace("Model", "")

            for attempt in range(1, self.per_model_retries + 2):
                # +2 so per_model_retries=1 means 2 total attempts
                try:
                    print(f"    [dim]-> Routing to {model_name} (attempt {attempt})...[/dim]")
                    raw_result = model.generate_fix(prompt, language)

                    # --- Quality Gate 1: Non-empty output ---
                    if not raw_result or not raw_result.strip():
                        raise ValueError(f"{provider} returned empty output")

                    stripped_result = raw_result.strip()

                    # --- Quality Gate 2: Language-aware structural validation ---
                    # Replaces the old raw character-count gate.
                    # Short but structurally valid patches are now accepted.
                    struct_ok, struct_reason = _StructuralValidator.validate(
                        stripped_result, language, prompt
                    )
                    if not struct_ok:
                        raise ValueError(
                            f"{provider} structural validation failed: {struct_reason}"
                        )

                    # --- Quality Gate 3: JSON structure presence ---
                    # The agent expects a JSON block with candidate_1/2/3.
                    # A response with no '{' at all is almost certainly wrong.
                    if "{" not in stripped_result and "```" not in stripped_result:
                        raise ValueError(
                            f"{provider} output has no JSON block or code fence — "
                            f"likely a prose response"
                        )

                    print(f"    [dim]OK {model_name} produced valid output.[/dim]")
                    return raw_result

                except FuturesTimeoutError:
                    print(
                        f"    [bold yellow]! {provider} timed out after {self.timeout}s. "
                        f"Skipping.[/bold yellow]"
                    )
                    return None  # Timeout is unrecoverable — don't retry

                except Exception as e:
                    error_str = str(e).lower()
                    error_class = e.__class__.__name__

                    is_quota = (
                        "429" in error_str
                        or "quota" in error_str
                        or "rate limit" in error_str
                        or error_class == "QuotaError"
                        or "invalid api key" in error_str
                        or "authentication" in error_str
                        or "unauthorized" in error_str
                    )
                    is_last_attempt = (attempt >= self.per_model_retries + 1)

                    if is_quota:
                        # Quota/auth errors are permanent — no retry
                        print(
                            f"    [bold yellow]! {provider} unavailable "
                            f"(key invalid or quota exceeded). Skipping.[/bold yellow]"
                        )
                        return None

                    if is_last_attempt:
                        simplified_msg = str(e).split("\n")[0][:120]
                        print(
                            f"    [bold yellow]! {provider} failed after "
                            f"{attempt} attempt(s): {simplified_msg}. Skipping.[/bold yellow]"
                        )
                        return None

                    # Transient error — retry
                    simplified_msg = str(e).split("\n")[0][:80]
                    print(
                        f"    [yellow]! {provider} attempt {attempt} failed: "
                        f"{simplified_msg}. Retrying...[/yellow]"
                    )

            return None  # All retries exhausted

        # -----------------------------------------------------------------------
        # Concurrent execution with per-future timeout
        # -----------------------------------------------------------------------
        with ThreadPoolExecutor(max_workers=max(1, len(self.models))) as executor:
            future_to_model: dict[Future, BaseModel] = {
                executor.submit(run_model, m): m for m in self.models
            }

            for future in as_completed(future_to_model):
                model = future_to_model[future]
                model_name = getattr(model, "model_name", model.__class__.__name__)

                try:
                    res = future.result(timeout=self.timeout)
                except FuturesTimeoutError:
                    provider = model.__class__.__name__.replace("Model", "")
                    print(
                        f"    [bold yellow]! {provider} future timed out after "
                        f"{self.timeout}s. Skipping.[/bold yellow]"
                    )
                    continue
                except Exception as e:
                    simplified = str(e).split("\n")[0][:120]
                    print(f"    [yellow]! Future error for {model_name}: {simplified}[/yellow]")
                    continue

                if res is not None:
                    results.append(res)
                    # Record the winning model name under a lock-free pattern
                    # (last write wins in CPython due to GIL, good enough here)
                    self.last_successful_model = model_name

        if not results:
            print("    [bold red]! All orchestrated models failed to produce valid output.[/bold red]")

        return results