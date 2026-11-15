import os


class LanguageDetector:

    EXTENSION_MAP = {
        ".py":   "python",
        ".cpp":  "cpp",
        ".cc":   "cpp",
        ".cxx":  "cpp",
        ".c++":  "cpp",
        ".java": "java",
        ".js":   "javascript",
    }

    # Languages that actually have an executor. ".js" is recognised for
    # diagnostics only; nothing can run or repair it yet.
    SUPPORTED = ("python", "cpp", "java")

    @staticmethod
    def detect(file_path: str, quiet: bool = False) -> str:
        """Detect language from the file extension.

        Uses the real extension (case-insensitive) rather than a suffix scan.
        Pass ``quiet=True`` to suppress the diagnostic line for internal calls.
        """
        ext = os.path.splitext(str(file_path))[1].lower()
        lang = LanguageDetector.EXTENSION_MAP.get(ext)
        if lang:
            if not quiet:
                print(f"[Language] Detected {lang.upper()} for: {file_path}")
            return lang

        if not quiet:
            print(f"[Language] WARNING: could not detect language for: {file_path}")
        return "unknown"

    @staticmethod
    def is_supported(file_path: str) -> bool:
        return LanguageDetector.detect(file_path, quiet=True) in LanguageDetector.SUPPORTED

    @staticmethod
    def supported_extensions() -> list:
        return sorted(
            ext for ext, lang in LanguageDetector.EXTENSION_MAP.items()
            if lang in LanguageDetector.SUPPORTED
        )
