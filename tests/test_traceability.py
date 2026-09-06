"""Tests for the traceability/verification spike (app/generate/traceability.py).

The load-bearing behavior: a clinical value in the note that the clinician never said shows up
as UNANCHORED — that's the fabrication/billing-fraud flag (product-strategy.md item 13). The
matcher has to bridge spoken transcript ('four out of five') and normalized note ('4/5').

    .venv/Scripts/python.exe -m unittest tests.test_traceability -v
"""

import unittest

from app.generate.traceability import (
    add_verification_flags,
    anchor_note_to_transcript,
    flag_cross_section_duplication,
    flag_unanchored_in_sections,
    flag_unanchored_pain_fields,
    flag_unsupported_devices,
    flag_unsupported_normals,
    flag_unsupported_vitals,
    normalize_for_matching,
    unanchored_values,
)


def _psec(body):
    return {"heading": "Pain", "body": body, "carried_forward": False}


class PainFieldFabricationTests(unittest.TestCase):
    """A rigid Worst/Best/Current /10 template invites the model to invent scores; catch it."""

    def test_invented_worst_best_current_flagged_when_no_pain_stated(self):
        body = "Worst: 10\nBest: 10\nCurrent: 10"
        out = flag_unanchored_pain_fields([_psec(body)], "patient reports neck and back pain, no numbers given")[0]["body"]
        self.assertIn("pain rating", out)
        self.assertIn('"10/10"', out)

    def test_stated_pain_score_not_flagged(self):
        # "current four out of ten" anchors "Current: 4".
        out = flag_unanchored_pain_fields([_psec("Current: 4")], "pain is currently four out of ten")[0]["body"]
        self.assertNotIn("pain rating", out)

    def test_dose_number_is_not_read_as_pain(self):
        out = flag_unanchored_pain_fields([_psec("Current dose 10 mg")], "no pain rating")[0]["body"]
        self.assertNotIn("pain rating", out)

    def test_wired_into_add_verification_flags(self):
        out = add_verification_flags([_psec("Worst: 8")], "no pain score stated")[0]["body"]
        self.assertIn('pain rating "8/10"', out)


class NormalizeTests(unittest.TestCase):
    def test_mmt_range_spoken(self):
        self.assertEqual(normalize_for_matching("three plus out of five"), "3+/5")

    def test_pain_spoken(self):
        self.assertEqual(normalize_for_matching("four out of ten"), "4/10")

    def test_minutes_spoken(self):
        self.assertEqual(normalize_for_matching("fifteen minutes"), "15 minutes")

    def test_compound_tens(self):
        self.assertEqual(normalize_for_matching("forty five minutes"), "45 minutes")

    def test_grossly_five(self):
        self.assertEqual(normalize_for_matching("grossly five out of five"), "grossly 5/5")

    def test_written_form_passes_through(self):
        self.assertEqual(normalize_for_matching("4 out of 5"), "4/5")

    def test_mmt_range_distributes_denominator(self):
        # Regression (found on a real generation): the spoken denominator applies to BOTH grades.
        self.assertEqual(normalize_for_matching("three plus to four minus out of five"), "3+/5 to 4-/5")

    def test_spoken_hundreds(self):
        self.assertEqual(normalize_for_matching("one hundred twenty degrees"), "120 degrees")

    def test_spoken_hundreds_with_and(self):
        self.assertEqual(normalize_for_matching("one hundred and twenty degrees"), "120 degrees")

    def test_colloquial_a_hundred(self):
        self.assertEqual(normalize_for_matching("a hundred degrees"), "100 degrees")

    def test_over_form(self):
        self.assertEqual(normalize_for_matching("four over ten"), "4/10")

    def test_none_input_is_safe(self):
        self.assertEqual(normalize_for_matching(None), "")


class SpokenThousandsTests(unittest.TestCase):
    """A community-distance goal is dictated "one thousand feet". Before `thousand` was a scale
    word the run parser stopped at "one", the transcript read "1 thousand feet", and the note's
    honest "1000 feet" drew a fabrication flag — a false amber marker on a correct value, which
    is worse than a miss because it trains the clinician to skim past the real ones."""

    def test_one_thousand(self):
        self.assertEqual(normalize_for_matching("one thousand feet"), "1000 feet")

    def test_thousands_with_hundreds(self):
        self.assertEqual(normalize_for_matching("one thousand five hundred feet"), "1500 feet")

    def test_year_form_still_parses(self):
        self.assertEqual(normalize_for_matching("two thousand eight"), "2008")

    def test_goal_distance_anchors_end_to_end(self):
        self.assertEqual(
            unanchored_values("Goal: ambulate 1000 feet with a straight cane.",
                              "patient will ambulate community distances of one thousand feet"),
            [],
        )


