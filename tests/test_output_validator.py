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


if __name__ == "__main__":
    unittest.main()
