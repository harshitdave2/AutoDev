import unittest
from core.heuristic_fixes import heuristic_repair


class HeuristicFixSafetyTests(unittest.TestCase):
    def test_zero_division_is_not_rewritten_to_a_silent_zero(self):
        code = "def ratio(value, divisor):\n    return value / divisor\n"

        repaired = heuristic_repair(code, "ZeroDivisionError", "division by zero")

        self.assertEqual(repaired, code)
        self.assertNotIn("else 0", repaired)

    def test_dictionary_iteration_fix_remains_available(self):
        code = "for key, value in records.items():\n    del records[key]\n"

        repaired = heuristic_repair(code, "RuntimeError", "dictionary changed size during iteration")

        self.assertIn("list(records.items())", repaired)


if __name__ == "__main__":
    unittest.main()
