# Office Ally custom SOAP layout — "Cadence Re-evaluation"

**For:** the Office Ally team building SD Mobile PT's custom note layouts.
**Used for:** the PT reassessment due at least every 10 treatment visits. Cadence note type:
*Re-evaluation / Progress Report*.

- A **routine 10th-visit Progress Report** is required by Medicare but is **not billable**. Only the
  treatment codes done that day are billed.
- A **Re-evaluation (CPT 97164)** is billable only when the note documents a **significant change**:
  new clinical findings, an unexpected change in condition, or failure to respond to the plan.
  Cadence flags this choice for the therapist. It never picks it.

Same mechanics as the other layouts: free-text boxes, 2,000 characters each, filled **by exact
label**, draft saved with Apply, signed by the therapist. Please keep the standard **Objective
Notes**, **Functional Status**, **Assessment** and **Plan Notes** boxes for overflow.

## Boxes

| # | SOAP part | Box label (exact) | What goes in it |
|---|---|---|---|
| 1 | Subjective | **Reporting Period** | Visit number, dates covered, visits attended |
| 2 | Subjective | **Reason for Reassessment** | Routine progress report, or the significant change |
| 3 | Subjective | **Interval History** | Patient report since last eval: pain, falls, hospital stays, medication changes |
| 4 | Subjective | **Diagnoses** | Diagnoses (ICD-10 only if the therapist assigned it) |
| 5 | Subjective | **Precautions** | Fall risk, weight bearing, other precautions |
| 6 | Objective | **Fall Risk** | Falls this period, steadiness |
| 7 | Objective | **Objective Measures** | Standardized tests today vs. the start (Berg, TUG, 5xSTS, 30-second chair stand, gait speed) |
| 8 | Objective | **Musculoskeletal Assessment** | ROM and strength vs. earlier values |
| 9 | Objective | **Cardiopulmonary** | BP, HR, O2 |
| 10 | Objective | **Functional Mobility** | Transfers, gait (distance / device / assist), stairs vs. previous |
| 11 | Assessment | **Goal Status** | Every previous goal: MET / PROGRESSING / NOT MET with current value |
| 12 | Assessment | **Assessment Summary** | Progress, remaining problems, why skilled PT continues, rehab potential |
| 13 | Plan | **Short-Term Goals** | Updated goals |
| 14 | Plan | **Long-Term Goals** | Updated goals |
| 15 | Plan | **Plan of Treatment** | Frequency, duration, new certification period, focus, discharge plan |
| 16 | Plan | **Billing - CPT & Minutes** | Written by Cadence's code: treatment codes with minutes, total treatment time, the 97164-or-Progress-Report decision to confirm |
