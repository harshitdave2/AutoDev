import unittest

from core.output_validator import OutputValidator


class OutputValidatorTests(unittest.TestCase):
    def test_none_flood_sets_suspicious_and_flag(self):
        report = OutputValidator.validate("None\nNone\nNone\nNone\nNone\n")
        self.assertTrue(report["is_suspicious"])
        self.assertIn("None Flood Detected", report["flags"])

    def test_uniform_array_is_reported(self):
        report = OutputValidator.validate("result = [7, 7, 7]")
        self.assertTrue(report["is_suspicious"])
        self.assertIn("Suspicious Uniform Array", report["flags"])

    def test_large_integer_is_reported(self):
        report = OutputValidator.validate("total=1000001")
        self.assertTrue(report["is_suspicious"])
        self.assertIn("Unreasonable Numeric Output", report["flags"])

    def test_normal_output_is_not_suspicious(self):
        report = OutputValidator.validate("Total: 42\nDone")
        self.assertFalse(report["is_suspicious"])
        self.assertEqual(report["flags"], [])

    def test_empty_output_is_not_assumed_to_be_a_bug(self):
        report = OutputValidator.validate("")
        self.assertFalse(report["is_suspicious"])
        self.assertTrue(OutputValidator.detect_short_output(""))

    def test_rejects_non_string_output(self):
        with self.assertRaises(TypeError):
            OutputValidator.validate(None)

    def test_empty_output_is_not_a_logic_failure(self):
        report = OutputValidator.validate("")
        self.assertFalse(report["is_suspicious"])
        self.assertEqual(report["flags"], [])

    def test_advisory_helpers_handle_non_string_values(self):
        self.assertFalse(OutputValidator.detect_none_flood(None))
        self.assertTrue(OutputValidator.detect_short_output(None))

    def test_unhashable_literal_text_does_not_crash(self):
        # ast.literal_eval raises TypeError for text like [{{}}]; the validator
        # used to propagate it and crash the whole repair run.
        for text in ("x = [{{}}]", "x = [{{}: 1}]"):
            report = OutputValidator.validate(text)
            self.assertFalse(report["is_suspicious"])

    def test_numeric_helper_tolerates_non_string(self):
        self.assertFalse(OutputValidator.detect_numeric_overflow(None))

    def test_extremely_large_integer_is_still_reported(self):
        # int() refuses >4300-digit strings; those used to be silently skipped.
        report = OutputValidator.validate("n=" + "9" * 5000)
        self.assertIn("Unreasonable Numeric Output", report["flags"])

    def test_threshold_boundary(self):
        self.assertFalse(OutputValidator.detect_numeric_overflow("n=1000000"))
        self.assertTrue(OutputValidator.detect_numeric_overflow("n=1000001"))
        self.assertTrue(OutputValidator.detect_numeric_overflow("n=-1000001"))
        self.assertFalse(OutputValidator.detect_numeric_overflow("n=0000007"))


if __name__ == "__main__":
    unittest.main()
