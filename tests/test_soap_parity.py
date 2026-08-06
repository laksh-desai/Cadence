"""Parity guard: evals/soap.py must stay identical to app.js's SOAP_RULES.

The SOAP classifier is authored in JavaScript (app/ui/static/app.js) because it runs in the
browser for the "Copy for Office Ally" control. evals/soap.py ports it so the eval harness can
score bucketing offline. A rule list duplicated across two languages silently drifts, so this
test parses the array back out of app.js and asserts the two agree.

If this fails, the JS is the source of truth: update evals/soap.py to match it.

    .venv/bin/python -m unittest tests.test_soap_parity -v
"""

import re
import unittest
from pathlib import Path

from evals.soap import SOAP_LABELS, SOAP_RULES, soap_block_for

APP_JS = Path(__file__).resolve().parent.parent / "app" / "ui" / "static" / "app.js"

_BLOCK_RE = re.compile(r"const SOAP_RULES\s*=\s*\[(.*?)\n\s*\];", re.DOTALL)
_PAIR_RE = re.compile(r'\[\s*"([^"]+)"\s*,\s*"([SOAP])"\s*\]')
_LABELS_RE = re.compile(r"const SOAP_LABELS\s*=\s*\{(.*?)\};", re.DOTALL)


def _js_rules() -> list[tuple[str, str]]:
    m = _BLOCK_RE.search(APP_JS.read_text(encoding="utf-8"))
    if not m:
        raise AssertionError("could not find the SOAP_RULES array in app.js")
    # Strip // comments so a commented-out example pair can't be mistaken for a rule.
    body = re.sub(r"//[^\n]*", "", m.group(1))
    return [(kw, blk) for kw, blk in _PAIR_RE.findall(body)]


class SoapParityTests(unittest.TestCase):
    def test_rule_lists_are_identical(self):
        self.assertEqual(
            _js_rules(), SOAP_RULES,
            "evals/soap.py has drifted from app.js's SOAP_RULES — update the Python port",
        )

    def test_rule_order_is_preserved(self):
        # Order is load-bearing: the first substring hit wins, so the disambiguators
        # ("response to treatment" -> A) must precede the generics ("treatment" -> O).
        js = _js_rules()
        self.assertEqual([k for k, _ in js], [k for k, _ in SOAP_RULES])

    def test_labels_match(self):
        m = _LABELS_RE.search(APP_JS.read_text(encoding="utf-8"))
        self.assertIsNotNone(m)
        js_labels = dict(re.findall(r'(\w+)\s*:\s*"([^"]+)"', m.group(1)))
        self.assertEqual(js_labels, SOAP_LABELS)


class SoapClassifierTests(unittest.TestCase):
    def test_disambiguators_beat_generics(self):
        # These are the exact cases the JS comment calls out as order-dependent.
        self.assertEqual(soap_block_for("Response to Treatment"), "A")
        self.assertEqual(soap_block_for("Musculoskeletal Assessment"), "O")
        self.assertEqual(soap_block_for("Functional Status"), "A")
        self.assertEqual(soap_block_for("Functional Mobility / Gait"), "O")

    def test_goals_split_between_plan_and_subjective(self):
        self.assertEqual(soap_block_for("Short-Term Goals"), "P")
        self.assertEqual(soap_block_for("Patient Goals"), "S")

    def test_treatment_sections_are_objective(self):
        for heading in ["Therapeutic Exercise", "Gait Training", "Manual Therapy"]:
            with self.subTest(heading=heading):
                self.assertEqual(soap_block_for(heading), "O")

    def test_unmatched_defaults_to_objective(self):
        self.assertEqual(soap_block_for("Something Entirely Novel"), "O")

    def test_empty_heading_does_not_raise(self):
        self.assertEqual(soap_block_for(""), "O")
        self.assertEqual(soap_block_for(None), "O")


if __name__ == "__main__":
    unittest.main()
