"""
Patch retry_manager.py with all three pipeline-order fixes:
1. _validate_candidate: add patch_mode param
2. _detect_patch_mode: new helper method
3. Local loop: merge BEFORE validate
4. Cloud loop: merge BEFORE validate, remove duplicate size guard
"""

import re

path = 'd:/AUTODEV/autodev/agent/retry_manager.py'
content = open(path, 'r', encoding='utf-8').read()

# ─────────────────────────────────────────────────────────────
# CHANGE 1: _validate_candidate — add patch_mode param
# ─────────────────────────────────────────────────────────────
OLD_VALIDATE = '''    def _validate_candidate(
        self,
        candidate: str,
        original_code: str,
        language: str,
    ) -> tuple[bool, str]:
        """
        Run the full PatchValidator suite on a candidate.
        Returns (is_valid, reason).
        """
        ok, reason = PatchValidator.validate(candidate, original_code, language)
        if not ok:
            self.console.print(f"[yellow]! Patch validation failed: {reason}[/yellow]")
        return ok, reason'''

NEW_VALIDATE = '''    def _validate_candidate(
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
        return "full"'''

if OLD_VALIDATE in content:
    content = content.replace(OLD_VALIDATE, NEW_VALIDATE, 1)
    print('CHANGE 1: _validate_candidate updated OK')
else:
    print('CHANGE 1: WARNING — old signature not found (may already be updated)')

# ─────────────────────────────────────────────────────────────
# CHANGE 2: Local loop — move merge BEFORE validate
#
# Current (broken) block in the local loop:
#   [FunctionPatchMerger] partial check → merge
#   [SEMANTIC VALIDATION]
#   [STRUCTURAL GUARDS] (duplicate too-short guard that can fire after merge)
#
# New (correct):
#   detect patch mode
#   [if snippet] FunctionPatchMerger.merge → get merged code
#   [SEMANTIC VALIDATION] on merged code with correct mode
#   [STRUCTURAL GUARDS] simplified — only main() check, no too-short duplicate
# ─────────────────────────────────────────────────────────────

OLD_LOCAL = '''                    # ---- Phase 3: FunctionPatchMerger — handle partial patches ----
                    # Check if the candidate is a partial patch (function-only)
                    # BEFORE validation so we can merge it rather than reject it.
                    try:
                        _norm_check = ResponseNormalizer.normalize(candidate, language=language)
                        if _norm_check.is_partial:
                            self.console.print(
                                "[dim][FunctionPatchMerger] Partial patch detected — merging...[/dim]"
                            )
                            _merge_result = FunctionPatchMerger.merge(
                                original=original_code,
                                patch=candidate,
                                language=language,
                            )
                            if _merge_result.success:
                                candidate = _merge_result.merged_code
                                self.console.print(
                                    f"[dim][FunctionPatchMerger] Merged: "
                                    f"replaced={_merge_result.functions_replaced}, "
                                    f"added={_merge_result.functions_added}[/dim]"
                                )
                            else:
                                self.console.print(
                                    f"[dim][FunctionPatchMerger] Merge failed: "
                                    f"{_merge_result.reason} — keeping candidate as-is[/dim]"
                                )
                    except Exception as _fm_err:
                        self.console.print(f"[dim]FunctionPatchMerger error: {_fm_err}[/dim]")

                    # ---- SEMANTIC VALIDATION (Phase 1) ----
                    val_ok, val_reason = self._validate_candidate(candidate, original_code, language)
                    if not val_ok:
                        self.console.print(
                            f"[yellow]Candidate {candidate_idx + 1} rejected by validator: {val_reason}[/yellow]"
                        )
                        _adaptive.record_failure("semantic", val_reason)
                        continue

                    # ---- STRUCTURAL GUARDS (preserved + adaptive tracking) ----
                    try:
                        original_lines = original_code.strip().splitlines()
                        patched_lines = candidate.strip().splitlines()

                        if len(original_lines) > 10 and len(patched_lines) < len(original_lines) * 0.25:
                            # Before hard-rejecting, try to merge as partial patch
                            _too_short_merge = FunctionPatchMerger.merge(
                                original=original_code, patch=candidate, language=language
                            )
                            if _too_short_merge.success and not _too_short_merge.fallback_used:
                                self.console.print(
                                    "[dim][FunctionPatchMerger] Rescued short patch via merge[/dim]"
                                )
                                candidate = _too_short_merge.merged_code
                                patched_lines = candidate.strip().splitlines()
                            else:
                                _adaptive.record_failure("too_short", "Patch removed too much code")
                                raise ValueError("Patch removed too much code")

                        import difflib
                        ratio = difflib.SequenceMatcher(None, original_code, candidate).ratio()
                        if len(original_lines) > 10 and ratio < 0.4:
                            # Before hard-rejecting, try to merge
                            _rewrite_merge = FunctionPatchMerger.merge(
                                original=original_code, patch=candidate, language=language
                            )
                            if _rewrite_merge.success and not _rewrite_merge.fallback_used:
                                self.console.print(
                                    "[dim][FunctionPatchMerger] Rescued rewrite-heavy patch via merge[/dim]"
                                )
                                candidate = _rewrite_merge.merged_code
                            else:
                                _adaptive.record_failure("rewrite", "Patch rewrote too much code")
                                raise ValueError("Patch rewrote too much code")

                        if len(original_lines) > 10:
                            has_main_orig = "main(" in original_code
                            has_main_patch = "main(" in candidate or "main(void" in candidate
                            if has_main_orig and not has_main_patch:
                                # Try to rescue via merger before rejecting
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
                            if (\'if __name__ == "__main__"\' in original_code
                                    and \'if __name__ == "__main__"\' not in candidate):
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
                        continue'''

