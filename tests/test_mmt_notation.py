"""Tests for the deterministic MMT strength-grade normalizer in postprocess.

The model routinely echoes the spoken long form of a manual muscle test grade
("three plus to four minus out of five") instead of the clinical shorthand the prompt
asks for ("3+/5 to 4-/5"). `normalize_strength_grades` fixes that after parsing. The
transform is deliberately bounded to a denominator of FIVE so it can never corrupt a
pain rating ("4 out of 10") or any other "out of N" phrase -- those negative cases are
the load-bearing tests here.

    .venv/Scripts/python.exe -m unittest tests.test_mmt_notation -v
"""

import unittest

from app.generate.postprocess import normalize_strength_grades


def _body(text):
    """Run one section body through the normalizer and return the result body."""
    return normalize_strength_grades([{"heading": "Musculoskeletal", "body": text, "carried_forward": False}])[0]["body"]


class ConvertsSpokenGradesTests(unittest.TestCase):
    def test_single_plain(self):
        self.assertEqual(_body("quad strength four out of five"), "quad strength 4/5")

    def test_single_with_plus(self):
        self.assertEqual(_body("three plus out of five"), "3+/5")

    def test_single_with_minus(self):
        self.assertEqual(_body("grip four minus out of five"), "grip 4-/5")

    def test_range_with_modifiers(self):
        self.assertEqual(_body("MMT three plus to four minus out of five"), "MMT 3+/5 to 4-/5")

    def test_range_plain(self):
        self.assertEqual(_body("hip flexors three to four out of five"), "hip flexors 3/5 to 4/5")

    def test_grossly_five(self):
        self.assertEqual(_body("right leg grossly five out of five"), "right leg grossly 5/5")

    def test_multiple_in_one_body(self):
        self.assertEqual(
            _body("quad three plus out of five; hamstring four out of five"),
            "quad 3+/5; hamstring 4/5",
        )

    def test_digit_form_out_of_5(self):
        self.assertEqual(_body("4 out of 5"), "4/5")


class DoesNotCorruptOtherNumbersTests(unittest.TestCase):
    """The dangerous failure mode: silently rewriting a non-MMT value."""

    def test_pain_out_of_ten_untouched(self):
        self.assertEqual(_body("pain four out of ten"), "pain four out of ten")

    def test_pain_out_of_10_untouched(self):
        self.assertEqual(_body("pain 4 out of 10 at rest"), "pain 4 out of 10 at rest")

    def test_existing_shorthand_untouched(self):
        self.assertEqual(_body("quad 3+/5, hamstring 4/5"), "quad 3+/5, hamstring 4/5")

    def test_unrelated_prose_untouched(self):
        text = "Patient walked 200 ft with a walker and reported no pain."
        self.assertEqual(_body(text), text)

    def test_hyphenated_word_form_is_left_alone_not_mangled(self):
        # "three-plus out of five" isn't matched -- acceptable miss, but it must never
        # be silently half-converted into something wrong.
        out = _body("three-plus out of five")
        self.assertNotIn("/5/5", out)
        self.assertNotIn("+-", out)


class IntegratesWithApplyTests(unittest.TestCase):
    def test_apply_runs_the_normalizer(self):
        from app.generate import postprocess

        sections = [{"heading": "Musculoskeletal Assessment", "body": "quad four out of five", "carried_forward": False}]
        out = postprocess.apply("initial", sections)
        self.assertEqual(out[0]["body"], "quad 4/5")


if __name__ == "__main__":
    unittest.main()
