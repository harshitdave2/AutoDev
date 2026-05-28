"""
core/response_normalizer.py
----------------------------
Normalize raw LLM output into clean code candidates.

LLMs return code in inconsistent shapes:
  - Markdown fenced blocks (```python ... ```)
  - JSON-wrapped patches  ({"fixed_code": "..."})
  - Multi-candidate JSON  ({"candidate_1": "...", ...})
  - Plain code            (raw source, no wrapper)
  - Explanations mixed with code
  - Partial function snippets with prose around them

This module is the FIRST stage in the patch pipeline.  It runs before
PatchValidator, CandidateRanker, and FunctionPatchMerger.

Pipeline position:
    LLM output
      -> ResponseNormalizer.normalize()   # <-- this module
      -> PatchCompletion.complete()
      -> FunctionPatchMerger.merge()
      -> PatchValidator.validate()
      -> CandidateRanker.rank()

Usage:
    result = ResponseNormalizer.normalize(raw_llm_output, language="python")
    for candidate in result.candidates:
        # each is a clean code string, ready for validation
        ...
    print(result.source_format)   # "markdown", "json_multi", "plain", etc.
    print(result.is_partial)      # True if patch looks like a snippet
"""

import ast
import json
import re
from dataclasses import dataclass, field
from typing import List, Optional


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass
class NormalizedOutput:
    """
    The result of normalizing a single raw LLM response.

    Attributes:
        candidates    : List of clean code strings extracted (1–3 typically).
        source_format : How the code was encoded ("markdown", "json_multi",
                        "json_single", "plain", "fence_mixed").
        is_partial    : True if the patch looks like a function snippet, not
                        a complete file.
        raw           : The original unmodified LLM output.
        notes         : Any normalizer notes (e.g. "stripped 3 prose lines").
    """
    candidates: List[str]
    source_format: str
    is_partial: bool
    raw: str
    notes: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Normalizer
# ---------------------------------------------------------------------------