class SpokenDecimalTests(unittest.TestCase):
    """Spoken decimals are read digit by digit: "point six eight" is 0.68, not 0.14. Summing the
    words was the old behaviour and it INVENTED a value, so a real dictated gait speed had nothing
    to anchor to."""

    def test_leading_point(self):
        self.assertEqual(normalize_for_matching("point six eight meters per second"),
                         "0.68 meters per second")

    def test_decimal_after_whole(self):
        self.assertEqual(normalize_for_matching("eighteen point four seconds"), "18.4 seconds")

    def test_compound_whole_with_decimal(self):
        self.assertEqual(normalize_for_matching("sixty one point four"), "61.4")

    def test_sub_milligram_dose(self):
        self.assertEqual(normalize_for_matching("point four milligrams daily"), "0.4 milligrams daily")

    def test_non_digit_tail_falls_back(self):
        self.assertEqual(normalize_for_matching("point twenty five"), "0.25")

    def test_point_as_a_clinical_word_is_left_alone(self):
        # "point" only ever acts as a connector when a number word follows it, so the ordinary
        # clinical uses must survive untouched.
        for phrase in ("trigger point release", "point tenderness over the joint line",
                       "a five point scale"):
            with self.subTest(phrase=phrase):
                self.assertIn("point", normalize_for_matching(phrase))

    def test_gait_speed_anchors_end_to_end(self):
        self.assertEqual(
            unanchored_values("Gait speed 0.68 meters per second with the walker.",
                              "gait speed measured over ten meters was point six eight meters per second"),
            [],
        )


class SpokenBloodPressureTests(unittest.TestCase):
    """A spoken BP uses the colloquial hundreds form. "one thirty eight over eighty two" summed to
    39, i.e. the normalizer produced a number nobody said. The rewrite is scoped to the
    "<value> over <value>" idiom because that is the only place the reading is unambiguous —
    "one thirty" on its own is a clock time as often as a pressure."""

    def test_colloquial_systolic(self):
        self.assertEqual(normalize_for_matching("one thirty eight over eighty two"), "138/82")

    def test_round_systolic(self):
        self.assertEqual(normalize_for_matching("one forty over ninety"), "140/90")

    def test_oh_form(self):
        self.assertEqual(normalize_for_matching("one oh five over seventy"), "105/70")

    def test_teens_second_component(self):
        self.assertEqual(normalize_for_matching("one ten over seventy"), "110/70")

    def test_two_hundreds(self):
        self.assertEqual(normalize_for_matching("two twenty over one ten"), "220/110")

    def test_explicit_hundred_form_unchanged(self):
        self.assertEqual(normalize_for_matching("one hundred thirty eight over eighty two"), "138/82")

    def test_two_digit_bp_unaffected(self):
        self.assertEqual(normalize_for_matching("ninety over sixty"), "90/60")

    def test_written_bp_unaffected(self):
        self.assertEqual(normalize_for_matching("blood pressure 138 over 82"), "blood pressure 138/82")

    def test_over_without_a_following_number_is_not_a_pressure(self):
        # The lookahead requires a number after "over", so a preposition never triggers the rewrite.
        self.assertNotIn("130", normalize_for_matching("one thirty over the course of the week"))


class AnchoredTests(unittest.TestCase):
    def _anchored_values(self, note, transcript):
        return {a.value for a in anchor_note_to_transcript(note, transcript) if a.anchored}

    def test_mmt_spoken_transcript_anchors_normalized_note(self):
        self.assertIn("3+/5", self._anchored_values("Quad strength 3+/5.", "quad is three plus out of five"))

    def test_pain_anchors(self):
        self.assertIn("4/10", self._anchored_values("Pain 4/10 at rest.", "pain is four out of ten at rest"))

    def test_minutes_anchor_written_and_spoken(self):
        self.assertIn("15 minutes", self._anchored_values("Ther-ex 15 minutes.", "did fifteen minutes of exercise"))

    def test_mmt_range_both_grades_anchor(self):
        # Regression: a dictated MMT range must anchor BOTH normalized grades, not just the second.
        vals = self._anchored_values("Strength 3+/5 to 4-/5.", "quad is three plus to four minus out of five")
        self.assertIn("3+/5", vals)
        self.assertIn("4-/5", vals)

    def test_distance_anchors_spoken_hundreds(self):
        self.assertIn("100 feet", self._anchored_values("Ambulated 100 feet.", "walked one hundred feet with a walker"))

    def test_fabricated_distance_is_flagged(self):
        note = "Ambulated 200 feet independently."
        transcript = "patient walked one hundred feet with contact guard"
        self.assertIn("200 feet", {a.value for a in unanchored_values(note, transcript)})


