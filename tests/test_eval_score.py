"""Tests for the eval scorers (evals/score.py).

Pure/offline — hand-built section lists, no model, no DB. These lock the semantics the
aggregate report depends on, especially the CPT miss-cause split (table gap vs missed section)
and the transcript->note omission check.

    .venv/bin/python -m unittest tests.test_eval_score -v
"""

import unittest

from app.generate.forms import FORMS
from evals import score


def _sec(heading, body, carried=False):
    return {"heading": heading, "body": body, "carried_forward": carried}


class CptScoringTests(unittest.TestCase):
    def test_hit_when_marker_matches_gold(self):
        sections = [_sec("Gait Training", "Minutes: 15. [[CPT: 97116 Gait Training — confirm]]")]
        s = score.score_cpt(sections, ("97116",))
        self.assertEqual(s.hits, ("97116",))
        self.assertEqual(s.recall, 1.0)
        self.assertEqual(s.precision, 1.0)

    def test_miss_of_a_mappable_code_is_missed_section_not_table_gap(self):
        # 97110 IS in Cadence's table, so a miss means the model never wrote a
        # Therapeutic Exercise section — a model problem, not a mapping problem.
        sections = [_sec("Objective Summary", "Did some exercises.")]
        s = score.score_cpt(sections, ("97110",))
        self.assertEqual(s.missed_section, ("97110",))
        self.assertEqual(s.table_gap, ())

    def test_code_absent_from_the_table_is_a_table_gap(self):
        # 97161 (eval complexity) is deliberately NOT auto-assigned, so it can never be
        # suggested — that must be reported as a table gap, never as a model failure.
        sections = [_sec("Objective Summary", "Evaluation performed.")]
        s = score.score_cpt(sections, ("97161",))
        self.assertEqual(s.table_gap, ("97161",))
        self.assertEqual(s.missed_section, ())

    def test_attainable_recall_excludes_table_gaps(self):
        sections = [_sec("Manual Therapy", "[[CPT: 97140 Manual Therapy — confirm]]")]
        s = score.score_cpt(sections, ("97140", "97161"))
        self.assertEqual(s.recall, 0.5)              # raw recall counts the unattainable code
        self.assertEqual(s.attainable_recall, 1.0)   # model got everything it could

    def test_extra_suggestion_lowers_precision(self):
        sections = [
            _sec("Gait Training", "[[CPT: 97116 Gait Training — confirm]]"),
            _sec("Massage", "[[CPT: 97124 Massage Therapy — confirm]]"),
        ]
        s = score.score_cpt(sections, ("97116",))
        self.assertEqual(s.extra, ("97124",))
        self.assertEqual(s.precision, 0.5)

    def test_no_gold_codes_gives_none_recall(self):
        self.assertIsNone(score.score_cpt([_sec("X", "y")], ()).recall)


class InvariantTests(unittest.TestCase):
    def setUp(self):
        self.form = FORMS["followup"]

    def _run(self, sections, **kw):
        opts = {"parsed_ok": True, "was_condensed": False, "condense_flag_present": False}
        opts.update(kw)
        return {c.name: c for c in score.score_invariants(sections, self.form, **opts)}

    def test_bare_model_authored_cpt_code_fails(self):
        checks = self._run([_sec("Therapeutic Exercise", "Billed 97110 today.")])
        self.assertFalse(checks["no model-authored CPT code survived"].passed)

    def test_pipeline_cpt_marker_does_not_trip_the_bare_code_check(self):
        checks = self._run([_sec("Gait Training", "Walked. [[CPT: 97116 Gait Training — confirm]]")])
        self.assertTrue(checks["no model-authored CPT code survived"].passed)

    def test_icd10_in_prose_fails(self):
        checks = self._run([_sec("Diagnosis", "Low back pain M54.5 confirmed.")])
        self.assertFalse(checks["no ICD-10 code survived"].passed)

    def test_icd10_inside_needs_marker_is_not_counted(self):
        # The pipeline replaces code sections with a NEEDS marker; that must not read as a
        # surviving code.
        checks = self._run([_sec("ICD-10", "[[NEEDS: code not stated by therapist — clinician to assign]]")])
        self.assertTrue(checks["no ICD-10 code survived"].passed)

    def test_zero_minute_section_fails(self):
        checks = self._run([_sec("Manual Therapy", "Minutes: 0. Not performed today.")])
        self.assertFalse(checks["no 'Minutes: 0' placeholder section"].passed)

    def test_illegal_carry_tag_fails(self):
        checks = self._run([_sec("Gait Training", "Walked 200 ft.", carried=True)])
        self.assertFalse(checks["no illegal [[CARRIED FORWARD]] tag"].passed)

    def test_legal_carry_tag_passes(self):
        checks = self._run([_sec("Functional Status", "Ambulates 200 ft.", carried=True)])
        self.assertTrue(checks["no illegal [[CARRIED FORWARD]] tag"].passed)

    def test_mid_sentence_truncation_detected(self):
        checks = self._run([_sec("Plan", "Continue therapy and the certification period")])
        self.assertFalse(checks["note does not end mid-sentence"].passed)

    def test_complete_sentence_passes(self):
        checks = self._run([_sec("Plan", "Continue therapy twice a week for six weeks.")])
        self.assertTrue(checks["note does not end mid-sentence"].passed)

    def test_condense_warning_required_only_when_condensed(self):
        secs = [_sec("Plan", "Continue therapy.")]
        self.assertNotIn("condense warning surfaced", self._run(secs))
        checks = self._run(secs, was_condensed=True, condense_flag_present=False)
        self.assertFalse(checks["condense warning surfaced"].passed)
        checks = self._run(secs, was_condensed=True, condense_flag_present=True)
        self.assertTrue(checks["condense warning surfaced"].passed)

    def test_content_folded_into_heading_fails(self):
        # The real failure this catches: the model wrote the section's content on the "## " line,
        # leaving the body empty. traceability inspects bodies only, so every fabrication check
        # silently no-ops — a note like this would otherwise score clean.
        folded = _sec(
            "Gait Training — Minutes: 15. Set up: patient standing with assistive device (cane). "
            "Region: lower extremity. Technique: ambulation of two hundred feet.", ""
        )
        checks = self._run([folded])
        self.assertFalse(checks["content in bodies, not headings"].passed)
        self.assertFalse(checks["every section has a non-empty body"].passed)

    def test_normal_headings_and_bodies_pass(self):
        checks = self._run([
            _sec("Gait Training", "Minutes: 15. Ambulated 200 feet."),
            _sec("Functional Mobility / Gait", "Independent on level surfaces."),
        ])
        self.assertTrue(checks["content in bodies, not headings"].passed)
        self.assertTrue(checks["every section has a non-empty body"].passed)

    def test_body_of_only_markers_counts_as_empty(self):
        # A body that is nothing but a CPT suggestion has no clinical content for the
        # verification layer to inspect either.
        checks = self._run([_sec("Gait Training", "[[CPT: 97116 Gait Training — confirm]]")])
        self.assertFalse(checks["every section has a non-empty body"].passed)

    def test_empty_soap_block_reported(self):
        checks = self._run([_sec("Gait Training", "Walked 200 ft.")])  # Objective only
        self.assertFalse(checks["all four SOAP blocks populated"].passed)


