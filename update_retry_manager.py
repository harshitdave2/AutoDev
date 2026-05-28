import re
import os

filepath = r"d:\AUTODEV\autodev\agent\retry_manager.py"

with open(filepath, "r", encoding="utf-8") as f:
    content = f.read()

# Replace backup restore logic
old_backup_restore = """                        if backup_path and os.path.exists(backup_path):
                            shutil.copy2(backup_path, script_path)"""

new_backup_restore = """                        for bp in backup_paths:
                            if os.path.exists(bp):
                                shutil.copy2(bp, bp[:-7])"""

content = content.replace(old_backup_restore, new_backup_restore)

old_backup_restore2 = """                            if backup_path and os.path.exists(backup_path):
                                shutil.copy2(backup_path, script_path)"""
new_backup_restore2 = """                            for bp in backup_paths:
                                if os.path.exists(bp):
                                    shutil.copy2(bp, bp[:-7])"""
content = content.replace(old_backup_restore2, new_backup_restore2)

old_backup_restore3 = """        if backup_path and os.path.exists(backup_path):
            shutil.copy2(backup_path, script_path)"""
new_backup_restore3 = """        for bp in backup_paths:
            if os.path.exists(bp):
                shutil.copy2(bp, bp[:-7])"""
content = content.replace(old_backup_restore3, new_backup_restore3)

# Replace local file reading logic
old_file_read = """                with open(script_path, "r", encoding="utf-8") as f:
                    full_code = f.read()"""

new_file_read = """                with open(script_path, "r", encoding="utf-8") as f:
                    entry_code = f.read()
                
                with open(patch_target, "r", encoding="utf-8") as f:
                    full_code = f.read()"""

content = content.replace(old_file_read, new_file_read)

# Replace primary extraction line if tb['line'] exists
old_extract_context = """                    primary = self._extract_context(script_path, tb["line"])"""
new_extract_context = """                    primary = self._extract_context(patch_target, tb["line"])"""
content = content.replace(old_extract_context, new_extract_context)

# Replace request_fix calls to include entry_file
old_request_fix = """                            patch_candidates = self.agent.request_fix(
                                error_info=tb,
                                code_context=primary,
                                language=language,
                                caller_context=caller,
                                full_file_mode=is_last,
                                full_file_content=old_code if is_last else ""
                            )"""

new_request_fix = """                            patch_candidates = self.agent.request_fix(
                                error_info=tb,
                                code_context=primary,
                                language=language,
                                caller_context=caller,
                                full_file_mode=is_last,
                                full_file_content=old_code if is_last else "",
                                entry_file=script_path,
                                error_file=patch_target,
                                entry_code=entry_code
                            )"""
content = content.replace(old_request_fix, new_request_fix)


old_cloud_request_fix = """                    cloud_candidates = cloud_agent.request_fix(
                        error_info=tb,
                        code_context=full_code,
                        language=language,
                        caller_context="",
                        full_file_mode=True,
                        full_file_content=full_code
                    )"""

new_cloud_request_fix = """                    cloud_candidates = cloud_agent.request_fix(
                        error_info=tb,
                        code_context=full_code,
                        language=language,
                        caller_context="",
                        full_file_mode=True,
                        full_file_content=full_code,
                        entry_file=script_path,
                        error_file=patch_target,
                        entry_code=entry_code
                    )"""
content = content.replace(old_cloud_request_fix, new_cloud_request_fix)

# Replace target_file usage for patch candidate writing
old_write_candidate = """                        if is_last:
                            target_file = tb["file"] if tb.get("file") else script_path
                            with open(target_file, "w", encoding="utf-8") as f:
                                f.write(candidate)
                        else:
                            apply_patch(tb["file"], old_code, candidate)"""

new_write_candidate = """                        if is_last:
                            with open(patch_target, "w", encoding="utf-8") as f:
                                f.write(candidate)
                        else:
                            apply_patch(patch_target, old_code, candidate)"""
content = content.replace(old_write_candidate, new_write_candidate)

# Replace write candidate for cloud escalation
old_cloud_write = """                            with open(script_path, "w", encoding="utf-8") as f:
                                f.write(patch)"""
new_cloud_write = """                            with open(patch_target, "w", encoding="utf-8") as f:
                                f.write(patch)"""
content = content.replace(old_cloud_write, new_cloud_write)

with open(filepath, "w", encoding="utf-8") as f:
    f.write(content)

print("Updated retry_manager.py successfully.")