class FabricationFlagTests(unittest.TestCase):
    """The point of the feature: unstated numbers get flagged."""

    def test_value_absent_from_transcript_is_unanchored(self):
        note = "Right quad strength 4/5."
        transcript = "patient reports shoulder pain, no strength testing performed"
        flagged = {a.value for a in unanchored_values(note, transcript)}
        self.assertIn("4/5", flagged)

    def test_wrong_number_is_unanchored(self):
        # Transcript says 15 minutes; note claims 30 -> 30 must be flagged, 15 would not.
        note = "Endurance 30 minutes."
        transcript = "we did fifteen minutes"
        self.assertIn("30 minutes", {a.value for a in unanchored_values(note, transcript)})

    def test_real_soap_run_fabrications_are_all_flagged(self):
        # The exact case the seam smoke-test produced: dictation mentioned only pain 4/10 and
        # 15 minutes of ther-ex, but the model invented ROM, strength, and a 30-min endurance.
        transcript = (
            "Patient reports right shoulder pain four out of ten with overhead reach. Performed "
            "therapeutic exercise fifteen minutes, rotator cuff strengthening. Tolerated well."
        )
        note = (
            "Pain 4/10. Right shoulder ROM 120 degrees forward elevation, 110 degrees external "
            "rotation. Strength 4/5 at 60 degrees. Endurance 30 minutes."
        )
        flagged = {a.value for a in unanchored_values(note, transcript)}
        self.assertEqual(flagged, {"120 degrees", "110 degrees", "60 degrees", "4/5", "30 minutes"})

    def test_stated_value_not_flagged(self):
        transcript = "pain is four out of ten"
        note = "Pain 4/10 at rest."
        self.assertEqual(unanchored_values(note, transcript), [])

    def test_pain_over_form_anchors(self):
        # "four over ten" must anchor the note's "4/10" (no false fabrication flag).
        self.assertEqual(unanchored_values("Pain 4/10 at rest.", "pain is four over ten at rest"), [])

    def test_spoken_hundreds_rom_is_not_false_flagged(self):
        # The false-positive that motivated hundreds parsing: real spoken ROM must anchor.
        transcript = "knee flexion to one hundred twenty degrees today"
        note = "Knee flexion 120 degrees."
        self.assertEqual(unanchored_values(note, transcript), [])


class SectionFlaggingTests(unittest.TestCase):
    """flag_unanchored_in_sections is what the /api/generate pipeline actually calls."""

    def _body(self, body, transcript):
        secs = [{"heading": "Objective", "body": body, "carried_forward": False}]
        return flag_unanchored_in_sections(secs, transcript)[0]["body"]

    def test_fabricated_value_gets_amber_marker(self):
        out = self._body("Strength 4/5.", "patient reports shoulder pain, no strength testing")
        self.assertIn('[[NEEDS: "4/5" not found in dictation', out)

    def test_anchored_section_is_untouched(self):
        body = "Pain 4/10 at rest."
        out = self._body(body, "pain four out of ten at rest")
        self.assertEqual(out, body)

    def test_value_already_inside_existing_needs_is_not_double_flagged(self):
        # If the model/postprocess already flagged it, don't append a second marker for it.
        body = 'Strength [[NEEDS: 4/5 — clinician to confirm]]'
        out = self._body(body, "no strength testing done")
        self.assertEqual(out.count("[[NEEDS:"), 1)

    def test_original_body_text_is_preserved(self):
        out = self._body("ROM 120 degrees forward elevation.", "no range of motion measured")
        self.assertTrue(out.startswith("ROM 120 degrees forward elevation."))
        self.assertIn('[[NEEDS: "120 degrees" not found', out)


