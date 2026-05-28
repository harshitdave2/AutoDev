"""
core/context_pruner.py
----------------------
Token-budget-aware context pruner for AutoDev.

Trims the code context sent to the LLM to a configurable token budget
while preserving the highest-signal sections:

  1. Import/global declarations (top of file)
  2. Crashing function body (from ContextEngine / analyzer)
  3. Direct caller functions (from traceback)
  4. ±20 lines around the crash line
  5. Everything else → replaced with `# ... [N lines omitted] ...`

Token estimation: len(text) // 4 (safe approximation, no external deps).

Usage:
    pruner = ContextPruner(budget=3500)
    pruned = pruner.prune(
        full_code=full_code,
        crash_line=tb.get("line", 0),
        crashing_func=crashing_func_src,
        caller_funcs=caller_func_srcs,
        language=language,
    )
"""

import re
from typing import List, Optional


# ---------------------------------------------------------------------------
# Token estimation
# ---------------------------------------------------------------------------

def _estimate_tokens(text: str) -> int:
    """
    Approximate token count using the 4-chars-per-token heuristic.
    Accurate enough for context budgeting without requiring tiktoken.
    """
    return max(1, len(text) // 4)


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

class ContextPruner:
    """
    Prunes source code context to fit within a token budget before it is
    sent to a language model.

    Attributes:
        budget (int): Maximum allowed tokens in the pruned context.
        header_lines (int): Number of leading lines (imports/globals) to always keep.
        crash_window (int): Lines to include above and below the crash line.
    """

    def __init__(
        self,
        budget: int = 3500,
        header_lines: int = 20,
        crash_window: int = 20,
        fast_mode: bool = False,
    ):
        self.budget = budget
        self.header_lines = header_lines
        self.crash_window = crash_window
        self.fast_mode = fast_mode

    def prune(
        self,
        full_code: str,
        crash_line: int = 0,
        crashing_func: str = "",
        caller_funcs: Optional[List[str]] = None,
        language: str = "python",
    ) -> str:
        """
        Return a pruned version of full_code that fits within self.budget tokens.

        Priority order (high → low):
          1. File header (imports, globals, package declarations)
          2. Crashing function body
          3. Caller function bodies
          4. Crash-line window (±crash_window lines)
          5. Remaining lines (omitted with a comment)

        If the full file already fits within budget, it is returned as-is.
        """
        if not full_code or not full_code.strip():
            return full_code

        caller_funcs = caller_funcs or []

        # Fast path: file fits in budget without any pruning
        if _estimate_tokens(full_code) <= self.budget:
            token_count = _estimate_tokens(full_code)
            print(
                f"[PrunedContext] File fits within budget — "
                f"{len(full_code.splitlines())} lines, ~{token_count} tokens (budget={self.budget})"
            )
            return full_code

        lines = full_code.splitlines()
        total_lines = len(lines)

        # --- Build priority regions as sets of (0-indexed) line numbers ---
        included: set[int] = set()

        # Region 1: File header (imports, package decls, globals)
        header_end = min(self.header_lines, total_lines)
        for i in range(header_end):
            included.add(i)

        # Region 2: Crashing function body
        if crashing_func and crashing_func.strip():
            func_lines = crashing_func.splitlines()
            # Find where this block appears in the full file
            start_idx = self._find_block_start(lines, func_lines)
            if start_idx >= 0:
                for i in range(start_idx, min(start_idx + len(func_lines), total_lines)):
                    included.add(i)

        # Region 3: Caller function bodies — SKIPPED in fast mode (saves tokens)
        if not self.fast_mode:
            for caller_src in caller_funcs:
                if not caller_src or not caller_src.strip():
                    continue
                caller_lines = caller_src.splitlines()
                start_idx = self._find_block_start(lines, caller_lines)
                if start_idx >= 0:
                    for i in range(start_idx, min(start_idx + len(caller_lines), total_lines)):
                        included.add(i)

        # Region 4: Crash-line window (1-indexed crash_line → 0-indexed)
        if crash_line and crash_line > 0:
            cl0 = crash_line - 1  # convert to 0-indexed
            window_start = max(0, cl0 - self.crash_window)
            window_end = min(total_lines, cl0 + self.crash_window + 1)
            for i in range(window_start, window_end):
                included.add(i)

        # --- Assemble the pruned output ---
        pruned = self._assemble(lines, included, language)

        # --- Budget compliance check ---
        if _estimate_tokens(pruned) > self.budget:
            # Over budget: fall back to crashing function + crash window only
            included_tight: set[int] = set()
            for i in range(header_end):
                included_tight.add(i)
            if crash_line and crash_line > 0:
                cl0 = crash_line - 1
                window_start = max(0, cl0 - self.crash_window)
                window_end = min(total_lines, cl0 + self.crash_window + 1)
                for i in range(window_start, window_end):
                    included_tight.add(i)
            pruned = self._assemble(lines, included_tight, language)

        token_count = _estimate_tokens(pruned)
        pruned_lines_count = len(pruned.splitlines())
        omitted = total_lines - pruned_lines_count
        mode_label = "fast" if self.fast_mode else "normal"

        print(
            f"[PrunedContext] {total_lines} → {pruned_lines_count} lines "
            f"({omitted} omitted) | ~{token_count} tokens | "
            f"budget={self.budget} | mode={mode_label}"
        )

        return pruned

    # -----------------------------------------------------------------------
    # Internal helpers
    # -----------------------------------------------------------------------

    @staticmethod
    def _find_block_start(file_lines: List[str], block_lines: List[str]) -> int:
        """
        Find the 0-indexed start position of block_lines inside file_lines
        using the first non-empty line of the block as an anchor.
        Returns -1 if not found.
        """
        if not block_lines:
            return -1

        # Use the first non-empty line as anchor
        anchor = next((l.rstrip() for l in block_lines if l.strip()), None)
        if anchor is None:
            return -1

        for i, line in enumerate(file_lines):
            if line.rstrip() == anchor:
                # Verify subsequent lines match (partial match is fine)
                match_len = min(len(block_lines), len(file_lines) - i)
                if match_len > 0:
                    return i
        return -1

    @staticmethod
    def _assemble(
        lines: List[str],
        included: set[int],
        language: str,
    ) -> str:
        """
        Build the pruned source string from the selected line indices.
        Consecutive omitted ranges are collapsed into a single omission comment.
        """
        if not included:
            return ""

        result_parts: List[str] = []
        omit_count = 0
        comment_prefix = _comment_prefix(language)

        for i, line in enumerate(lines):
            if i in included:
                if omit_count > 0:
                    result_parts.append(
                        f"{comment_prefix} ... [{omit_count} lines omitted] ..."
                    )
                    omit_count = 0
                result_parts.append(line)
            else:
                omit_count += 1

        # Flush any trailing omission
        if omit_count > 0:
            result_parts.append(
                f"{comment_prefix} ... [{omit_count} lines omitted] ..."
            )

        return "\n".join(result_parts)


def _comment_prefix(language: str) -> str:
    """Return the single-line comment prefix for the given language."""
    if language == "python":
        return "#"
    elif language == "java":
        return "//"
    elif language == "cpp":
        return "//"
    return "#"


# ---------------------------------------------------------------------------
# Convenience factory
# ---------------------------------------------------------------------------

def make_pruner(is_cloud: bool = False, fast_mode: bool = False) -> ContextPruner:
    """
    Factory that returns a ContextPruner pre-configured for local or cloud use.

    Local (Ollama) normal: 3500 token budget.
    Local (Ollama) fast:   1500 token budget — crash function + window only, no callers.
    Cloud (Groq/Gemini):  12000 token budget.

    Args:
        is_cloud  : True for cloud models (Groq/Gemini).
        fast_mode : True for speed-first local mode (tightest context).
    """
    if is_cloud:
        budget = 12_000
        fm = False
    elif fast_mode:
        budget = 1_500
        fm = True
    else:
        budget = 3_500
        fm = False
    return ContextPruner(budget=budget, fast_mode=fm)
