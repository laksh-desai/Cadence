"""Tests for the deterministic post-parse safety net (app/generate/postprocess.py).

These lock in CLAUDE.md generation rules #11 and #12 — the corrections that must
hold *regardless of model compliance*, because MedGemma 4B reliably violates the
prompt no matter how it's worded:
  - drops invented "Minutes: 0" not-performed placeholder sections,
  - strips [[CARRIED FORWARD]] from any heading that isn't one of the form's real
    carry-forward labels,
  - never lets a model-authored CPT/ICD code through (replaces it with a gap marker).

Pure functions — no DB, no model. Run with:
    .venv/Scripts/python.exe -m unittest tests.test_postprocess -v
"""

import unittest

from app.generate import postprocess

CODE_MARKER = "[[NEEDS: code not stated by therapist — clinician to assign]]"


def _sec(heading, body, carried=False):
    return {"heading": heading, "body": body, "carried_forward": carried}


class DropUnperformedTests(unittest.TestCase):
    def test_body_opening_with_minutes_zero_is_dropped(self):
        secs = [_sec("Ultrasound", "Minutes: 0 — not performed today.")]
        self.assertEqual(postprocess.drop_unperformed_treatment_sections(secs), [])

    def test_case_insensitive_and_leading_whitespace(self):
        secs = [
            _sec("A", "minutes: 0 nothing"),
            _sec("B", "   Minutes: 0\nno treatment"),
        ]
        self.assertEqual(postprocess.drop_unperformed_treatment_sections(secs), [])

    def test_real_treatment_with_nonzero_minutes_is_kept(self):
        secs = [_sec("Therapeutic Exercise", "Minutes: 20\nPerformed knee extensions.")]
        self.assertEqual(postprocess.drop_unperformed_treatment_sections(secs), secs)

    def test_zero_not_a_word_boundary_is_kept(self):
        # "Minutes: 05" is a nonzero (if oddly written) duration -- the \b in the
        # pattern means only a bare 0 counts, so this must survive.
        secs = [_sec("Manual Therapy", "Minutes: 05 of soft tissue work.")]
        self.assertEqual(postprocess.drop_unperformed_treatment_sections(secs), secs)

    def test_minutes_zero_not_at_body_start_is_kept(self):
        # Only a body that OPENS with the placeholder is a not-performed marker.
        secs = [_sec("Note", "Total treatment time excluding rest: Minutes: 0 rest breaks.")]
        self.assertEqual(postprocess.drop_unperformed_treatment_sections(secs), secs)


class EnforceCarryTagsTests(unittest.TestCase):
    def test_real_carry_label_keeps_flag(self):
        out = postprocess.enforce_carry_tags("followup", [_sec("Functional Status", "x", True)])
        self.assertTrue(out[0]["carried_forward"])

    def test_non_carry_heading_is_stripped(self):
        out = postprocess.enforce_carry_tags("followup", [_sec("Therapeutic Exercise", "x", True)])
        self.assertFalse(out[0]["carried_forward"])

    def test_collapsed_goals_heading_matches_bidirectionally(self):
        # A collapsed single "Goals" heading must still be treated as a carry label even
        # though followup's label list says "Short-Term Goals" / "Long-Term Goals".
        out = postprocess.enforce_carry_tags("followup", [_sec("Goals", "x", True)])
        self.assertTrue(out[0]["carried_forward"])

    def test_form_with_no_carry_labels_strips_everything(self):
        out = postprocess.enforce_carry_tags("initial", [_sec("Assessment", "x", True)])
        self.assertFalse(out[0]["carried_forward"])

    def test_literal_body_tag_stripped_on_non_carry_form(self):
        # Real-run #3: a non-carry Initial Eval had "[[CARRIED FORWARD]]" written into every body.
        out = postprocess.enforce_carry_tags(
            "initial", [_sec("Chief Complaint", "Status post right THA. [[CARRIED FORWARD]]", False)])
        self.assertNotIn("CARRIED FORWARD", out[0]["body"])
        self.assertFalse(out[0]["carried_forward"])

    def test_literal_body_tag_marks_carry_on_allowed_section(self):
        # On a real carry section, a tag in the BODY (not heading) must still mark it carried.
        out = postprocess.enforce_carry_tags(
            "followup", [_sec("Functional Status", "Ambulates 200 ft. [[CARRIED FORWARD]]", False)])
        self.assertTrue(out[0]["carried_forward"])
        self.assertNotIn("CARRIED FORWARD", out[0]["body"])


