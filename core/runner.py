import os
import subprocess
import sys

from languages.language_router import LanguageRouter
from languages.language_detector import LanguageDetector


def sanitize_cpp_source(file_path: str):
    """
    Remove non-ASCII characters (emoji, box chars) that break C++ compilers.
    """

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            code = f.read()

        cleaned = code.encode("ascii", "ignore").decode()

        if cleaned != code:
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(cleaned)

    except Exception:
        pass


def run_script(script_path: str) -> dict:
    """
    Routes execution to the correct language executor.
    """

    language = LanguageDetector.detect(script_path)

    # Pre-sanitize C++ source
    if language == "cpp":
        sanitize_cpp_source(script_path)

    executor = LanguageRouter.route(script_path)

    return executor.execute(script_path)