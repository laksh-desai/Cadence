# Office Ally custom SOAP layout — "Cadence Discharge Summary"

**For:** the Office Ally team building SD Mobile PT's custom note layouts.
**Used for:** the end of every episode of care. Cadence note type: *Discharge Summary*.
The structure follows the common Net Health–style discharge summary the practice is used to:
reason, dates and visits, start vs. discharge status, final goal status, home program,
recommendations, prognosis.

Medicare treats the discharge note as a progress report covering the period up to discharge, so it
needs the goal status and objective comparisons below. A discharge visit bills only the treatment
codes performed that day; there is no separate discharge evaluation code.

Same mechanics as the other layouts: free-text boxes, 2,000 characters each, filled **by exact
label**, draft saved with Apply, signed by the therapist. Please keep the standard **Objective
Notes**, **Functional Status**, **Assessment** and **Plan Notes** boxes for overflow.

## Boxes

| # | SOAP part | Box label (exact) | What goes in it |
|---|---|---|---|
| 1 | Subjective | **Discharge Information** | Discharge date, start of care, visits attended, referring provider |
| 2 | Subjective | **Reason for Discharge** | Goals met / plateau / patient choice / hospitalization / other |
| 3 | Subjective | **Diagnoses** | Diagnoses (ICD-10 only if the therapist assigned it) |
| 4 | Subjective | **Precautions** | Precautions still relevant at discharge |
| 5 | Objective | **Summary of Skilled Services** | Interventions given during the episode and frequency |
| 6 | Objective | **Initial Status** | Function and test results at the start of care |
| 7 | Objective | **Objective Measures** | Tests at discharge beside the start-of-care values |
| 8 | Objective | **Functional Status** | Mobility, transfers, gait, stairs at discharge vs. start |
| 9 | Plan | **Short-Term Goals** | Every goal: MET / NOT MET / DISCONTINUED with final value and reason |
| 10 | Plan | **Long-Term Goals** | Same, for long-term goals |
| 11 | Plan | **Home Exercise Program & Education** | Program issued, patient and caregiver training, understanding |
| 12 | Plan | **Equipment & Recommendations** | Equipment, follow-up, referrals, maintenance program, when to return |
| 13 | Assessment | **Discharge Assessment** | Overall progress, remaining deficits and safety, prognosis |
| 14 | Plan | **Billing - CPT & Minutes** | Written by Cadence's code: treatment codes done today with minutes, total treatment time |
