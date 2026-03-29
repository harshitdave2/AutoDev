import shutil
import os
import ast

def validate_python_syntax(code: str) -> bool:
    """
    Ensures the AI generated code is valid Python.
    """
    try:
        ast.parse(code)
        return True
    except SyntaxError:
        return False


def validate_patch_integrity(original_code: str, patched_code: str) -> bool:
    """
    Prevents catastrophic patches where the model deletes most of the file.
    """

    original_len = len(original_code.strip())
    patched_len = len(patched_code.strip())

    if original_len == 0:
        return False

    ratio = patched_len / original_len

    # Reject patches that remove too much content
    if ratio < 0.4:
        return False

    return True

def backup_file(file_path: str) -> str:
    """
    Creates a backup of the specified file by appending '.backup' to its name.

    Args:
        file_path (str): The path to the file to backup.

    Returns:
        str: The path to the newly created backup file.
    """
    backup_path = file_path + ".backup"
    shutil.copy2(file_path, backup_path)
    return backup_path


def apply_patch(file_path: str, original_code: str, patched_code: str):

    with open(file_path, "r", encoding="utf-8") as f:
        full_code = f.read()

    # ---------- PATCH SAFETY CHECKS ----------

    is_python = file_path.endswith(".py")

    if is_python:
        if not validate_patch_integrity(original_code, patched_code):
            raise Exception("Patch rejected: file integrity check failed.")

    language_is_python = file_path.endswith(".py")
    if language_is_python and not validate_python_syntax(patched_code):
        raise Exception("Patch rejected: syntax error detected.")

    # ---------- APPLY PATCH ----------

    if original_code in full_code:
        new_full_code = full_code.replace(original_code, patched_code)
    else:
        raise Exception("Patch rejected: original code not found in file.")

    with open(file_path, "w", encoding="utf-8") as f:
        f.write(new_full_code)