"""Recovering sections the model mislabelled, shifted, or stranded on a heading line.

All three repairs here came out of ONE measured failure. On 3 of 4 real Follow-Up generations the
model turned the template's own TITLE LINE into a section heading:

    ## Follow-Up Visit
    Precautions [carry forward] — weight-bearing status, no lifting over ten pounds overhead.

That does two things, and the second is the damaging one. It invents a section nobody asked for,
and it CONSUMES the real first section — "Summary of Daily Skilled Services" vanishes and the
Precautions content ends up under a heading that is not Precautions. `Precautions` is a
CARRY-FORWARD label, so `CARRY_SECTION_LABELS` stops matching it and the NEXT visit has nothing to
carry forward. A cosmetic-looking heading bug quietly disables a feature one visit later.

Measured effect of the three repairs together, over the same 25 real notes: Follow-Up template
conformance 62% -> 75%, empty bodies 3 -> 2, and `initial` / `initial_updated` unchanged at 95% and
100% (no regression).

Every repair is anchored on labels the TEMPLATE ITSELF declares (`forms.spec_section_labels`), so
it can only ever relabel or relocate something the template named — never invent a section. The
false-positive tests matter more than the positive ones: a wrong relabel silently files clinical
content under the wrong heading, which is worse than the bug being fixed.

    .venv/Scripts/python.exe -m unittest tests.test_section_recovery -v
"""

import unittest

from app.generate import forms, postprocess


def _sec(heading, body, carried=False):
    return {"heading": heading, "body": body, "carried_forward": carried}


class SpecLabelTests(unittest.TestCase):
    """ONE definition of "what did this template ask for", shared by the repairs and by
    scripts/audit_notes.py — a second copy would let the app and the thing measuring the app
    disagree about the template."""

    def test_field_per_section_labels(self):
        labels = forms.spec_section_labels("followup")
        for expected in ("Summary of Daily Skilled Services", "Precautions", "Short-Term Goals",
                         "Plan"):
            self.assertIn(expected, labels)

    def test_block_format_labels(self):
        self.assertEqual(forms.spec_section_labels("initial_updated"),
                         ["Subjective", "Objective", "Assessment", "Plan"])

    def test_the_title_is_not_mistaken_for_a_section(self):
        self.assertEqual(forms.spec_title("followup"), "FOLLOW-UP VISIT")
        self.assertNotIn("FOLLOW-UP VISIT", forms.spec_section_labels("followup"))

    def test_instruction_prose_is_excluded(self):
        for label in forms.spec_section_labels("initial"):
            self.assertLessEqual(len(label.split()), 7, label)


class TitleHeadingTests(unittest.TestCase):
    def test_a_title_heading_is_relabelled_from_its_body(self):
        out = postprocess.relabel_spec_title_heading("followup", [
            _sec("Follow-Up Visit", "Precautions [carry forward] — weight-bearing as tolerated."),
        ])
        self.assertEqual(out[0]["heading"], "Precautions")
        self.assertEqual(out[0]["body"], "weight-bearing as tolerated.")

    def test_recovering_the_label_restores_carry_forward(self):
        """The reason this is not cosmetic. With the heading left as the title, the section is not
        a carry-forward label any more, and the next visit carries nothing."""
        sections = postprocess.apply("followup", [
            _sec("Follow-Up Visit", "Precautions [carry forward] — no overhead lifting.", True),
        ])
        self.assertEqual(sections[0]["heading"], "Precautions")
        self.assertIn("Precautions", forms.CARRY_SECTION_LABELS["followup"])

    def test_the_carry_snapshot_actually_recovers(self):
        """The end of the causal chain, and the reason this is not a cosmetics fix.

        Verified against real run 14 (docs/synthetic-run-outputs-full.json): with the heading left
        as the template's title, `carry_forward.extract_snapshot_fields` captured NOTHING — so the
        patient's NEXT visit would have had no precautions to carry forward, one visit after a bug
        that only ever looked like a wrong heading.
        """
        from app.storage import carry_forward
        sections = postprocess.apply("followup", [
            _sec("Follow-Up Visit",
                 "Precautions [carry forward] — weight-bearing status, no lifting over ten "
                 "pounds overhead.", True),
        ])
        snapshot = carry_forward.extract_snapshot_fields("followup", sections)
        self.assertTrue(snapshot.get("precautions"),
                        "the next visit would carry nothing forward")
        self.assertIn("no lifting over ten pounds", snapshot["precautions"])

    def test_a_title_heading_whose_body_reveals_nothing_is_left_alone(self):
        """A miss is recoverable; a wrong relabel files clinical content under the wrong heading."""
        sections = [_sec("Follow-Up Visit", "Patient did well today.")]
        self.assertEqual(postprocess.relabel_spec_title_heading("followup", sections), sections)

    def test_a_real_section_heading_is_never_relabelled(self):
        sections = [_sec("Precautions", "Summary of Daily Skilled Services — worked on gait.")]
        out = postprocess.relabel_spec_title_heading("followup", sections)
        self.assertEqual(out[0]["heading"], "Precautions")


