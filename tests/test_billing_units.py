"""The Medicare 8-minute rule and which codes it applies to.

Two invariants live here, and both are money:

  1. `units_for_minutes` is a CLOSED FORM of the published table. The closed form is what runs;
     the literal table is what the rule says. This suite walks every integer 0..200 through both
     so the arithmetic can never silently drift from the rule it encodes.
  2. Only TIMED codes contribute minutes. The service-based modalities (hot/cold packs, e-stim,
     traction, whirlpool, ...) bill one unit per session regardless of duration, so letting their
     minutes into the total inflates the unit count — an overbill, not a rounding error.

Also locks the CMS-vs-AMA divergence: these are two real, incompatible payer rules, and Cadence
must never collapse them into a single confident number.

    .venv/Scripts/python.exe -m unittest tests.test_billing_units -v
"""

import unittest

from app.generate import billing, cpt
from app.generate.billing import (
    AMA_RULE_OF_EIGHTS,
    CMS_SUBSTITUTION,
    UNIT_TABLE,
    allocate_units,
    units_for_minutes,
)

# Service-based (untimed) codes that appear in cpt._CPT_RULES, plus the evaluation codes. None of
# these may ever be treated as timed.
UNTIMED_IN_TABLE = ("97010", "97012", "97014", "97016", "97018", "97022", "97024", "97150")
EVAL_CODES = ("97161", "97162", "97163")


def _table_lookup(minutes: int) -> int:
    """The published table, read literally — the oracle the closed form is checked against.

    Past the printed table the bands are CONTINUED by stepping 15 minutes at a time rather than
    computed, so this oracle shares no arithmetic with `units_for_minutes` and the comparison
    stays a real check instead of restating the same formula twice.
    """
    for low, high, units in UNIT_TABLE:
        if low <= minutes <= high:
            return units
    low, high, units = UNIT_TABLE[-1]
    while minutes > high:
        low, high, units = low + 15, high + 15, units + 1
    return units


class UnitsForMinutesTests(unittest.TestCase):
    def test_every_documented_boundary(self):
        """The exact minute where the unit count ticks over. These are the numbers a biller
        argues about, so each is asserted by hand rather than only by the sweep below."""
        for minutes, expected in [
            (0, 0), (7, 0), (8, 1), (22, 1), (23, 2), (37, 2), (38, 3),
            (52, 3), (53, 4), (67, 4), (68, 5), (82, 5), (83, 6),
        ]:
            with self.subTest(minutes=minutes):
                self.assertEqual(units_for_minutes(minutes), expected)

    def test_closed_form_matches_the_literal_table(self):
        for minutes in range(0, 201):
            with self.subTest(minutes=minutes):
                self.assertEqual(units_for_minutes(minutes), _table_lookup(minutes))

    def test_every_band_is_fifteen_minutes_wide(self):
        for low, high, _ in UNIT_TABLE[1:]:
            self.assertEqual(high - low, 14, f"band {low}-{high} is not 15 minutes wide")

    def test_a_typical_four_unit_session(self):
        """The target session for this work: ~53-67 timed minutes is 4 units."""
        for minutes in range(53, 68):
            self.assertEqual(units_for_minutes(minutes), 4)

    def test_zero_and_none_are_zero_units(self):
        self.assertEqual(units_for_minutes(0), 0)
        self.assertEqual(units_for_minutes(None), 0)


