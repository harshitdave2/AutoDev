class LanguageDetector:

    EXTENSION_MAP = {
        ".py": "python",
        ".cpp": "cpp",
        ".cc": "cpp",
        ".cxx": "cpp",
        ".js": "javascript"
    }

    @staticmethod
    def detect(file_path: str) -> str:

        for ext, lang in LanguageDetector.EXTENSION_MAP.items():
            if file_path.endswith(ext):
                return lang

        return "unknown"