class TemplateEchoTests(unittest.TestCase):
    """Real-run #15: the model output the template's field INSTRUCTIONS as the values. Flag those;
    never touch a real value that merely shares a couple of words."""

    def test_echoed_functional_status_instruction_flagged(self):
        body = "ambulation distance, assistive device, assist level, and stairs, updated to reflect today."
        out = postprocess.flag_template_echo("followup", [_sec("Functional Status", body)])
        self.assertIn("[[NEEDS:", out[0]["body"])
        self.assertNotIn("assist level", out[0]["body"])

    def test_echoed_goal_instruction_flagged(self):
        out = postprocess.flag_template_echo(
            "followup", [_sec("Short-Term Goals", "mark MET if today's data shows it achieved.")])
        self.assertIn("[[NEEDS:", out[0]["body"])

    def test_echoed_plan_instruction_flagged(self):
        out = postprocess.flag_template_echo(
            "followup", [_sec("Plan", "plan for the next visit: frequency, progression, and any change to the assist level.")])
        self.assertIn("[[NEEDS:", out[0]["body"])

    def test_real_functional_status_value_not_flagged(self):
        body = "Ambulates 200 feet with a single point cane at contact guard; managed six steps with the rail."
        out = postprocess.flag_template_echo("followup", [_sec("Functional Status", body)])
        self.assertEqual(out[0]["body"], body)

    def test_real_goal_value_not_flagged(self):
        out = postprocess.flag_template_echo("followup", [_sec("Short-Term Goals", "MET")])
        self.assertEqual(out[0]["body"], "MET")

    def test_strips_echoed_carry_forward_instruction_from_heading(self):
        # The model copies the spec's "[carry forward]" instruction into the heading; drop it.
        out = postprocess.strip_carry_instruction_headings([_sec("Precautions [carry forward]", "x", False)])
        self.assertEqual(out[0]["heading"], "Precautions")

    def test_strips_carry_instruction_with_trailing_note(self):
        out = postprocess.strip_carry_instruction_headings(
            [_sec("Short-Term Goals [carry forward — mark MET]", "x", False)]
        )
        self.assertEqual(out[0]["heading"], "Short-Term Goals")

    def test_clean_heading_left_untouched(self):
        out = postprocess.strip_carry_instruction_headings([_sec("Functional Status", "x", False)])
        self.assertEqual(out[0]["heading"], "Functional Status")

    def test_code_field_lines_are_flagged(self):
        # Block-format codes live as body field lines, not headings — flag the model-authored value.
        body = "Frequency: 2x/week\nMedical Diagnosis (ICD-10): M54.5\nTreatment Procedures (CPT): 97110"
        out = postprocess.flag_code_field_lines([_sec("Plan", body, False)])[0]["body"]
        self.assertIn("Medical Diagnosis (ICD-10): [[NEEDS:", out)
        self.assertIn("Treatment Procedures (CPT): [[NEEDS:", out)
        self.assertNotIn("M54.5", out)          # fabricated ICD code removed
        self.assertNotIn("97110", out)
        self.assertIn("Frequency: 2x/week", out)  # non-code field untouched

    def test_treatment_diagnosis_in_words_not_flagged(self):
        out = postprocess.flag_code_field_lines([_sec("Plan", "Treatment Diagnosis: Rotator cuff tendinopathy", False)])[0]["body"]
        self.assertIn("Rotator cuff tendinopathy", out)
        self.assertNotIn("[[NEEDS:", out)

    def test_false_stays_false(self):
        out = postprocess.enforce_carry_tags("followup", [_sec("Functional Status", "x", False)])
        self.assertFalse(out[0]["carried_forward"])

    def test_body_and_heading_are_preserved(self):
        out = postprocess.enforce_carry_tags("followup", [_sec("Precautions", "weight bearing", True)])
        self.assertEqual(out[0]["heading"], "Precautions")
        self.assertEqual(out[0]["body"], "weight bearing")


