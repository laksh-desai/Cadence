"""Medicare documentation checklist (app/generate/compliance.py).

Each "denial" case is a common real reason outpatient therapy claims fail medical review —
unskilled language, no response, unmeasurable goals, no comparison on a progress report — written as
a fake note. The checklist must catch every one, and must pass the compliant version of each note
type cleanly (a checker that flags good notes trains the clinician to ignore it).
"""

import unittest

from app.generate import compliance


def _s(heading, body):
    return {"heading": heading, "body": body, "carried_forward": False}


GOOD_DAILY = [
    _s("Subjective", "Reports hip pain 3/10, no falls since last visit."),
    _s("Gait Training", "Minutes: 15\n2 x 100 ft with a rolling walker, contact guard; verbal cues "
                        "for step length."),
    _s("Neuromuscular Re-education", "Minutes: 12\nTandem stance 3 x 30 seconds, tactile cues at the "
                                     "pelvis, min assist for two losses of balance."),
    _s("Assessment", "Tolerated with fatigue after gait; step length improved; progressing toward the "
                     "150 ft goal; remains a fall risk and needs skilled cueing and guarding."),
    _s("Short-Term Goals", "Walk 150 ft with walker at supervision in 3 weeks — progressing."),
    _s("Plan", "Continue 2x/week; progress gait distance; start step training."),
]

GOOD_EVAL = [
    _s("Chief Complaint", "Difficulty walking after right hip ORIF."),
    _s("Diagnoses", "Right hip fracture s/p ORIF; gait abnormality."),
    _s("Referral & Relevant History", "Prior level of function: community ambulator without a device."),
    _s("Fall Risk", "Two falls in six months; Timed Up and Go 24 seconds with walker."),
    _s("Musculoskeletal Assessment", "Right hip flexion 85 degrees; hip abductors 3-/5."),
    _s("Functional Mobility", "Walks 75 ft with a rolling walker, contact guard."),
    _s("Assessment Summary", "Strength and balance deficits; high fall risk; skilled PT needed; good "
                             "rehab potential."),
    _s("Short-Term Goals", "In 3 weeks walk 150 ft with the walker at supervision."),
    _s("Long-Term Goals", "In 8 weeks walk 500 ft with a cane independently."),
    _s("Plan of Treatment", "PT 2x/week for 8 weeks: gait training, neuromuscular re-education, "
                            "therapeutic exercise, home exercise program."),
]

GOOD_REEVAL = [
    _s("Reporting Period", "Visit 10; March 3 to April 2."),
    _s("Objective Measures", "Berg 44/56, up from 36; TUG 16 seconds, down from 24."),
    _s("Goal Status", "Walk 150 ft with walker at supervision: MET. Berg > 45: PROGRESSING."),
    _s("Assessment Summary", "Good progress; still a fall risk on turns; continued skilled PT needed."),
    _s("Short-Term Goals", "In 3 weeks walk 400 ft with a cane independently."),
    _s("Long-Term Goals", "In 4 weeks independent community walking 500 ft with a cane."),
    _s("Plan of Treatment", "Continue 2x/week for 4 weeks."),
]

GOOD_DISCHARGE = [
    _s("Reason for Discharge", "Goals met."),
    _s("Initial Status", "75 ft with a walker, contact guard; Berg 36."),
    _s("Functional Status", "600 ft with a cane independently, up from 75 ft with a walker."),
    _s("Short-Term Goals", "Walk 150 ft with walker at supervision: MET."),
    _s("Long-Term Goals", "Walk 500 ft with a cane independently: MET."),
    _s("Home Exercise Program & Education", "Written balance program issued; demonstrated correctly."),
    _s("Equipment & Recommendations", "Single-point cane; community balance class."),
]


def _fixes(form_id, sections):
    return [f["element"] for f in compliance.check(form_id, sections) if f["level"] == "fix"]


def _all(form_id, sections):
    return [f["element"] for f in compliance.check(form_id, sections)]


