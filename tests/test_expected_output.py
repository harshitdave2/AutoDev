import unittest

from core.expected_output import normalize_output, output_matches


class ExpectedOutputTests(unittest.TestCase):
    def test_line_endings_and_final_newlines_are_normalized(self):
        self.assertEqual(normalize_output("ok\\r\\n"), "ok")
        self.assertEqual(normalize_output("one\\r\\ntwo\\r"), "one\\ntwo")

    def test_other_whitespace_is_preserved(self):
        self.assertNotEqual(normalize_output("value \\n"), normalize_output("value\\n"))

    def test_exact_output_oracle_matches(self):
        self.assertTrue(output_matches("answer\\r\\n", "answer"))
        self.assertFalse(output_matches("answer with extra", "answer"))


if __name__ == "__main__":
    unittest.main()
