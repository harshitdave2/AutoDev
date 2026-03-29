import ast
import re


class OutputValidator:

    @staticmethod
    def extract_lists(stdout: str):
        """
        Extract all Python lists from stdout text.
        Example:
        'Normalized: [0,0,0]' → [0,0,0]
        """

        matches = re.findall(r"\[[^\]]+\]", stdout)

        lists = []

        for m in matches:
            try:
                parsed = ast.literal_eval(m)
                if isinstance(parsed, list):
                    lists.append(parsed)
            except:
                pass

        return lists


    @staticmethod
    def detect_uniform_array(stdout: str):

        lists = OutputValidator.extract_lists(stdout)

        for arr in lists:

            if len(arr) > 1:

                first = arr[0]

                if all(v == first for v in arr):
                    return True

        return False


    @staticmethod
    def detect_none_flood(stdout: str):

        lines = [l.strip() for l in stdout.splitlines() if l.strip()]

        if not lines:
            return False

        return len(lines) >= 5 and all(l == "None" for l in lines)

    @staticmethod
    def detect_short_output(stdout: str):

        stripped = stdout.strip()

        # only treat completely empty output as suspicious
        if stripped == "":
            return True

        return False

    @staticmethod
    def detect_numeric_overflow(stdout: str):

        import re

        numbers = re.findall(r"-?\d+", stdout)

        for n in numbers:

            try:
                val = int(n)

                # unrealistic large numbers
                if abs(val) > 1000000:
                    return True

            except:
                pass

        return False

    @classmethod
    def validate(cls, stdout: str, language: str = "python"):

        report = {
            "is_suspicious": False,
            "flags": [],
        }

        if cls.detect_none_flood(stdout):
            report["flags"].append("None Flood Detected")

        if cls.detect_uniform_array(stdout):
            report["flags"].append("Suspicious Uniform Array")

        if cls.detect_numeric_overflow(stdout):
            report["flags"].append("Unreasonable Numeric Output")

        report["is_suspicious"] = False

        return report