class TimedCodeTests(unittest.TestCase):
    def test_service_based_modalities_are_not_timed(self):
        """Untimed codes bill once per session. If any of these leaked into TIMED_CODES their
        minutes would inflate the unit total on every note that used a modality."""
        for code in UNTIMED_IN_TABLE + EVAL_CODES:
            with self.subTest(code=code):
                self.assertFalse(cpt.is_timed(code))
                self.assertNotIn(code, cpt.TIMED_CODES)

    def test_the_core_treatment_codes_are_timed(self):
        for code in ("97110", "97112", "97116", "97140", "97530", "97535", "97035"):
            with self.subTest(code=code):
                self.assertTrue(cpt.is_timed(code))

    def test_timed_codes_is_a_subset_of_what_the_table_can_suggest_plus_modalities(self):
        """Every timed code must be a real PT code shape — catches a typo'd entry."""
        for code in cpt.TIMED_CODES:
            self.assertRegex(code, r"^97\d{3}$")

    def test_untimed_minutes_never_enter_the_total(self):
        """A stated duration for a service-based modality is not billable time.

        Asserted end-to-end through `extract`, not through `allocate_units`: allocation is only
        ever HANDED timed codes, so testing it there would prove nothing about the exclusion. Ten
        minutes of hot packs alongside twenty of ther ex must stay 1 unit — counting the modality
        would push the total to 30 minutes and 2 units, which is the overbill.
        """
        draft = billing.extract(
            "Shoulder follow-up. We did therapeutic exercise for twenty minutes. "
            "Hot packs for ten minutes at the end."
        )
        codes = {h.code for h in draft.billable}
        self.assertIn("97010", codes, "the modality should still be detected and billable")
        self.assertEqual(draft.total_timed_minutes, 20)
        self.assertEqual(draft.units.total_units, 1)
        self.assertIn("97010", draft.untimed_codes)


class AllocationTests(unittest.TestCase):
    def test_cms_and_ama_disagree_on_two_eight_minute_services(self):
        """The canonical divergence. Emitting only one of these numbers would be taking the
        biller's side of a payer-specific question rule 12 leaves to them."""
        minutes = {"97110": 8, "97140": 8}
        cms = allocate_units(minutes, method=CMS_SUBSTITUTION)
        ama = allocate_units(minutes, method=AMA_RULE_OF_EIGHTS)
        self.assertEqual(cms.total_units, 1)
        self.assertEqual(ama.total_units, 2)

    def test_cms_gives_the_leftover_unit_to_the_largest_remainder(self):
        alloc = allocate_units({"97110": 23, "97140": 7}, method=CMS_SUBSTITUTION)
        self.assertEqual(alloc.total_timed_minutes, 30)
        self.assertEqual(alloc.total_units, 2)
        self.assertEqual(dict(alloc.per_code), {"97110": 2, "97140": 0})
        self.assertFalse(alloc.ambiguous)

    def test_a_remainder_tie_is_flagged_but_output_stays_deterministic(self):
        minutes = {"97140": 8, "97110": 8}
        first = allocate_units(minutes, method=CMS_SUBSTITUTION)
        second = allocate_units(dict(reversed(list(minutes.items()))), method=CMS_SUBSTITUTION)
        self.assertTrue(first.ambiguous)
        self.assertEqual(first.per_code, second.per_code)
        self.assertIn("tie", first.note.lower())

    def test_allocated_units_never_exceed_the_total(self):
        for minutes in ({"97110": 53}, {"97110": 30, "97140": 23}, {"97110": 8, "97112": 9, "97140": 40}):
            with self.subTest(minutes=minutes):
                alloc = allocate_units(minutes, method=CMS_SUBSTITUTION)
                self.assertEqual(sum(u for _, u in alloc.per_code), alloc.total_units)

    def test_four_unit_session_splits_across_three_treatments(self):
        alloc = allocate_units({"97110": 25, "97140": 20, "97116": 15}, method=CMS_SUBSTITUTION)
        self.assertEqual(alloc.total_timed_minutes, 60)
        self.assertEqual(alloc.total_units, 4)

    def test_empty_minutes_yields_zero_units(self):
        alloc = allocate_units({}, method=CMS_SUBSTITUTION)
        self.assertEqual(alloc.total_units, 0)
        self.assertEqual(alloc.per_code, ())

    def test_method_is_reported_on_every_allocation(self):
        self.assertEqual(allocate_units({"97110": 20}, method=CMS_SUBSTITUTION).method,
                         CMS_SUBSTITUTION)
        self.assertEqual(allocate_units({"97110": 20}, method=AMA_RULE_OF_EIGHTS).method,
                         AMA_RULE_OF_EIGHTS)


if __name__ == "__main__":
    unittest.main()
