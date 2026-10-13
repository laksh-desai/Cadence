"""Repairs for failures measured in the 2026-10 field test (scripts/field_test.py).

Each test is the shape of a REAL generated note from that run, reduced to what matters.
"""

import unittest

from app.generate import billing, billing_section, note_audit, postprocess


def _s(heading, body):
    return {"heading": heading, "body": body, "carried_forward": False}


class StackedLabelLines(unittest.TestCase):
    def test_a_reeval_written_as_one_section_is_split_back_out(self):
        body = ("visit number 10, March 3 to April 2.\n"
                "Reason for Reassessment — routine progress report.\n"
                "Diagnoses — right hip ORIF.\n"
                "Goal Status — walk 150 ft at supervision is MET.\n"
                "Plan of Treatment — continue 2x per week for 4 weeks.")
        out = postprocess.split_label_lines("reeval", [_s("Reporting Period", body)])
        self.assertEqual([s["heading"] for s in out],
                         ["Reporting Period", "Reason for Reassessment", "Diagnoses", "Goal Status",
                          "Plan of Treatment"])
        self.assertEqual(out[0]["body"], "visit number 10, March 3 to April 2.")
        self.assertEqual(out[3]["body"], "walk 150 ft at supervision is MET.")

    def test_prose_mentioning_a_label_does_not_split(self):
        body = "Plan to reassess goals next week.\nGoals reviewed with the patient."
        out = postprocess.split_label_lines("followup", [_s("Assessment", body)])
        self.assertEqual(len(out), 1)

    def test_an_existing_section_is_never_duplicated(self):
        sections = [_s("Assessment", "Improving.\nPlan — continue."), _s("Plan", "Continue 2x/week.")]
        self.assertEqual(postprocess.split_label_lines("followup", sections), sections)


class UnperformedTreatments(unittest.TestCase):
    def test_not_performed_treatment_sections_are_dropped(self):
        sections = [_s("Gait Training", "Minutes: 20\n300 ft with rollator, contact guard."),
                    _s("Manual Therapy", "Not performed today."),
                    _s("Therapeutic Activities", "N/A"),
                    _s("Self-Care / Home Management Training", "Minutes: 0 - not done")]
        out = postprocess.drop_unperformed_treatment_sections(sections)
        self.assertEqual([s["heading"] for s in out], ["Gait Training"])

    def test_a_non_treatment_section_saying_not_done_is_kept(self):
        sections = [_s("Vitals", "Not performed today.")]
        self.assertEqual(postprocess.drop_unperformed_treatment_sections(sections), sections)


class BareGoalStatus(unittest.TestCase):
    def test_bare_met_is_flagged(self):
        out = postprocess.flag_bare_goal_status([_s("Short-Term Goals", "MET")])
        self.assertIn("[[NEEDS: name each goal", out[0]["body"])

    def test_a_named_goal_is_untouched(self):
        sec = [_s("Short-Term Goals", "Walk 150 ft with walker at supervision: MET.")]
        self.assertEqual(postprocess.flag_bare_goal_status(sec), sec)


class UndictatedTreatment(unittest.TestCase):
    def test_a_treatment_the_dictation_never_mentions_is_flagged_and_audited(self):
        d = "Gait training twenty minutes. Neuro re-ed fifteen minutes. Total treatment time thirty five minutes."
        draft = billing.extract(d)
        sections = [_s("Gait Training", "Minutes: 20\n300 ft, contact guard."),
                    _s("Therapeutic Exercise", "Minutes: 35\nExercises.")]
        flagged = billing_section.flag_undictated_treatments(sections, draft)
        self.assertNotIn("NEEDS", flagged[0]["body"])
        self.assertIn(billing_section.UNDICTATED_FLAG, flagged[1]["body"])
        audit = note_audit.audit("followup", flagged + [billing_section.build(draft, d, "followup")])
        self.assertTrue(any("Therapeutic Exercise is in the note but was not in the dictation" in f["text"]
                            for f in audit["findings"]))
        self.assertFalse(audit["ready"])



class SkeletonNoteIsFlagged(unittest.TestCase):
    """2026-10: the model returned only the outline's headings (445 chars, every body empty)."""

    def test_headings_only_output_warns_at_the_top(self):
        from app.generate.forms import FORMS, spec_section_labels
        from app.ui import server
        text = "\n".join(f"## {label}\n" for label in spec_section_labels("followup"))
        result = server._finalize_note(FORMS["followup"], text, False, False, "gait training", False)
        self.assertTrue(result.missing_info and result.missing_info[0].startswith("INCOMPLETE NOTE"))

    def test_a_complete_note_has_no_warning(self):
        from app.generate.forms import FORMS, spec_section_labels
        from app.ui import server
        text = "\n".join(f"## {label}\nStated content for {label.lower()} today.\n"
                         for label in spec_section_labels("followup"))
        result = server._finalize_note(FORMS["followup"], text, False, False, "gait training", False)
        self.assertFalse(any(m.startswith("INCOMPLETE NOTE") for m in result.missing_info))


if __name__ == "__main__":
    unittest.main()
