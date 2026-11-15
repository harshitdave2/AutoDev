from languages.language_detector import LanguageDetector


class UnsupportedLanguageError(ValueError):
    """Raised when a source file has no executor.

    Subclasses ValueError so callers can handle it as a user-input problem
    instead of an unexpected crash.
    """


class LanguageRouter:

    @staticmethod
    def route(file_path: str):

        lang = LanguageDetector.detect(file_path, quiet=True)

        if lang == "python":
            from languages.python_lang.python_executor import PythonExecutor
            return PythonExecutor()

        elif lang == "cpp":
            from languages.cpp_lang.cpp_executor import CppExecutor
            return CppExecutor()

        elif lang == "java":
            from languages.java_lang.java_executor import JavaExecutor
            return JavaExecutor()

        raise UnsupportedLanguageError(
            f"Unsupported language for file: {file_path} "
            f"(supported extensions: {', '.join(LanguageDetector.supported_extensions())})"
        )
