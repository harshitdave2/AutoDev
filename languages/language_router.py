from languages.language_detector import LanguageDetector

class LanguageRouter:

    @staticmethod
    def route(file_path: str):

        lang = LanguageDetector.detect(file_path)

        if lang == "python":
            from languages.python_lang.python_executor import PythonExecutor
            return PythonExecutor()

        elif lang == "cpp":
            from languages.cpp_lang.cpp_executor import CppExecutor
            return CppExecutor()

        elif lang == "java" or file_path.endswith(".java"):
            from languages.java_lang.java_executor import JavaExecutor
            return JavaExecutor()

        else:
            raise Exception(f"Unsupported language for file: {file_path}")