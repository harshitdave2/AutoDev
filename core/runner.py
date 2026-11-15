"""Language-aware execution entry point."""
from languages.language_router import LanguageRouter
from languages.language_detector import LanguageDetector


def run_script(script_path: str) -> dict:
    """Execute a source file without mutating it as a side effect."""
    language = LanguageDetector.detect(script_path)
    executor = LanguageRouter.route(script_path)
    result = executor.execute(script_path)
    result.setdefault("language", language)
    return result