class FlagCodeSectionsTests(unittest.TestCase):
    def test_cpt_heading_body_replaced(self):
        out = postprocess.flag_code_sections([_sec("CPT Codes", "97110, 97140")])
        self.assertEqual(out[0]["body"], CODE_MARKER)

    def test_icd_heading_body_replaced(self):
        out = postprocess.flag_code_sections([_sec("ICD-10 Diagnosis", "M25.51")])
        self.assertEqual(out[0]["body"], CODE_MARKER)

    def test_case_insensitive(self):
        out = postprocess.flag_code_sections([_sec("Billing cpt", "anything")])
        self.assertEqual(out[0]["body"], CODE_MARKER)

    def test_non_code_heading_untouched(self):
        out = postprocess.flag_code_sections([_sec("Assessment", "Tolerating well.")])
        self.assertEqual(out[0]["body"], "Tolerating well.")

    def test_word_boundary_avoids_false_positive(self):
        # A heading that merely contains the letters (e.g. "Indication") must not trip.
        out = postprocess.flag_code_sections([_sec("Indications for Continued Care", "x")])
        self.assertEqual(out[0]["body"], "x")


class ApplyIntegrationTests(unittest.TestCase):
    def test_all_three_corrections_compose(self):
        sections = [
            _sec("Ultrasound", "Minutes: 0 not performed"),          # dropped
            _sec("Functional Status", "Ambulates 200ft.", True),     # carry kept
            _sec("Gait Training", "Walked 200ft.", True),            # carry stripped
            _sec("CPT Code", "97110"),                               # body flagged
        ]
        out = postprocess.apply("followup", sections)
        headings = [s["heading"] for s in out]
        self.assertNotIn("Ultrasound", headings)  # dropped entirely
        by_heading = {s["heading"]: s for s in out}
        self.assertTrue(by_heading["Functional Status"]["carried_forward"])
        self.assertFalse(by_heading["Gait Training"]["carried_forward"])
        self.assertEqual(by_heading["CPT Code"]["body"], CODE_MARKER)