NEW_LOCAL = '''                    # ─── STEP 1: Detect patch mode ────────────────────────────────────
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
                    self.console.print(
                        f"[dim][Validator] Validating reconstructed full file (mode={_patch_mode})[/dim]"
                    )
                    val_ok, val_reason = self._validate_candidate(
                        candidate, original_code, language, patch_mode=_patch_mode
                    )
                    if not val_ok:
                        self.console.print(
                            f"[yellow]Candidate {candidate_idx + 1} rejected by validator: {val_reason}[/yellow]"
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
                            if (\'if __name__ == "__main__"\' in original_code
                                    and \'if __name__ == "__main__"\' not in candidate
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
                        continue'''

if OLD_LOCAL in content:
    content = content.replace(OLD_LOCAL, NEW_LOCAL, 1)
    print('CHANGE 2: Local loop pipeline order fixed OK')
else:
    print('CHANGE 2: WARNING — local loop block not found exactly, attempting partial match...')
    # Try locating by the key anchor
    anchor = '# ---- Phase 3: FunctionPatchMerger — handle partial patches ----'
    if anchor in content:
        print('  Anchor found — manual edit needed')
    else:
        print('  Anchor NOT found — content may have changed')

# ─────────────────────────────────────────────────────────────
# CHANGE 3: Cloud loop — add merge before validate, remove duplicate size guard
# ─────────────────────────────────────────────────────────────

OLD_CLOUD = '''                        # ---- SEMANTIC VALIDATION on cloud candidate ----
                        val_ok, val_reason = self._validate_candidate(patch, original_code, language)
                        if not val_ok:
                            self.console.print(
                                f"[yellow]Cloud candidate {c_idx + 1} rejected: {val_reason}[/yellow]"
                            )
                            continue

                        try:
                            original_lines = original_code.strip().splitlines()
                            patched_lines = patch.strip().splitlines()

                            if len(original_lines) > 10 and len(patched_lines) < len(original_lines) * 0.25:
                                raise ValueError("Cloud patch removed too much code")

                            import difflib
                            ratio = difflib.SequenceMatcher(None, original_code, patch).ratio()
                            if len(original_lines) > 10 and ratio < 0.4:
                                raise ValueError("Cloud patch rewrote too much code")

                            # Apply patch (full-file or function-level)'''

NEW_CLOUD = '''                        # ---- Detect patch mode & merge BEFORE validate (cloud) ----
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

                            # Apply patch (full-file or function-level)'''

if OLD_CLOUD in content:
    content = content.replace(OLD_CLOUD, NEW_CLOUD, 1)
    print('CHANGE 3: Cloud loop pipeline order fixed OK')
else:
    print('CHANGE 3: WARNING — cloud loop block not found exactly')

# Write result
open(path, 'w', encoding='utf-8').write(content)
print('retry_manager.py written successfully')
