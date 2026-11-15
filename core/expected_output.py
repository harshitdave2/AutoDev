"""Exact stdout-oracle helpers shared by AutoDev and the benchmark runner."""


def normalize_output(value: str) -> str:
    """Normalize line endings and final newlines while preserving other whitespace."""
    if not isinstance(value, str):
        raise TypeError("program output must be a string")
    return value.replace("\r\n", "\n").replace("\r", "\n").rstrip("\n")


def output_matches(actual: str, expected: str) -> bool:
    """Compare captured stdout against an explicitly supplied expected result."""
    return normalize_output(actual) == normalize_output(expected)