class HeadingFoldRepairTests(unittest.TestCase):
    """`split_folded_headings` — the model writing section CONTENT on the `## ` line.

    Real MedGemma 4B run (2026-08, 3-record sweep): on 2 of 3 notes the model folded the content
    into the heading and left EVERY body empty — 8/14 headings over 80 chars, longest 339. That
    silently no-ops the ENTIRE rule-20 verification layer, which inspects `body` only, AND leaves
    the content uneditable, because app.js renders the heading as a <span> and gives a textarea
    only for the body. The verbatim heading from that run is the first test below.

        .venv/Scripts/python.exe -m unittest tests.test_postprocess -v
    """

    REAL = ("Summary of Daily Skilled Services — 18 minutes of therapeutic exercise (rotator cuff "
            "strengthening with yellow band, scapular setting, and prone horizontal abduction). "
            "15 minutes of simulated overhead painting task (scapulohumeral mechanics and pacing). "
            "12 minutes of electrical stimulation to the left upper trapezius for pain modulation.")

    def test_real_run_folded_heading_is_split(self):
        out = postprocess.split_folded_headings([_sec(self.REAL, "")])
        self.assertEqual(out[0]["heading"], "Summary of Daily Skilled Services")
        self.assertTrue(out[0]["body"].startswith("18 minutes of therapeutic exercise"))
        self.assertLessEqual(len(out[0]["heading"]), postprocess.MAX_HEADING_CHARS)
        self.assertNotIn("[[NEEDS:", out[0]["body"], "a clean split is confident — no flag")

    def test_short_heading_untouched(self):
        secs = [_sec("Therapeutic Exercise", "Minutes: 20. Quad sets.")]
        self.assertEqual(postprocess.split_folded_headings(secs), secs)

    def test_long_heading_with_a_real_body_untouched(self):
        """Both conditions are required — they guard each other."""
        secs = [_sec(self.REAL, "Minutes: 18. Real content lives here.")]
        self.assertEqual(postprocess.split_folded_headings(secs), secs)

    def test_body_of_only_markers_counts_as_empty_and_the_marker_survives(self):
        out = postprocess.split_folded_headings([_sec(self.REAL, "[[CARRIED FORWARD]]")])
        self.assertEqual(out[0]["heading"], "Summary of Daily Skilled Services")
        self.assertIn("[[CARRIED FORWARD]]", out[0]["body"])

    def test_colon_separator(self):
        h = "Functional Status: ambulates 200 feet with a rolling walker, contact guard assist " \
            "on level ground and four steps with one rail."
        out = postprocess.split_folded_headings([_sec(h, "")])
        self.assertEqual(out[0]["heading"], "Functional Status")
        self.assertTrue(out[0]["body"].startswith("ambulates 200 feet"))

    def test_earliest_valid_separator_wins(self):
        h = "Gait Training: in the hallway — with contact guard assist and cueing for heel " \
            "strike throughout the session, tolerated well."
        out = postprocess.split_folded_headings([_sec(h, "")])
        self.assertEqual(out[0]["heading"], "Gait Training")

    def test_never_splits_inside_a_marker(self):
        h = ("Gait Training [[CPT: 97116 Gait Training — confirm]] in the hallway with contact "
             "guard assist, cueing for heel strike and step length symmetry.")
        out = postprocess.split_folded_headings([_sec(h, "")])
        combined = out[0]["heading"] + out[0]["body"]
        self.assertEqual(combined.count("[["), combined.count("]]"))
        self.assertIn("[[CPT: 97116 Gait Training — confirm]]", combined)

    def test_minutes_travels_into_the_body_with_its_number(self):
        """Rule 10: 'Minutes: __' belongs in the body, never the heading — and never split
        away from the number it labels."""
        h = "Therapeutic Exercise Minutes: 25 — quad sets, straight leg raises, and short arc " \
            "quads performed in supine with verbal cueing."
        out = postprocess.split_folded_headings([_sec(h, "")])
        self.assertEqual(out[0]["heading"], "Therapeutic Exercise")
        self.assertTrue(out[0]["body"].startswith("Minutes: 25"))

    def test_no_separator_falls_back_to_truncation_and_flags(self):
        h = ("The patient performed rotator cuff strengthening with a yellow theraband followed "
             "by scapular setting and prone horizontal abduction throughout the session today")
        out = postprocess.split_folded_headings([_sec(h, "")])
        self.assertLessEqual(len(out[0]["heading"]), postprocess.MAX_LABEL_CHARS)
        self.assertFalse(out[0]["heading"].endswith(" "))
        self.assertIn(h, out[0]["body"], "the full text must be preserved, not truncated away")
        self.assertIn("[[NEEDS:", out[0]["body"], "a guessed label earns a flag")

    def test_fallback_keeps_the_cpt_matchable_prefix(self):
        from app.generate import cpt
        h = ("Therapeutic Exercise performed with the patient in supine including quad sets and "
             "straight leg raises with verbal cueing for form throughout the full session")
        out = postprocess.split_folded_headings([_sec(h, "")])
        self.assertEqual(cpt.code_for_heading(out[0]["heading"]), ("97110", "Therapeutic Exercise"))

    def test_a_label_carrying_a_clinical_value_is_rejected(self):
        """"Pain 8/10 at rest" is content, not a label — it must fall through to the fallback so
        the values land in the body where the verification layer can check them."""
        h = "Pain 8/10 at rest — worst 8 out of 10, best 3 out of 10, currently 5 out of 10 " \
            "with overhead reaching and at night when lying on that side."
        out = postprocess.split_folded_headings([_sec(h, "")])
        self.assertNotEqual(out[0]["heading"], "Pain 8/10 at rest")
        self.assertIn("8/10", out[0]["body"])

    def test_idempotent(self):
        once = postprocess.split_folded_headings([_sec(self.REAL, "")])
        self.assertEqual(postprocess.split_folded_headings(once), once)

    def test_apply_runs_the_split_before_the_zero_minutes_drop(self):
        """The load-bearing ordering test. A folded "Minutes: 0" leaves an empty body, so the drop
        never fires and the invented not-performed section survives into the note."""
        h = ("Ultrasound — Minutes: 0, not performed today because the patient reported increased "
             "irritability and we deferred the modality to the next visit.")
        self.assertEqual(postprocess.apply("followup", [_sec(h, "")]), [])

    def test_apply_leaves_code_headings_to_flag_code_sections(self):
        """Rule 12 wins: flag_code_sections REPLACES the whole body, so splitting first would hand
        it content that then gets wiped. Behaviour here must stay byte-identical to before."""
        h = ("CPT Codes billed for this visit include 97110 therapeutic exercise and 97140 manual "
             "therapy along with the associated timed treatment minutes for each service.")
        out = postprocess.apply("followup", [_sec(h, "")])
        self.assertEqual(out[0]["heading"], h, "a code heading is left untouched")
        self.assertEqual(out[0]["body"], CODE_MARKER)

    def test_a_folded_heading_no_longer_over_tags_carry_forward(self):
        """`_is_carry_forward_label` does a substring match, so "functional status" appearing
        anywhere inside a 200-char heading marked the section carried. The split fixes it."""
        h = ("Treatment Response — the patient's functional status was reassessed today and she "
             "reports improved tolerance for overhead activity since the previous session.")
        out = postprocess.apply("followup", [_sec(h, "", carried=True)])
        self.assertFalse(out[0]["carried_forward"])

    def test_a_folded_plan_section_no_longer_earns_a_treatment_chip(self):
        """Measured on real captured output, and the strongest argument for this repair.

        `cpt.suggest_codes` matches the section HEADING, deliberately, because matching prose
        misfires (rule 12). A folded heading turns the whole section's PROSE into the heading, so
        the guard is defeated: `## Plan — Continue skilled therapy... gait training...` earned a
        97116 chip for a treatment that had not happened yet. Replaying the repair over 21 real
        folded headings removed 5 such chips, every one on a Summary or Plan section — none was
        ever a treatment section. That makes this a billing-safety fix, not a formatting one.
        """
        from app.generate import cpt
        h = ("Plan — Continue skilled therapy sessions twice weekly for four more weeks and "
             "progress to gait training on uneven surfaces once tolerance improves.")
        self.assertIsNotNone(cpt.code_for_heading(h), "precondition: the fold earns a chip today")
        out = postprocess.apply("followup", [_sec(h, "")])
        self.assertEqual(out[0]["heading"], "Plan")
        self.assertIsNone(cpt.code_for_heading(out[0]["heading"]),
                          "a Plan section must not carry a treatment CPT chip")
        self.assertNotIn("[[CPT:", out[0]["body"])
        self.assertIn("gait training", out[0]["body"], "the text itself is preserved, just moved")

    def test_a_short_heading_carrying_a_value_is_also_folded(self):
        """Found on the real after-repair sweep (record 2001): the 6 long folds were repaired, but
        6 SHORT headings still carried their value inline with an empty body. Same failure under
        the length threshold, and it matters for the same reason — with an empty body,
        `flag_unsupported_vitals` cannot see the BP at all, so an INVENTED one passes unflagged.
        """
        for heading, want_label, want_body in [
            ("Vitals — BP: 120/80 mmHg, HR: 72 bpm", "Vitals", "BP: 120/80 mmHg, HR: 72 bpm"),
            ("Pain - At Rest — 3/10", "Pain - At Rest", "3/10"),
            ("Short-Term Goals — MET", "Short-Term Goals", "MET"),
            ("Response to Treatment — Good", "Response to Treatment", "Good"),
        ]:
            with self.subTest(heading=heading):
                out = postprocess.split_folded_headings([_sec(heading, "")])[0]
                self.assertEqual(out["heading"], want_label)
                self.assertEqual(out["body"], want_body)

    def test_a_short_real_heading_is_never_mangled(self):
        """The other side. `## Pain - At Rest` is a real template label containing a hyphen, and
        `## Vitals` with nothing dictated is a legitimate empty section. Only the em/en dash — the
        template spec's own "Label — description" format — counts as a fold in a short heading;
        splitting on the hyphen or a colon would destroy real labels."""
        for heading in ("Vitals", "Pain - At Rest", "Coordination / Sensation / Edema",
                        "Plan of Treatment", "Objective Summary"):
            with self.subTest(heading=heading):
                secs = [_sec(heading, "")]
                self.assertEqual(postprocess.split_folded_headings(secs), secs)

    def test_a_short_heading_the_split_cannot_parse_is_left_alone(self):
        """The truncation fallback exists for long folded prose. Applying it to a short label we
        simply couldn't parse would mangle a legitimate heading for no benefit."""
        secs = [_sec("— — —", "")]
        self.assertEqual(postprocess.split_folded_headings(secs), secs)

    def test_is_folded_heading_predicate_is_exported_for_the_eval(self):
        self.assertTrue(postprocess.is_folded_heading(_sec(self.REAL, "")))
        self.assertFalse(postprocess.is_folded_heading(_sec("Vitals", "")))
        self.assertFalse(postprocess.is_folded_heading(_sec(self.REAL, "real body")))


