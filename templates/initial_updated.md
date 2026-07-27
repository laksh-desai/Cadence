---
id: initial_updated
name: Initial Evaluation — Updated Version (experimental)
mode: require
carry: false
steps:
  - label: "Chief complaint and how it affects function"
    example: "Patient here for right shoulder pain that started three weeks ago; can't lift her arm overhead to reach cabinets or fasten a seatbelt."
  - label: "History of present illness — onset, cause, and course"
    example: "Onset three weeks ago after lifting a heavy box; no single clear injury; getting gradually worse, not better, since it began."
  - label: "Prior treatment, imaging, and referring diagnosis"
    example: "Saw primary care, X-ray was negative; referred for PT with a diagnosis of rotator cuff strain; no prior treatment for this problem."
  - label: "Prior history — medical, surgical, cognition, falls, medications"
    example: "History of high blood pressure and a prior appendectomy; cognitively intact; no falls in the past year; takes lisinopril 10 milligrams daily."
  - label: "Prior level of function and living situation"
    example: "Before this she worked full time as a nurse and exercised daily; lives in a two-story home with stairs, spouse at home to help."
  - label: "Patient goals and pain — worst, best, current, and description"
    example: "Wants to return to lifting at work and sleeping through the night; pain worst 8 out of 10, best 2, currently 5, sharp with overhead reaching."
  - label: "Outcome measure, observation, posture, and handedness"
    example: "DASH score 45 at baseline; right-hand dominant; guarded posture with rounded shoulders and forward head."
  - label: "Range of motion, neuromuscular, and strength by region"
    example: "Right shoulder active flexion 90 degrees versus 160 on the left; rotator cuff strength 3+ out of 5; sensation intact throughout."
  - label: "Functional mobility, gait, and special tests"
    example: "Independent with gait and transfers, no device; positive Hawkins-Kennedy and a painful arc on the right."
  - label: "Diagnosis, presentation, and justification for skilled care"
    example: "Impression of right rotator cuff tendinopathy; presentation is evolving; skilled therapy needed to restore range, strength, and safe overhead function."
  - label: "Education, rehab potential, precautions, and goals"
    example: "Educated on activity modification and a home program; rehab potential good; no overhead lifting over ten pounds; short-term goal full range in four weeks, long-term return to full-duty nursing in eight weeks."
  - label: "Plan — frequency, duration, certification dates, and codes"
    example: "PT twice a week for eight weeks; certification period starts today with recert due in ninety days; assigning the treatment and diagnosis codes yourself."
---
INITIAL EVALUATION — first full-intake visit, baseline capture. Require-mode; carry-forward OFF.
Produce the note as EXACTLY FOUR sections, each starting with a "## " heading, in this order:
## Subjective, ## Objective, ## Assessment, ## Plan. Under each heading write its fields ONE per line
as "Field: value". Keep every field on its own line — NEVER merge several fields onto one line — and
never add a title, "INITIAL EVALUATION", or summary section before or after these four.
Output EVERY field listed below for each block, in order, even when the dictation gave no information
for it — for such a field write exactly "not documented" as the value. Never drop a field, and never
invent a value: use "not documented" for anything the therapist didn't state.

## Subjective
Chief Complaint: [presenting problem in the patient's words, effect on function]
History of Present Illness: [brief course of the current problem]
Date of Onset: [when it started]
Mechanism / Cause: [how it started, or "insidious"]
Course Since Onset: [ better / worse / unchanged ]
Prior Treatment for This Problem: [what was tried before]
Imaging / Referral / Referring Diagnosis: [imaging result, referral source, referring diagnosis]
Medical History: [list every condition stated]
Surgical History: [prior surgeries]
Complicating / Personal Factors: [comorbidities / personal factors; omit the line if none stated]
Cognition: [alert / oriented status]
History of Falls: [falls in the past year]
Current Medications: [list EVERY medication and dose stated — do not drop any]
Allergies: [drug allergies, or "no known drug allergies" if stated]
Prior Level of Function: [work, activities, mobility before this episode]
Living Situation: [home setup, stairs, support at home, equipment]
Patient Goals: [what the patient wants to get back to]
Pain: [Worst _/10, Best _/10, Current _/10, then location / quality / aggravating-easing — use ONLY numbers actually stated; if no rating was given, write "not rated"]

## Objective
Outcome Measurement Tools: [standardized measure + baseline score, if stated]
Observation: [general observation only — do NOT put ROM / strength / gait here]
Handedness: [right / left]
Posture: [postural findings]
Range of Motion: [region / movement — AROM or PROM — degrees — L vs R]
Neuromuscular: [MMT / strength grades, tone, sensation, reflexes]
Functional Mobility / Gait: [bed mobility, transfers, gait, assistive device, distance]
Special Tests: [test name — positive / negative]

## Assessment
Diagnosis: [PT clinical impression]
Clinical Presentation: [ Stable / Evolving ]
Justification for Skilled Care: [why skilled therapy is medically necessary]
Patient Education: [what was covered this visit]
Rehab Potential: [ Good / Fair / Poor ]
Contraindications / Precautions to Therapy: [precautions]
Short-Term Goals: [measurable — target timeframe]
Long-Term Goals: [measurable — tied to prior level of function]

## Plan
Frequency: [visits per week]
Duration: [total weeks]
Medicare Certification Dates: [certification period start; recert due at least every 90 days]
Treatment Procedures (CPT): [only a code the therapist explicitly assigned — otherwise leave for the clinician]
Medical Diagnosis (ICD-10): [only a code the therapist explicitly assigned — otherwise leave for the clinician]
Treatment Diagnosis: [the PT treatment diagnosis in words]