class UnsupportedNormalsTests(unittest.TestCase):
    """flag_unsupported_normals — the invented-normal fabrication class (CLAUDE.md rule 19)."""

    def _body(self, body, transcript):
        secs = [{"heading": "Exam", "body": body, "carried_forward": False}]
        return flag_unsupported_normals(secs, transcript)[0]["body"]

    def test_unmentioned_skin_normal_is_flagged(self):
        out = self._body("Skin intact.", "patient reports knee pain and difficulty with stairs")
        self.assertIn("skin/integumentary stated as normal", out)

    def test_mentioned_skin_is_not_flagged(self):
        out = self._body("Skin intact and dry.", "the skin around the incision looked clean")
        self.assertEqual(out, "Skin intact and dry.")

    def test_integumentary_synonym_is_flagged(self):
        # Regression (real run): the model wrote "Integumentary: Unremarkable" instead of "skin".
        self.assertIn("skin/integumentary stated as normal", self._body("Integumentary: Unremarkable.", "worked on gait today"))

    def test_no_edema_flagged_when_swelling_unmentioned(self):
        self.assertIn("edema stated as normal", self._body("No edema noted.", "gait training performed"))

    def test_no_edema_not_flagged_when_swelling_mentioned(self):
        # Clinician phrased it as "swelling" — the broad keyword set must still anchor it.
        self.assertEqual(self._body("No edema.", "some swelling noted at the ankle"), "No edema.")

    def test_o2_normal_flagged_when_unmentioned(self):
        self.assertIn("oxygen saturation stated as normal", self._body("O2 at rest and with activity normal.", "blood pressure 130 over 80"))

    def test_cognition_anchored_by_alert_and_oriented(self):
        self.assertEqual(self._body("Cognitively intact.", "patient is alert and oriented times three"), "Cognitively intact.")

    def test_rule19_real_scenario_flags_each_untouched_system(self):
        # The exact invented-normals block from the CLAUDE.md rule 19 real run, against a dictation
        # that only covered gait — skin/neuro/cognition/coordination/sensation/edema all invented.
        transcript = "patient ambulated 100 feet with a rolling walker at contact guard"
        body = ("Skin intact. Neurological exam unremarkable. Cognitively intact. "
                "Coordination intact. Sensation intact. No edema noted.")
        out = self._body(body, transcript)
        for label in ("skin/integumentary", "neurological exam", "cognition", "coordination", "sensation", "edema"):
            self.assertIn(f"{label} stated as normal", out)


class UnsupportedDevicesTests(unittest.TestCase):
    """flag_unsupported_devices — the invented-assistive-device class (CLAUDE.md rule 14)."""

    def _body(self, body, transcript):
        return flag_unsupported_devices([{"heading": "Mobility", "body": body, "carried_forward": False}], transcript)[0]["body"]

    def test_invented_cane_is_flagged(self):
        out = self._body("Ambulates with a cane.", "patient walked 100 feet with contact guard")
        self.assertIn('assistive device "cane" not mentioned', out)

    def test_dictated_device_not_flagged(self):
        # Head-noun anchoring: note says "rolling walker", dictation says "walker" -> anchored.
        self.assertEqual(self._body("Ambulates with a rolling walker.", "used a walker today"), "Ambulates with a rolling walker.")

    def test_negated_device_not_flagged(self):
        self.assertEqual(self._body("Ambulates without a cane.", "walked independently"), "Ambulates without a cane.")


class UnsupportedVitalsTests(unittest.TestCase):
    def _body(self, body, transcript):
        return flag_unsupported_vitals([{"heading": "Vitals", "body": body, "carried_forward": False}], transcript)[0]["body"]

    def test_invented_bp_is_flagged(self):
        self.assertIn("blood pressure value stated", self._body("BP 130/80.", "heart rate was 74"))

    def test_dictated_bp_not_flagged(self):
        self.assertEqual(self._body("BP 130/80.", "blood pressure one thirty over eighty"), "BP 130/80.")

    def test_mmt_grade_does_not_trigger_bp(self):
        # "3+/5" must NOT be read as a BP value (single digits).
        self.assertEqual(self._body("Quad 3+/5.", "no vitals taken"), "Quad 3+/5.")

    def test_invented_hr_is_flagged(self):
        self.assertIn("heart rate value stated", self._body("HR 74.", "blood pressure 130 over 80"))

    def test_hr_not_stated_is_not_flagged(self):
        # Regression (real run): the model honestly wrote "HR: Not stated" — must NOT be flagged.
        self.assertEqual(self._body("BP: Not stated. HR: Not stated.", "did some exercises"), "BP: Not stated. HR: Not stated.")

    def test_date_is_not_misread_as_blood_pressure(self):
        # "12/08/2026" is a date, not a BP — the lookbehind/lookahead must reject it.
        self.assertEqual(self._body("Certification period 12/08/2026.", "no vitals taken"), "Certification period 12/08/2026.")

    def test_invented_o2_saturation_is_flagged(self):
        self.assertIn("oxygen saturation value stated", self._body("O2 95%.", "blood pressure 130 over 80"))

    def test_dictated_o2_not_flagged(self):
        self.assertEqual(self._body("O2 95%.", "oxygen was 95 percent on room air"), "O2 95%.")


