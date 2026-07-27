"""Composition tests for the post-generation pipeline the /api/generate endpoint runs.

Each step is unit-tested on its own; this checks they COMPOSE the way server.py chains them —
postprocess.apply -> traceability.add_verification_flags -> cpt.suggest_codes — with no marker
interference (a section can legitimately carry a CPT suggestion AND verification flags at once).
Pure functions, no model/DB.

    .venv/Scripts/python.exe -m unittest tests.test_pipeline_compose -v
"""

import unittest

from app.generate import cpt, postprocess, traceability


def _run(sections, form_id, transcript):
    s = postprocess.apply(form_id, sections)
    s = traceability.add_verification_flags(s, transcript)
    s, extra = cpt.suggest_codes(s, form_id)
    return s, extra


class PipelineComposeTests(unittest.TestCase):
    def test_cpt_and_verification_flags_coexist_on_one_section(self):
        # Gait Training section with a fabricated distance + device the dictation never mentioned:
        # it should end up with the CPT suggestion AND both verification flags, none clobbered.
        sections = [{"heading": "Gait Training", "body": "Ambulated 500 feet with a cane.", "carried_forward": False}]
        s, _ = _run(sections, "followup", "patient did some walking today")
        body = s[0]["body"]
        self.assertIn("[[CPT: 97116 Gait Training — confirm]]", body)
        self.assertIn('"500 feet" not found', body)
        self.assertIn('assistive device "cane" not mentioned', body)

    def test_model_written_code_in_heading_stripped_through_full_pipeline(self):
        sections = [{"heading": "Therapeutic Exercise 97110", "body": "Quad sets.", "carried_forward": False}]
        s, _ = _run(sections, "followup", "did quad sets")
        self.assertEqual(s[0]["heading"], "Therapeutic Exercise")
        self.assertIn("[[CPT: 97110 Therapeutic Exercise — confirm]]", s[0]["body"])

    def test_eval_complexity_surfaced_by_pipeline_for_initial(self):
        sections = [{"heading": "Objective Summary", "body": "Alert and oriented.", "carried_forward": False}]
        _, extra = _run(sections, "initial", "patient is alert and oriented")
        self.assertTrue(any("97161" in e and "97163" in e for e in extra))

    def test_non_treatment_section_gets_no_cpt(self):
        sections = [{"heading": "Chief Complaint", "body": "Right knee pain.", "carried_forward": False}]
        s, _ = _run(sections, "followup", "right knee pain")
        self.assertNotIn("[[CPT:", s[0]["body"])


if __name__ == "__main__":
    unittest.main()