def _replace(sections, heading, body):
    return [_s(s["heading"], body) if s["heading"] == heading else s for s in sections]


class CompliantNotesPass(unittest.TestCase):
    def test_good_notes_have_no_findings(self):
        for form_id, note in (("followup", GOOD_DAILY), ("initial", GOOD_EVAL),
                              ("reeval", GOOD_REEVAL), ("discharge", GOOD_DISCHARGE)):
            with self.subTest(form=form_id):
                self.assertEqual(compliance.check(form_id, note), [])


class DenialReasonsAreCaught(unittest.TestCase):
    def test_unskilled_tolerated_well(self):
        note = _replace(GOOD_DAILY, "Assessment", "Tolerated well.")
        self.assertIn("Skilled language", _fixes("followup", note))

    def test_continue_plan_of_care_alone(self):
        note = _replace(GOOD_DAILY, "Plan", "Continue POC.")
        self.assertIn("Skilled language", _fixes("followup", note))

    def test_treatment_without_skilled_input(self):
        note = _replace(GOOD_DAILY, "Gait Training", "Minutes: 15\nWalked 100 ft.")
        self.assertIn("Skilled care", _fixes("followup", note))

    def test_treatment_without_parameters(self):
        note = _replace(GOOD_DAILY, "Gait Training", "Minutes: 15\nGait with verbal cues.")
        self.assertIn("Treatment parameters", _all("followup", note))

    def test_no_assessment(self):
        note = [s for s in GOOD_DAILY if s["heading"] != "Assessment"]
        self.assertIn("Patient response", _fixes("followup", note))

    def test_no_link_to_goals_or_necessity(self):
        note = [s for s in GOOD_DAILY if s["heading"] != "Short-Term Goals"]
        note = _replace(note, "Assessment", "Tolerated with mild fatigue after the session.")
        found = _all("followup", note)
        self.assertIn("Progress toward goals", found)
        self.assertIn("Medical necessity", found)

    def test_unmeasurable_goal(self):
        note = _replace(GOOD_EVAL, "Short-Term Goals", "Improve walking.")
        self.assertIn("Measurable goals", _fixes("initial", note))

    def test_plan_without_frequency_or_duration(self):
        note = _replace(GOOD_EVAL, "Plan of Treatment", "Gait training and exercise.")
        found = _fixes("initial", note)
        self.assertIn("Plan of care: frequency", found)
        self.assertIn("Plan of care: duration", found)

    def test_eval_without_objective_baseline(self):
        note = [s for s in GOOD_EVAL if s["heading"] not in
                ("Fall Risk", "Musculoskeletal Assessment", "Functional Mobility")]
        self.assertIn("Objective tests and measures", _fixes("initial", note))

    def test_progress_report_without_measured_change(self):
        note = _replace(GOOD_REEVAL, "Objective Measures", "Patient is doing better.")
        self.assertIn("Objective measures", _fixes("reeval", note))

    def test_progress_report_without_goal_status(self):
        note = [s for s in GOOD_REEVAL if s["heading"] != "Goal Status"]
        self.assertIn("Goal status", _fixes("reeval", note))

    def test_progress_report_without_reporting_period(self):
        note = [s for s in GOOD_REEVAL if s["heading"] != "Reporting Period"]
        self.assertIn("Reporting period", _fixes("reeval", note))

    def test_discharge_without_reason_or_goal_outcome(self):
        note = [s for s in GOOD_DISCHARGE if s["heading"] not in ("Reason for Discharge", "Long-Term Goals")]
        found = _fixes("discharge", note)
        self.assertIn("Reason for discharge", found)
        self.assertIn("Final goal status", found)

    def test_markers_do_not_count_as_content(self):
        note = _replace(GOOD_DAILY, "Plan", "[[NEEDS: plan for the next visit]]")
        self.assertIn("Plan", _fixes("followup", note))


if __name__ == "__main__":
    unittest.main()