class OmissionTests(unittest.TestCase):
    def test_value_stated_but_absent_from_note_is_dropped(self):
        transcript = "Pain was four out of ten and he walked two hundred feet."
        sections = [_sec("Pain", "Pain 4/10.")]  # distance never made it into the note
        s = score.score_omissions(sections, transcript)
        self.assertIn("200 feet", s.dropped)
        self.assertIn("4/10", s.present)

    def test_spoken_and_written_forms_match(self):
        transcript = "Strength was three plus out of five."
        sections = [_sec("Strength", "MMT 3+/5.")]
        s = score.score_omissions(sections, transcript)
        self.assertEqual(s.dropped, ())
        self.assertEqual(s.rate, 1.0)

    def test_mmt_range_denominator_distributes(self):
        # The locked regression from CLAUDE.md rule 20(a): the spoken denominator applies to
        # BOTH grades, so a real dictated range must not read as dropped.
        transcript = "Strength three plus to four minus out of five."
        sections = [_sec("Strength", "MMT 3+/5 to 4-/5.")]
        self.assertEqual(score.score_omissions(sections, transcript).dropped, ())

    def test_no_values_in_transcript_gives_none_rate(self):
        self.assertIsNone(score.score_omissions([_sec("X", "y")], "no numbers here").rate)


class FlagTriageTests(unittest.TestCase):
    def test_flags_collected_with_section_and_text(self):
        sections = [_sec("Gait", 'Walked. [[NEEDS: "500 feet" not found in dictation — verify or remove]]')]
        flags = score.collect_flags(sections, "he walked about 500 feet down the hall today")
        self.assertEqual(len(flags), 1)
        self.assertEqual(flags[0].section, "Gait")
        self.assertIn("500 feet", flags[0].text)

    def test_context_window_quotes_the_transcript(self):
        sections = [_sec("Gait", '[[NEEDS: "500 feet" not found in dictation — verify or remove]]')]
        flags = score.collect_flags(sections, "he walked about 500 feet down the hall today")
        self.assertIn("500", flags[0].context)

    def test_context_empty_when_value_absent_from_transcript(self):
        sections = [_sec("Gait", '[[NEEDS: "500 feet" not found in dictation — verify or remove]]')]
        self.assertEqual(score.collect_flags(sections, "nothing relevant here")[0].context, "")

    def test_multiple_flags_in_one_body(self):
        body = ('[[NEEDS: "4/10" not found in dictation — verify]] '
                '[[NEEDS: assistive device "cane" not mentioned in dictation — verify]]')
        self.assertEqual(len(score.collect_flags([_sec("Gait", body)], "")), 2)


class SectionCoverageTests(unittest.TestCase):
    def test_counts_expected_labels_from_the_template_spec(self):
        form = FORMS["followup"]
        present, expected, missing = score.section_coverage(
            [_sec("Precautions", "WBAT."), _sec("Functional Status", "Ambulates 200 ft.")], form
        )
        self.assertGreater(expected, 0)
        self.assertEqual(present, expected - len(missing))
        self.assertIn("Response to Treatment", missing)


if __name__ == "__main__":
    unittest.main()