class CrossSectionDuplicationTests(unittest.TestCase):
    def _sec(self, heading, body):
        return {"heading": heading, "body": body, "carried_forward": False}

    def test_long_duplicate_sentence_flags_both_sections(self):
        dup = "Patient ambulated 100 feet with a rolling walker and contact guard assistance."
        secs = [self._sec("Objective Summary", dup), self._sec("Functional Mobility", dup)]
        out = flag_cross_section_duplication(secs)
        self.assertTrue(all("duplicated across sections" in s["body"] for s in out))

    def test_short_shared_phrase_not_flagged(self):
        secs = [self._sec("A", "Pain 4/10 at rest."), self._sec("B", "Pain 4/10 with activity.")]
        out = flag_cross_section_duplication(secs)
        self.assertTrue(all("duplicated" not in s["body"] for s in out))

    def test_unique_sections_untouched(self):
        secs = [self._sec("A", "Quad strength is three plus out of five today."),
                self._sec("B", "Gait is steady over level ground without a device.")]
        self.assertEqual(flag_cross_section_duplication(secs), secs)


class CombinedVerificationTests(unittest.TestCase):
    def test_flags_both_value_and_normal(self):
        secs = [{"heading": "Objective", "body": "Strength 4/5. Sensation intact.", "carried_forward": False}]
        out = add_verification_flags(secs, "patient reports pain, no exam performed")[0]["body"]
        self.assertIn('"4/5" not found', out)
        self.assertIn("sensation stated as normal", out)

    def test_flags_device_and_vital_too(self):
        secs = [{"heading": "Objective", "body": "Ambulates with a cane. BP 130/80.", "carried_forward": False}]
        out = add_verification_flags(secs, "patient did some exercises")[0]["body"]
        self.assertIn('assistive device "cane" not mentioned', out)
        self.assertIn("blood pressure value stated", out)

    def test_supported_content_untouched(self):
        secs = [{"heading": "Objective", "body": "Pain 4/10.", "carried_forward": False}]
        out = add_verification_flags(secs, "pain is four out of ten")[0]["body"]
        self.assertEqual(out, "Pain 4/10.")


class DegreesAndPainAnchoringRegressionTests(unittest.TestCase):
    """Real-run false positives (synthetic-run-outputs): ROM stated as a bare number ("flexion
    ninety") and pain best/current stated as bare numbers ("best two, currently four") were wrongly
    flagged as fabricated. Lock the fix — and that a genuine fabrication is STILL flagged (no new
    false negatives)."""

    def test_rom_degrees_bare_number_anchors(self):
        note = "Range of Motion: shoulder flexion 90 degrees, abduction 80 degrees, external rotation 15 degrees"
        transcript = "active flexion ninety, abduction eighty, external rotation fifteen"
        self.assertEqual(unanchored_values(note, transcript), [])

    def test_fabricated_rom_degrees_still_flagged(self):
        note = "Range of Motion: flexion 150 degrees"
        self.assertIn("150 degrees", {a.value for a in unanchored_values(note, "active flexion ninety")})

    def test_rom_degrees_does_not_anchor_to_blood_pressure_component(self):
        # "80 degrees" must NOT be anchored by the "80" inside a blood pressure "130/80".
        note = "Range of Motion: knee flexion 80 degrees"
        transcript = "blood pressure one thirty over eighty, heart rate seventy"
        self.assertIn("80 degrees", {a.value for a in unanchored_values(note, transcript)})

    def test_pain_best_current_bare_numbers_anchor(self):
        note = "Pain: Worst 7/10, Best 2/10, Current 4/10"
        transcript = "pain worst is like seven out of ten, best two, right now about four"
        self.assertEqual(unanchored_values(note, transcript), [])

    def test_pain_currently_variant_anchors(self):
        note = "Pain: Worst 8/10, Best 3/10, Current 5/10"
        transcript = "worst eight out of ten, best three, currently five"
        self.assertEqual(unanchored_values(note, transcript), [])

    def test_fabricated_pain_score_still_flagged(self):
        note = "Pain: Best 6/10"
        self.assertIn("6/10", {a.value for a in unanchored_values(note, "pain worst seven out of ten, best two")})

    def test_pain_shorthand_does_not_touch_a_med_dose(self):
        self.assertNotIn("5/10", normalize_for_matching("takes current 5 mg dose"))


if __name__ == "__main__":
    unittest.main()
