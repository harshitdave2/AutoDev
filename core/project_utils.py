import os

def find_project_root(script_path: str) -> str:
    """
    Detects the root directory of the project.
    For this tool, we use the directory containing the entry script as the project root.
    """
    if not script_path:
        return os.getcwd()
    return os.path.dirname(os.path.abspath(script_path))

def resolve_patch_target(project_root: str, script_path: str, error_file: str) -> str:
    """
    Computes the correct file to patch given an error file and the project root.
    Returns `script_path` if the error file is outside the project root
    or if it matches known system/library paths.
    """
    if not error_file:
        return script_path

    # Protect against patching system or external libraries
    external_libraries = ["site-packages", "dist-packages", "/usr/lib", "\\usr\\lib", "python/lib", "python\\lib"]
    for ext_lib in external_libraries:
        if ext_lib in error_file:
            return script_path

    # Resolve the potentially relative error file against the project root
    full_path = os.path.normpath(os.path.join(project_root, error_file))

    # Verify that the full path actually exists
    if not os.path.exists(full_path):
        return script_path

    # Verify that the full path is within the project root
    try:
        common_path = os.path.commonpath([full_path, project_root])
        if common_path != project_root:
            return script_path
    except ValueError:
        return script_path

    return full_path