class ResponseNormalizer:
    """
    Converts raw LLM output into clean, validated code candidates.

    All methods are classmethods — no instantiation needed.
    Safe: never raises on malformed input.
    """

    # Prose lines that LLMs prefix their responses with
    _PROSE_PREFIXES = (
        "here", "sure", "certainly", "of course", "explanation:",
        "the fix", "this fix", "i've", "i have", "below", "above",
        "let me", "the issue", "the bug", "the problem", "note:",
        "result:", "output:", "changes:", "fix:", "solution:",
    )

    @classmethod
    def normalize(
        cls,
        raw: str,
        language: str = "python",
    ) -> NormalizedOutput:
        """
        Normalize a raw LLM response into clean candidate code strings.

        Tries extraction strategies in priority order:
          1. Multi-candidate JSON  ({"candidate_1": "...", "candidate_2": "..."})
          2. Single-key JSON       ({"fixed_code": "..."})
          3. Markdown fenced block (```python ... ```)
          4. Plain code            (no wrapper detected)

        Args:
            raw      : The raw text output from the LLM.
            language : Target language for heuristics ("python", "java", "cpp").

        Returns:
            NormalizedOutput with candidates and metadata.
        """
        if not raw or not raw.strip():
            return NormalizedOutput(
                candidates=[],
                source_format="empty",
                is_partial=False,
                raw=raw or "",
                notes=["Empty LLM response"],
            )

        notes: List[str] = []

        # Strip BOS/EOS sentinel tokens
        cleaned = cls._strip_sentinels(raw)

        # --- Strategy 1: Multi-candidate JSON ---
        mc_result = cls._try_multi_candidate_json(cleaned, language, notes)
        if mc_result:
            is_partial = any(cls._is_partial(c, language) for c in mc_result)
            return NormalizedOutput(
                candidates=mc_result,
                source_format="json_multi",
                is_partial=is_partial,
                raw=raw,
                notes=notes,
            )

        # --- Strategy 2: Single-key JSON ---
        sc_result = cls._try_single_json(cleaned, language, notes)
        if sc_result:
            is_partial = cls._is_partial(sc_result, language)
            return NormalizedOutput(
                candidates=[sc_result],
                source_format="json_single",
                is_partial=is_partial,
                raw=raw,
                notes=notes,
            )

        # --- Strategy 3: Markdown fenced blocks ---
        fence_results = cls._try_fenced_blocks(cleaned, language, notes)
        if fence_results:
            is_partial = any(cls._is_partial(c, language) for c in fence_results)
            return NormalizedOutput(
                candidates=fence_results,
                source_format="markdown",
                is_partial=is_partial,
                raw=raw,
                notes=notes,
            )

        # --- Strategy 4: Plain text / fallback ---
        plain = cls._extract_plain(cleaned, language, notes)
        is_partial = cls._is_partial(plain, language)
        return NormalizedOutput(
            candidates=[plain] if plain.strip() else [],
            source_format="plain",
            is_partial=is_partial,
            raw=raw,
            notes=notes,
        )

    # -----------------------------------------------------------------------
    # Strategy 1: Multi-candidate JSON
    # -----------------------------------------------------------------------

    @classmethod
    def _try_multi_candidate_json(
        cls, text: str, language: str, notes: List[str]
    ) -> List[str]:
        """Extract candidate_1 / candidate_2 / candidate_3 from JSON."""
        json_str = cls._extract_json_block(text)
        if not json_str:
            return []
        try:
            parsed = json.loads(json_str)
        except json.JSONDecodeError:
            return []

        candidates = []
        for key in sorted(parsed.keys()):
            if key.startswith("candidate_"):
                code = str(parsed[key])
                code = cls._unescape(code)
                code = cls._strip_fences(code)
                code = cls._strip_prose_lines(code)
                if code.strip():
                    candidates.append(code.strip())

        if candidates:
            notes.append(f"Extracted {len(candidates)} multi-candidate JSON block(s)")
        return candidates

    # -----------------------------------------------------------------------
    # Strategy 2: Single JSON (fixed_code key or largest string value)
    # -----------------------------------------------------------------------

    @classmethod
    def _try_single_json(
        cls, text: str, language: str, notes: List[str]
    ) -> Optional[str]:
        """Extract a single code block from JSON with fixed_code or similar key."""
        json_str = cls._extract_json_block(text)
        if not json_str:
            return None
        try:
            parsed = json.loads(json_str)
        except json.JSONDecodeError:
            # Fallback: regex extraction of fixed_code value
            m = re.search(
                r'"(?:fixed_code|code|patch|solution)"\s*:\s*"(.*?)(?:"(?:\s*[,}])|$)',
                text, re.DOTALL
            )
            if m:
                code = cls._unescape(m.group(1))
                code = cls._strip_fences(code).strip()
                if code:
                    notes.append("Extracted fixed_code via regex fallback")
                    return code
            return None

        # Check known code keys
        for key in ("fixed_code", "code", "patch", "solution", "fixed", "repair"):
            if key in parsed:
                code = str(parsed[key])
                code = cls._unescape(code)
                code = cls._strip_fences(code)
                code = cls._strip_prose_lines(code)
                if code.strip():
                    notes.append(f"Extracted '{key}' from JSON")
                    return code.strip()

        # Last resort: find the longest string value in the dict
        longest_key, longest_val = "", ""
        for k, v in parsed.items():
            if isinstance(v, str) and len(v) > len(longest_val):
                longest_key, longest_val = k, v
        if longest_val and len(longest_val) > 30:
            code = cls._unescape(longest_val)
            code = cls._strip_fences(code).strip()
            if code:
                notes.append(f"Used longest JSON string value under key '{longest_key}'")
                return code

        return None

    # -----------------------------------------------------------------------
    # Strategy 3: Markdown fenced blocks
    # -----------------------------------------------------------------------

    @classmethod
    def _try_fenced_blocks(
        cls, text: str, language: str, notes: List[str]
    ) -> List[str]:
        """Extract all ``` fenced code blocks from the response."""
        # Match fenced blocks with optional language tag
        pattern = re.compile(
            r'```(?:' + re.escape(language) + r'|cpp|c\+\+|java|python|py|)?\s*\n'
            r'(.*?)'
            r'```',
            re.DOTALL | re.IGNORECASE,
        )
        matches = pattern.findall(text)

        # Also try single-backtick blocks for very short snippets (rare)
        if not matches:
            # Try any language tag
            generic = re.compile(r'```\w*\s*\n(.*?)```', re.DOTALL)
            matches = generic.findall(text)

        results = []
        for m in matches:
            code = m.strip()
            code = cls._strip_prose_lines(code)
            if code:
                results.append(code)

        if results:
            notes.append(f"Extracted {len(results)} fenced code block(s)")
        return results

    # -----------------------------------------------------------------------
    # Strategy 4: Plain text fallback
    # -----------------------------------------------------------------------

    @classmethod
    def _extract_plain(
        cls, text: str, language: str, notes: List[str]
    ) -> str:
        """
        Strip prose lines and return whatever code-like content remains.
        Used as a last resort when no structured format is detected.
        """
        # Remove any JSON fragments
        text = re.sub(r'^\s*\{[^}]*\}\s*$', '', text, flags=re.MULTILINE)
        # Remove any markdown fence markers
        text = cls._strip_fences(text)
        # Remove prose prefix lines
        text = cls._strip_prose_lines(text)
        if text.strip():
            notes.append("Used plain text extraction fallback")
        return text.strip()

    # -----------------------------------------------------------------------
    # Partial patch detection
    # -----------------------------------------------------------------------

    @classmethod
    def _is_partial(cls, code: str, language: str) -> bool:
        """
        Heuristically determine if `code` is a partial patch (function snippet)
        rather than a complete file.

        A patch is partial if it:
          - Contains only function(s) but no imports/includes
          - Is very short relative to what a complete file would look like
          - Doesn't contain a main entry point
          - Contains leading/trailing ellipsis or "# ..." markers
        """
        if not code or not code.strip():
            return False

        code_stripped = code.strip()

        # Ellipsis markers are definitive partials
        if "..." in code_stripped[:50] or "# ..." in code_stripped or "/* ... */" in code_stripped:
            return True

        if language == "python":
            # Complete files usually have imports at the top or a main block
            has_import = bool(re.search(r'^(?:import|from)\s+\w', code_stripped, re.MULTILINE))
            has_main = 'if __name__' in code_stripped
            has_class = bool(re.search(r'^class\s+\w', code_stripped, re.MULTILINE))
            has_func = bool(re.search(r'^def\s+\w', code_stripped, re.MULTILINE))
            # If it only has function defs and no imports/main, treat as partial
            if has_func and not has_import and not has_main and not has_class:
                # Could be partial — check if it's short enough
                if len(code_stripped.splitlines()) < 30:
                    return True
            return False

        elif language == "java":
            has_class = bool(re.search(r'\bclass\s+\w', code_stripped))
            has_package = bool(re.search(r'^package\s+\w', code_stripped, re.MULTILINE))
            has_import = bool(re.search(r'^import\s+\w', code_stripped, re.MULTILINE))
            # Partial: method without class wrapper
            if not has_class and bool(re.search(r'\b(?:public|private|protected|static)\b.*\(', code_stripped)):
                return True
            return False

        elif language == "cpp":
            has_include = bool(re.search(r'^#include', code_stripped, re.MULTILINE))
            has_main = bool(re.search(r'\bmain\s*\(', code_stripped))
            # Partial: function without includes or main
            if not has_include and not has_main:
                return True
            return False

        return False

    # -----------------------------------------------------------------------
    # Helpers
    # -----------------------------------------------------------------------

    @staticmethod
    def _strip_sentinels(text: str) -> str:
        """Remove BOS/EOS tokens injected by some LLMs."""
        text = re.sub(r'<[?/]?begin[^>]*of[^>]*sentence[^>]*>', '', text, flags=re.IGNORECASE)
        text = re.sub(r'<\|[^|>]+\|>', '', text)
        text = re.sub(r'<\?[^>]*\?>', '', text)
        text = re.sub(r'<(s|/s|pad|bos|eos|unk|sep|cls|mask)>', '', text, flags=re.IGNORECASE)
        return text

    @staticmethod
    def _strip_fences(text: str) -> str:
        """Remove ``` markers from text."""
        text = re.sub(r'```\w*\s*\n?', '', text)
        text = text.replace('```', '')
        return text

    @classmethod
    def _strip_prose_lines(cls, code: str) -> str:
        """
        Remove lines that are clearly prose explanations rather than code.
        Keeps all lines that look like code.
        """
        lines = code.splitlines()
        clean = []
        for line in lines:
            stripped = line.strip().lower()
            if not stripped:
                clean.append(line)
                continue
            # Keep if it starts with a code indicator
            if stripped.startswith(("#", "//", "/*", "*", "import", "from",
                                    "def ", "class ", "public", "private",
                                    "protected", "static", "int ", "void ",
                                    "return", "if ", "for ", "while ",
                                    "include", "#include", "package",
                                    "{", "}", ";")):
                clean.append(line)
                continue
            # Drop if it starts with a known prose prefix
            is_prose = any(stripped.startswith(p) for p in cls._PROSE_PREFIXES)
            if not is_prose:
                clean.append(line)

        return "\n".join(clean)

    @staticmethod
    def _unescape(text: str) -> str:
        """Decode common JSON escape sequences."""
        return (text
                .replace("\\n", "\n")
                .replace("\\t", "\t")
                .replace('\\"', '"')
                .replace("\\'", "'")
                .replace("\\\\", "\\"))

    @staticmethod
    def _extract_json_block(text: str) -> str:
        """Extract the first balanced JSON object from text."""
        start = text.find('{')
        if start == -1:
            return ""
        depth = 0
        in_string = False
        escape_next = False
        for i, ch in enumerate(text[start:], start):
            if escape_next:
                escape_next = False
                continue
            if ch == '\\' and in_string:
                escape_next = True
                continue
            if ch == '"':
                in_string = not in_string
                continue
            if in_string:
                continue
            if ch == '{':
                depth += 1
            elif ch == '}':
                depth -= 1
                if depth == 0:
                    return text[start:i + 1]
        return ""
