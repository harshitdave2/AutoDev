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

    @staticmethod
    def detect(file_path: str) -> str:
        """Detect language from file extension and emit a diagnostic log."""
        for ext, lang in LanguageDetector.EXTENSION_MAP.items():
            if file_path.lower().endswith(ext):
                print(f"[Language] Detected {lang.upper()} for: {file_path}")
                return lang

        print(f"[Language] WARNING: could not detect language for: {file_path}")
        return "unknown"