class ShiftedBodyTests(unittest.TestCase):
    def test_a_following_sections_content_is_split_back_out(self):
        out = postprocess.split_shifted_section_bodies("followup", [
            _sec("Pain - At Rest 1/10", "Pain - With Movement 4/10"),
        ])
        self.assertEqual([s["heading"] for s in out], ["Pain - At Rest 1/10", "Pain - With Movement"])
        self.assertEqual(out[1]["body"], "4/10")

    def test_the_full_chain_recovers_both_values(self):
        """The split leaves an empty body, which is exactly the shape the fold repair then fixes —
        so the stranded heading value ends up somewhere the verification layer can see it."""
        out = postprocess.apply("followup", [_sec("Pain - At Rest 1/10", "Pain - With Movement 4/10")])
        got = {s["heading"]: s["body"] for s in out}
        self.assertEqual(got.get("Pain - At Rest"), "1/10")
        self.assertEqual(got.get("Pain - With Movement"), "4/10")

    def test_prose_mentioning_an_existing_section_is_not_split(self):
        """The guard that makes this safe. A Plan body opening "Short-Term Goals will be
        reassessed…" is prose, and the giveaway is that Short-Term Goals ALREADY exists."""
        sections = [
            _sec("Short-Term Goals", "Walk 300 feet."),
            _sec("Plan", "Short-Term Goals will be reassessed in two weeks."),
        ]
        self.assertEqual(postprocess.split_shifted_section_bodies("followup", sections), sections)

    def test_an_undeclared_label_is_not_split(self):
        sections = [_sec("Plan", "Random Capitalised Words follow here.")]
        self.assertEqual(postprocess.split_shifted_section_bodies("followup", sections), sections)


class DeclaredLabelHeadingTests(unittest.TestCase):
    def test_a_non_numeric_value_comes_off_the_heading(self):
        """`split_folded_headings` cannot see this one — "Good" is a value to a reader and nothing
        to a regex. The template's own label is what makes it tractable."""
        out = postprocess.split_declared_label_headings("followup", [
            _sec("Response to Treatment Good", ""),
        ])
        self.assertEqual(out[0]["heading"], "Response to Treatment")
        self.assertEqual(out[0]["body"], "Good")

    def test_a_label_continuation_is_not_treated_as_a_value(self):
        """"Plan of Treatment" starts with the declared label "Plan". Splitting it would invent a
        "Plan" section whose body is "of Treatment"."""
        sections = [_sec("Plan of Treatment", "")]
        self.assertEqual(postprocess.split_declared_label_headings("followup", sections), sections)

    def test_a_populated_body_blocks_the_split(self):
        sections = [_sec("Response to Treatment Good", "She tolerated it well.")]
        self.assertEqual(postprocess.split_declared_label_headings("followup", sections), sections)

    def test_an_exact_label_is_untouched(self):
        for heading in ("Plan", "Precautions", "Pain - At Rest", "Functional Status"):
            with self.subTest(heading=heading):
                sections = [_sec(heading, "")]
                self.assertEqual(
                    postprocess.split_declared_label_headings("followup", sections), sections)

    def test_a_code_heading_is_left_to_rule_12(self):
        sections = [_sec("CPT Codes 97110", "")]
        self.assertEqual(postprocess.split_declared_label_headings("followup", sections), sections)


class RedundantLabelTests(unittest.TestCase):
    def test_a_body_restating_its_own_heading_is_trimmed(self):
        out = postprocess.strip_redundant_body_label("followup", [
            _sec("Long-Term Goals", "Long-Term Goals [carry forward] — return to full duty."),
        ])
        self.assertEqual(out[0]["body"], "return to full duty.")

    def test_it_never_empties_a_section(self):
        """Trading a cosmetic problem for a lost one is not an improvement."""
        sections = [_sec("Precautions", "Precautions")]
        self.assertEqual(postprocess.strip_redundant_body_label("followup", sections), sections)

    def test_an_unrelated_body_is_untouched(self):
        sections = [_sec("Precautions", "Weight-bearing as tolerated.")]
        self.assertEqual(postprocess.strip_redundant_body_label("followup", sections), sections)


class SectionRosterNotUsedTests(unittest.TestCase):
    """The roster rule was tried, measured, and REVERTED. These tests lock the revert.

    Enabling it (confounded with an extra template section) took Follow-Up section coverage from
    93% to 47% over the same 5 real records — three of five notes stopped after the treatment
    sections with no Plan, no Goals, no Functional Status. Value capture rose 57% -> 65% at the
    same time, which is exactly the trade that looks like progress and is not: a note missing its
    Plan is not improved by containing more measurements.

    The function is kept, unused, so the negative result stays attached to the idea. If someone
    re-enables it, these tests fail and point them at the measurement first.
    """

    def test_the_roster_does_not_reach_the_prompt(self):
        from app.generate.forms import FORMS
        from app.generate.prompt import PatientContext, build_prompt
        prompt = build_prompt(FORMS["followup"], PatientContext(name="T", sub="—"),
                              "gait training fifteen minutes", "", None)
        self.assertNotIn("REQUIRED SECTIONS", prompt,
                         "the roster measured WORSE — re-read _section_roster_rule before "
                         "re-enabling it, and change one thing at a time")

    def test_the_function_is_kept_for_the_record(self):
        """Deleting it would delete the finding with it."""
        from app.generate.forms import FORMS
        from app.generate.prompt import _section_roster_rule
        self.assertIn("REQUIRED SECTIONS", _section_roster_rule(FORMS["followup"]))
        self.assertIn("MEASURED HARMFUL", _section_roster_rule.__doc__)

    def test_the_template_has_no_objective_measures_section(self):
        """The other half of the same revert. Adding it was well-motivated — 15 of 22 dropped
        values were ROM/MMT with nowhere to go — but it shipped alongside the roster and the pair
        regressed section coverage badly. The rule-15 gap is real and still open; the fix has to
        be re-attempted on its own."""
        self.assertNotIn("Objective Measures", forms.spec_section_labels("followup"))


if __name__ == "__main__":
    unittest.main()
