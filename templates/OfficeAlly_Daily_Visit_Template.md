# Office Ally custom SOAP layout — "Cadence Daily Visit"

**For:** the Office Ally team building SD Mobile PT's custom note layouts.
**Used for:** every routine treatment visit (Medicare daily note). Cadence note type: *Daily Visit*.

## How Cadence fills it (please read first)

- Cadence's Chrome extension fills the open Add Note page **box by box, using each box's label**.
  When a box's label is **exactly** the name in the "Box label" column below, that Cadence section
  goes into that box and nothing else does. Please use the labels **exactly as written**
  (capitals, spaces and punctuation may vary, but the words must match).
- Every box should be a **multi-line free-text box** (the same kind as the standard "Objective
  Notes" box). Cadence respects Office Ally's 2,000-character limit per box. If a section is
  longer, it continues into the next box of the same S/O/A/P part, marked "(cont.)".
- Cadence **never signs or submits**. It saves a draft with **Apply**, reads every box back, and
  the therapist reviews and signs.
- Please keep the standard boxes **Objective Notes**, **Functional Status**, **Assessment**,
  **Procedure Notes** and **Plan Notes** too. Cadence uses them as overflow.
- Boxes appear in the order below. Leave out Review of Systems and Physical Exam grids; Cadence
  doesn't fill them.

## Boxes

| # | SOAP part | Box label (exact) | What goes in it | Typical length |
|---|---|---|---|---|
| 1 | Subjective | **Subjective** | Patient's report today: pain, changes, falls since last visit, home-program adherence | 1–3 sentences |
| 2 | Subjective | **Precautions** | Fall risk, weight-bearing status, other precautions | 1 line |
| 3 | Objective | **Vitals** | BP, HR, O2 (only when taken) | 1 line |
| 4 | Objective | **Pain - At Rest** | Rating /10 and location | 1 line |
| 5 | Objective | **Pain - With Movement** | Rating /10 and provoking activity | 1 line |
| 6 | Objective | **Gait Training** | Minutes, distance, device, assist level, cues, response (CPT 97116) | 2–4 sentences |
| 7 | Objective | **Neuromuscular Re-education** | Minutes, balance and coordination activities, cues, response (97112) | 2–4 sentences |
| 8 | Objective | **Therapeutic Exercise** | Minutes, exercises with sets and reps, cues, response (97110) | 2–4 sentences |
| 9 | Objective | **Therapeutic Activities** | Minutes, functional task practice, e.g. transfers (97530) | 2–4 sentences |
| 10 | Objective | **Manual Therapy** | Minutes, technique and region (97140) | 1–3 sentences |
| 11 | Objective | **Self-Care / Home Management Training** | Minutes, ADL and home-safety training (97535) | 1–3 sentences |
| 12 | Objective | **Objective Measures** | Standardized tests today: TUG, Berg, 5x sit-to-stand, 30-second chair stand, gait speed, with scores | 1–3 lines |
| 13 | Objective | **Functional Status** | Ambulation distance, device, assist level, transfers, stairs | 1–3 sentences |
| 14 | Assessment | **Assessment** | Response to treatment, progress toward goals, why skilled PT is still needed | 2–4 sentences |
| 15 | Plan | **Short-Term Goals** | Each goal and its status (MET / progressing) | 1 line per goal |
| 16 | Plan | **Long-Term Goals** | Each goal and its status | 1 line per goal |
| 17 | Plan | **Plan** | Next-visit focus, frequency, progression, home program and education | 1–3 sentences |
| 18 | Plan | **Billing - CPT & Minutes** | Written by Cadence's code, not the AI. One line per CPT code with its minutes, total timed minutes, total treatment time, units (8-minute rule), ICD-10 to confirm | 4–8 lines |

Boxes 6–11 are filled only when that treatment was done; an empty treatment box simply stays empty.

## A question for Office Ally

The **Billing - CPT & Minutes** box documents the codes and minutes in the note, which is what
Medicare reviews. Can the layout also feed these into Office Ally's **charge / superbill** screen?
If there is a field or import for that, tell us its format and Cadence can fill it too. Until then,
the biller enters charges from this box.

## Example of what Cadence puts in the boxes (fake patient)

- **Gait Training:** "Minutes: 15. Ambulated 2 x 100 ft with a rolling walker, contact guard; verbal
  cues for step length and upright posture; one standing rest. CPT 97116 Gait Training"
- **Billing - CPT & Minutes:**
  ```
  CPT 97116 Gait Training 15 min
  CPT 97112 Neuromuscular Re-education 12 min
  CPT 97110 Therapeutic Exercise 15 min
  Total timed minutes: 42
  Total treatment time: 45 min
  Units (8-minute rule): 3 (97116 x1, 97112 x1, 97110 x1)
  ```
