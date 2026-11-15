"""
core/heuristic_fixes.py
-----------------------
Lightweight deterministic repair layer — runs BEFORE any LLM call.

If a deterministic fix succeeds, the LLM is never invoked.

Checks (safe, narrow rewrites only):
  1. Dictionary mutation during iteration
  2. Index out-of-bounds (bounds guard)
  3. NoneType dereference (None guard)
  4. Unbalanced braces / brackets (C++, Java)
  5. Missing semicolons (C++, Java)
  6. Off-by-one range(len(x)+1) → range(len(x)) (Python)

Division-by-zero failures are intentionally not rewritten: choosing a fallback
value changes program semantics and must be guided by tests or the model.
"""
import re


def heuristic_repair(code: str, error_type: str, error_message: str) -> str:
    """
    Lightweight deterministic repair layer before LLM invocation.

    Returns the (possibly modified) code. If nothing was changed, returns
    the original code unchanged so the caller can skip LLM if desired.
    """
    if not code:
        return code

    original = code
    msg = (str(error_type) + " " + str(error_message)).lower()
    applied: list[str] = []

    # ------------------------------------------------------------------
    # 1. Dictionary changed size during iteration
    # ------------------------------------------------------------------
    if "dictionary changed size" in msg:
        before = code
        code = re.sub(r'in\s+([a-zA-Z0-9_.]+)\.items\(\)\s*:', r'in list(\1.items()):', code)
        code = re.sub(r'in\s+([a-zA-Z0-9_.]+)\.keys\(\)\s*:', r'in list(\1.keys()):', code)
        code = re.sub(r'in\s+([a-zA-Z0-9_.]+)\.values\(\)\s*:', r'in list(\1.values()):', code)
        if code != before:
            applied.append("dict-iteration-guard")

    # ------------------------------------------------------------------
    # 2. Division by zero
    # ------------------------------------------------------------------
    # No automatic fallback is safe here: choosing 0, None, or an exception
    # changes program semantics and cannot be inferred from the traceback.
    # ------------------------------------------------------------------
    # 3. Index error → bounds check (Python)
    # ------------------------------------------------------------------
    if "index error" in msg or "indexerror" in msg or "out of bounds" in msg:
        before = code
        code = re.sub(
            r'\b([a-zA-Z0-9_]+)\[([a-zA-Z0-9_]+)\]',
            r'(\1[\2] if \2 < len(\1) else None)',
            code
        )
        if code != before:
            applied.append("index-bounds-guard")

    # ------------------------------------------------------------------
    # 4. NoneType / NullPointerException
    # ------------------------------------------------------------------
    if "nonetype" in msg or "null pointer" in msg or "nullpointerexception" in msg:
        before = code
        code = re.sub(
            r'\b([a-zA-Z0-9_]+)\.([a-zA-Z0-9_]+)\(',
            r'(\1.\2( if \1 is not None else None)',
            code
        )
        if code != before:
            applied.append("none-dereference-guard")

    # ------------------------------------------------------------------
    # 5. Off-by-one: range(len(x) + 1) → range(len(x))  (Python only)
    # ------------------------------------------------------------------
    if "indexerror" in msg or "index error" in msg or "out of range" in msg:
        before = code
        code = re.sub(
            r'range\(\s*len\(([a-zA-Z0-9_.]+)\)\s*\+\s*1\s*\)',
            r'range(len(\1))',
            code
        )
        if code != before:
            applied.append("off-by-one-range")

    # ------------------------------------------------------------------
    # 6. Unbalanced braces — C++/Java only (add missing closing brace)
    # ------------------------------------------------------------------
    if "syntaxerror" in msg or "expected '}'" in msg or "missing }" in msg:
        before = code
        open_b = code.count("{")
        close_b = code.count("}")
        if open_b > close_b:
            code = code.rstrip() + "\n" + ("}" * (open_b - close_b)) + "\n"
            if code != before:
                applied.append("missing-closing-brace")

    # ------------------------------------------------------------------
    # 7. Missing semicolon on last statement (C++/Java simple heuristic)
    # ------------------------------------------------------------------
    # Only for languages where last non-blank line ends with an identifier/paren
    # but lacks a semicolon (and the file looks like C++/Java by #include or class)
    if "#include" in code or ("class " in code and "def " not in code):
        lines = code.splitlines()
        changed = False
        for i, line in enumerate(lines):
            stripped = line.rstrip()
            if stripped and not stripped.endswith((";", "{", "}", "//", "*/", ")")):
                # Check: it's a statement-like line (contains assignment or function call)
                if re.search(r'[a-zA-Z0-9_]\s*[=\(]', stripped) and not stripped.startswith("//"):
                    lines[i] = stripped + ";"
                    changed = True
                    break  # Only fix the first occurrence to avoid cascade
        if changed:
            code = "\n".join(lines)
            applied.append("missing-semicolon")

    # ------------------------------------------------------------------
    # Logging
    # ------------------------------------------------------------------
    if applied:
        print(f"[HeuristicFix] applied: {', '.join(applied)}")
    else:
        if code != original:
            print("[HeuristicFix] applied (unnamed change)")
        else:
            print("[HeuristicFix] skipped — no deterministic fix matched")

    return code