if __name__ == "__main__":
    unittest.main()


class SpecInstructionHeadingTests(unittest.TestCase):
    """The model copying the template's field INSTRUCTION onto the heading line.

    Every heading below is verbatim from a real MedGemma Follow-Up generation in a seeded batch
    (2 of 6 notes), each with correct clinical content in the body underneath.

    `split_folded_headings` cannot cover this: it requires an EMPTY body, and it MOVES text rather
    than deleting it, which is right for content and wrong for boilerplate that belongs in neither
    the heading nor the body.
    """

    def test_strips_the_instruction_and_keeps_the_body(self):
        sections = [{
            "heading": "Precautions — weight-bearing status, range-of-motion limits, and any "
                       "other precautions still in effect.",
            "body": "Weight-bearing as tolerated. Left hip ROM limited to 90 degrees of flexion.",
        }]
        out = postprocess.strip_spec_instruction_headings("followup", sections)
        self.assertEqual(out[0]["heading"], "Precautions")
        self.assertEqual(out[0]["body"], sections[0]["body"], "body must be untouched")

    def test_strips_a_heading_that_is_under_the_fold_threshold(self):
        """The repair is about instruction text, not length. "Vitals — Blood pressure and heart
        rate." is only 39 chars, so no length-based check would ever reach it."""
        sections = [{"heading": "Vitals — Blood pressure and heart rate.",
                     "body": "BP 128/76, HR 72."}]
        out = postprocess.strip_spec_instruction_headings("followup", sections)
        self.assertEqual(out[0]["heading"], "Vitals")

    def test_leaves_a_heading_whose_tail_is_not_in_the_spec(self):
        """The safety property. Deletion is only defensible because the removed text is matched
        against the form's OWN spec; a tail the template never wrote is real content and stays."""
        sections = [{"heading": "Gait Training — 300 feet with no device today",
                     "body": "Patient ambulated 300 feet."}]
        out = postprocess.strip_spec_instruction_headings("followup", sections)
        self.assertEqual(out[0]["heading"], sections[0]["heading"])

    def test_leaves_an_ordinary_heading_alone(self):
        sections = [{"heading": "Therapeutic Exercise", "body": "Minutes: 20. Four-way hip."}]
        out = postprocess.strip_spec_instruction_headings("followup", sections)
        self.assertEqual(out[0]["heading"], "Therapeutic Exercise")

    def test_unknown_form_is_a_no_op(self):
        sections = [{"heading": "Anything — with a tail", "body": "x"}]
        self.assertEqual(
            postprocess.strip_spec_instruction_headings("no_such_form", sections), sections)

    def test_apply_strips_before_the_fold_repair(self):
        """Order guard. With an EMPTY body, split_folded_headings would move the instruction text
        down into the body, where it would masquerade as clinical content and nothing removes it.
        Stripping first means the fold repair only ever sees real content."""
        sections = [_sec("Precautions — weight-bearing status, range-of-motion limits, and any "
                         "other precautions still in effect.", "")]
        out = postprocess.apply("followup", sections)
        self.assertTrue(out, "the section should survive")
        self.assertEqual(out[0]["heading"], "Precautions")
        self.assertNotIn("weight-bearing status, range-of-motion limits", out[0]["body"],
                         "template boilerplate must not be relocated into the body")

    def test_is_idempotent(self):
        sections = [{"heading": "Vitals — Blood pressure and heart rate.", "body": "BP 128/76."}]
        once = postprocess.strip_spec_instruction_headings("followup", sections)
        twice = postprocess.strip_spec_instruction_headings("followup", once)
        self.assertEqual(once, twice)
