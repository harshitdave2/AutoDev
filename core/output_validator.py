"""Heuristic output checks.

These checks are advisory: without an expected-output oracle, unusual output
must not be treated as proof of a logic bug.
"""
import ast
import re
from typing import Any


class OutputValidator:
    @staticmethod
    def extract_lists(stdout: str) -> list[list[Any]]:
        """Extract Python list literals embedded in stdout."""
        if not isinstance(stdout, str):
            return []
        lists = []
        for match in re.finditer(r"\[[^\[\]\n]*\]", stdout):
            try:
                value = ast.literal_eval(match.group(0))
            except (ValueError, SyntaxError):
                continue
            if isinstance(value, list):
                lists.append(value)
        return lists

    @staticmethod
    def detect_uniform_array(stdout: str) -> bool:
        return any(len(values) > 1 and all(v == values[0] for v in values[1:])
                   for values in OutputValidator.extract_lists(stdout))

    @staticmethod
    def detect_none_flood(stdout: str) -> bool:
        lines = [line.strip() for line in stdout.splitlines() if line.strip()]
        return len(lines) >= 5 and all(line == "None" for line in lines)

    @staticmethod
    def detect_short_output(stdout: str) -> bool:
        """An empty output is detectable, but not inherently erroneous."""
        return not stdout.strip()

    @staticmethod
    def detect_numeric_overflow(stdout: str) -> bool:
        for number in re.findall(r"(?<![\w.])-?\d+(?![\w.])", stdout):
            try:
                if abs(int(number)) > 1_000_000:
                    return True
            except ValueError:
                continue
        return False

    @classmethod
    def validate(cls, stdout: str, language: str = "python") -> dict:
        if not isinstance(stdout, str):
            raise TypeError("stdout must be a string")

        flags = []
        if cls.detect_none_flood(stdout):
            flags.append("None Flood Detected")
        if cls.detect_uniform_array(stdout):
            flags.append("Suspicious Uniform Array")
        if cls.detect_numeric_overflow(stdout):
            flags.append("Unreasonable Numeric Output")

        # Short/empty output is not flagged by default: valid programs can be
        # intentionally silent, and the validator has no expected-output oracle.
        return {
            "is_suspicious": bool(flags),
            "flags": flags,
            "language": language,
        }
