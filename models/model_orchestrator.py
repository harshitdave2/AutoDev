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
  3. Request timeout -- `timeout` is the per-attempt budget in seconds. The
     orchestrator waits at most ``timeout * (per_model_retries + 1)`` for the
     slowest model, then returns whatever finished. Model calls run in daemon
     threads, so a hung provider can no longer block the CLI or its exit.
  4. last_successful_model -- the highest-priority model that produced a valid
     result. Results are returned in model-priority order (deterministic),
     not completion order.
  5. Backward-compatible: generate_fix() still raises NotImplementedError
     so callers that check hasattr(model, "generate_parallel") still work.
"""

import ast
import re
import threading
import time
from typing import List, Optional

from rich.console import Console
from rich.markup import escape

from models.base_model import BaseModel

_console = Console(highlight=False)


def _log(message: str) -> None:
    """Print Rich markup properly (plain print() leaked literal [dim] tags)."""
    _console.print(message)


_PERMANENT_PHRASES = (
    "quota", "rate limit", "rate_limit", "too many requests", "resource_exhausted",
    "invalid api key", "api key not valid", "unauthorized", "authentication",
    "permission_denied", "forbidden",
)
_STATUS_IN_TEXT = re.compile(r"(?:http|status|code)\D{0,15}(?:401|403|429)(?!\d)")


def _is_permanent_failure(exc: Exception) -> bool:
    """True for quota/auth failures that retrying the same model cannot fix.

    The old check did ``"429" in str(exc)``, which also matched port numbers,
    token counts and line numbers, and so skipped retries for transient errors.
    """
    if exc.__class__.__name__ == "QuotaError":
        return True
    status = getattr(exc, "status_code", None)
    if status is None:
        status = getattr(getattr(exc, "response", None), "status_code", None)
    if isinstance(status, int):
        return status in (401, 403, 429)
    message = str(exc).lower()
    return any(phrase in message for phrase in _PERMANENT_PHRASES) or bool(
        _STATUS_IN_TEXT.search(message)
    )


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

    def _run_model(self, model: BaseModel, prompt: str, language: str) -> Optional[str]:
        """Run one model with its retry budget. Returns raw output or None."""
        model_name = escape(str(getattr(model, "model_name", model.__class__.__name__)))
        provider = escape(model.__class__.__name__.replace("Model", ""))
        max_attempts = self.per_model_retries + 1

        for attempt in range(1, max_attempts + 1):
            try:
                _log(f"    [dim]-> Routing to {model_name} (attempt {attempt})...[/dim]")
                raw_result = model.generate_fix(prompt, language)

                # Gate 1: non-empty output
                if not isinstance(raw_result, str) or not raw_result.strip():
                    raise ValueError(f"{provider} returned empty output")
                stripped_result = raw_result.strip()

                # Gate 2: language-aware structural validation
                struct_ok, struct_reason = _StructuralValidator.validate(
                    stripped_result, language, prompt
                )
                if not struct_ok:
                    raise ValueError(f"{provider} structural validation failed: {struct_reason}")

                # Gate 3: the agent expects a JSON block or a code fence
                if "{" not in stripped_result and "```" not in stripped_result:
                    raise ValueError(
                        f"{provider} output has no JSON block or code fence - likely a prose response"
                    )

                _log(f"    [dim]OK {model_name} produced valid output.[/dim]")
                return raw_result

            except Exception as e:
                detail = escape(str(e).split("\n")[0][:120])

                if _is_permanent_failure(e):
                    _log(f"    [bold yellow]! {provider} unavailable "
                         f"(key invalid or quota exceeded). Skipping.[/bold yellow]")
                    return None

                if attempt >= max_attempts:
                    _log(f"    [bold yellow]! {provider} failed after {attempt} "
                         f"attempt(s): {detail}. Skipping.[/bold yellow]")
                    return None

                _log(f"    [yellow]! {provider} attempt {attempt} failed: {detail}. Retrying...[/yellow]")

        return None

    def generate_parallel(self, prompt: str, language: str = "python") -> List[str]:
        """
        Submit the prompt to all configured models concurrently.

        Returns the raw outputs that passed the quality gates, in model-priority
        order. Models that have not finished within the deadline are skipped.
        """
        if not self.models:
            raise Exception("No cloud models available to orchestrate.")

        outcomes: dict = {}
        lock = threading.Lock()

        def worker(index: int, model: BaseModel) -> None:
            try:
                result = self._run_model(model, prompt, language)
            except BaseException:  # never let a worker die silently without an outcome
                result = None
            with lock:
                outcomes[index] = result

        threads = []
        for index, model in enumerate(self.models):
            thread = threading.Thread(
                target=worker, args=(index, model), daemon=True, name=f"autodev-model-{index}"
            )
            thread.start()
            threads.append(thread)

        deadline = time.monotonic() + self.timeout * (self.per_model_retries + 1)
        for thread in threads:
            thread.join(max(0.0, deadline - time.monotonic()))

        with lock:
            finished = dict(outcomes)

        results: List[str] = []
        winner = None
        for index, model in enumerate(self.models):
            name = str(getattr(model, "model_name", model.__class__.__name__))
            if index not in finished:
                provider = escape(model.__class__.__name__.replace("Model", ""))
                _log(f"    [bold yellow]! {provider} timed out after "
                     f"{self.timeout * (self.per_model_retries + 1):g}s. Skipping.[/bold yellow]")
                continue
            if finished[index] is not None:
                results.append(finished[index])
                if winner is None:
                    winner = name

        if winner is not None:
            self.last_successful_model = winner
        else:
            _log("    [bold red]! All orchestrated models failed to produce valid output.[/bold red]")

        return results
