"""The code-written Billing section and the pre-send billing audit (2026-10).

Medicare pays a timed code only with its minutes, and every daily note needs the total timed
minutes and the total treatment time. These tests pin the two halves: the section says exactly what
the dictation supports (and flags what it doesn't), and the audit catches what would not be paid.
"""

import unittest

from app.generate import billing, billing_section, note_audit

FULL = ("Gait training fifteen minutes with a rolling walker, contact guard. Neuromuscular "
        "re-education twelve minutes, tandem stance. Therapeutic exercise ten minutes, sit to "
        "stand. Total treatment time forty minutes.")


def _section(dictation, form_id="followup"):
    return billing_section.build(billing.extract(dictation), dictation, form_id)


def _sec(heading, body):
    return {"heading": heading, "body": body, "carried_forward": False}


class BillingSectionTests(unittest.TestCase):
    def test_codes_minutes_totals_and_units(self):
        body = _section(FULL)["body"]
        for expected in ("97116 Gait Training — confirm]] 15 min",
                         "97112 Neuromuscular Re-education — confirm]] 12 min",
                         "97110 Therapeutic Exercise — confirm]] 10 min",
                         "Total timed minutes: 37", "Total treatment time: 40 min",
                         "Units (8-minute rule): 2"):
            self.assertIn(expected, body)

    def test_missing_minutes_and_total_time_are_flagged_never_guessed(self):
        d = "Gait training with a walker. Therapeutic exercise, sit to stand."
        body = _section(d)["body"]
        self.assertIn("[[NEEDS: minutes for Gait Training", body)
        self.assertIn("[[NEEDS: total treatment time", body)
        self.assertNotIn("Total timed minutes: 0", body)

    def test_nothing_billable_says_so(self):
        body = _section("Patient reports feeling better today.")["body"]
        self.assertIn("no billable treatment", body)

    def test_reeval_carries_the_97164_decision(self):
        body = _section(FULL, form_id="reeval")["body"]
        self.assertIn("97164", body)
        self.assertIn("Progress Report is not billable", body)

    def test_timed_minutes_over_total_time_is_flagged(self):
        d = ("Gait training thirty minutes. Therapeutic exercise twenty minutes. "
             "Total treatment time forty minutes.")
        self.assertIn("exceed the total treatment time", _section(d)["body"])


class AuditTests(unittest.TestCase):
    def _note(self, gait_body="Minutes: 15\nWalked 150 ft with a rolling walker, contact guard, "
                              "verbal cues for step length. [[CPT: 97116 Gait Training — confirm]]",
              dictation=FULL):
        # Passes the Medicare checklist, so these tests isolate the BILLING findings.
        return [_sec("Gait Training", gait_body),
                _sec("Assessment", "Tolerated with fatigue; step length improved; progressing toward "
                                   "the 150 ft goal; still a fall risk and needs skilled cueing."),
                _sec("Plan", "Continue 2x/week; progress distance."),
                _section(dictation)]

    def test_complete_note_only_asks_for_confirmation(self):
        out = note_audit.audit("followup", self._note())
        self.assertTrue(out["ready"])
        self.assertEqual([f["level"] for f in out["findings"]], ["check"])
        self.assertIn("not confirmed", out["findings"][0]["text"])
        self.assertEqual(out["total_treatment_minutes"], 40)

    def test_confirmed_codes_are_recognised(self):
        sections = self._note()
        sections[-1]["body"] = sections[-1]["body"].replace(" — confirm]]", "]]")
        out = note_audit.audit("followup", sections)
        self.assertTrue(all(c["confirmed"] for c in out["codes"]))
        self.assertFalse(out["findings"])

    def test_timed_section_without_minutes_must_be_fixed(self):
        out = note_audit.audit("followup", self._note(gait_body="Walked 150 ft, contact guard."))
        self.assertFalse(out["ready"])
        self.assertTrue(any("Gait Training" in f["text"] and f["level"] == "fix"
                            for f in out["findings"]))

    def test_missing_total_treatment_time_must_be_fixed(self):
        d = "Gait training fifteen minutes with a walker."
        out = note_audit.audit("followup", self._note(dictation=d))
        self.assertFalse(out["ready"])
        self.assertTrue(any("Total treatment time" in f["text"] for f in out["findings"]))

    def test_minutes_disagreement_is_shown(self):
        out = note_audit.audit("followup", self._note(
            gait_body="Minutes: 20\n150 ft, contact guard. [[CPT: 97116 Gait Training — confirm]]"))
        self.assertTrue(any("says 20 min" in f["text"] for f in out["findings"]))

    def test_eval_without_complexity_code_is_checked(self):
        out = note_audit.audit("initial", [_sec("Assessment Summary", "Deficits in gait.")])
        self.assertTrue(any("97161" in f["text"] for f in out["findings"]))

    def test_note_without_any_code_must_be_fixed(self):
        out = note_audit.audit("followup", [_sec("Plan", "Continue.")])
        self.assertFalse(out["ready"])


if __name__ == "__main__":
    unittest.main()
