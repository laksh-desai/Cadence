---
id: discharge
name: Discharge Summary
mode: require
carry: true
steps:
  - label: "Discharge date, start of care, and number of visits"
    example: "Discharged April 30; start of care March 3; 16 visits attended of 16 planned."
  - label: "Reason for discharge"
    example: "Goals met. (Or: plateaued, patient choice, hospitalized, moved, stopped attending.)"
  - label: "Diagnoses"
    example: "Gait abnormality and muscle weakness after a left total knee replacement."
  - label: "Precautions at discharge"
    optional: true
    example: "Fall risk; continue using the cane outdoors."
  - label: "Treatment provided during the episode"
    example: "Gait training, balance and neuromuscular re-education, strengthening, stair training, and home exercise instruction, 2x per week."
  - label: "Status at the start of care"
    example: "Walked 75 ft with a rolling walker at min assist; Berg 36 out of 56; unable to do stairs."
  - label: "Tests and measures at discharge, compared with the start"
    example: "Berg 50 out of 56, up from 36; Timed Up and Go 11 seconds with a cane, down from 24."
  - label: "Functional status at discharge"
    example: "Walks 500 ft with a cane, independent; transfers independent; 12 steps with one rail, modified independent."
  - label: "Final status of each short-term goal"
    example: "Walk 150 ft with walker at supervision: MET. Independent transfers: MET."
  - label: "Final status of each long-term goal"
    example: "Independent household walking with a cane: MET. Community walking 1000 ft: NOT MET, reached 500 ft — patient chose to stop."
  - label: "Home exercise program and education given"
    example: "Issued a written home program of balance and strengthening exercises; daughter trained in guarding on stairs; patient demonstrated it correctly."
  - label: "Equipment and recommendations"
    example: "Using a single-point cane; recommend continuing the walking program and a community exercise class; return to PT if falls recur."
  - label: "Discharge assessment and prognosis"
    example: "Significant gains in balance and gait; low fall risk now; good prognosis to maintain gains with the home program."
---
DISCHARGE SUMMARY — end of the episode of care. Require-mode; carry-forward ON.
Write each item below as its OWN "## " section (never fold several under one heading), in this order. Compare the start of care with discharge wherever both are stated. Completeness means every STATED fact appears — never assert an unstated normal finding.

Discharge Information — discharge date, start-of-care date, number of visits attended, and referring provider, as stated.
Reason for Discharge — goals met, plateau, patient choice, hospitalization, or other reason, exactly as stated.
Diagnoses — medical and PT diagnoses stated; include an ICD-10 code ONLY if the therapist explicitly assigned one.
Precautions [carry forward] — precautions still relevant at discharge; omit if none were stated.
Summary of Skilled Services — the interventions provided during the episode and their frequency.
Initial Status — function and test results at the start of care, as stated.
Objective Measures — standardized tests at discharge with score and device, beside the start-of-care value.
Functional Status [carry forward] — bed mobility, transfers, gait with distance / device / assist level, and stairs at discharge, compared with the start of care.
Short-Term Goals [carry forward] — every goal, one line each, marked MET, NOT MET or DISCONTINUED with the final value; a goal not met gets the stated reason.
Long-Term Goals [carry forward] — every goal, one line each, marked MET, NOT MET or DISCONTINUED with the final value; a goal not met gets the stated reason.
Home Exercise Program & Education — the home program issued, patient and caregiver training, and their demonstrated understanding.
Equipment & Recommendations — equipment in use, follow-up, referrals, restorative or maintenance program, and when to return to therapy.
Discharge Assessment — overall progress, remaining deficits and safety, and the prognosis to maintain gains.
