"""Phrase banks the synthetic generator renders dictation from. Data only, no logic.

Adding a body part means adding entries here plus one `ICD_BY_BODY_PART` entry in
`app/generate/coding_tables.py`. Nothing in `generate.py` changes.

**On circularity** (the caveat that matters most about this whole eval loop): the generator and
the extractor share an author, so a phrase bank that only ever speaks the extractor's own cue
vocabulary would measure nothing — it would score 100% by construction and teach us that the
extractor recognizes the words we told it to recognize.

`INTERVENTION_SPOKEN` therefore deliberately includes PARAPHRASES the cue table does not know
("hands-on work", "functional activities", "strength work"). A sample that uses one is still
labeled with the correct gold code, because the therapist really did perform that service — so
the extractor genuinely misses it and recall genuinely drops. That gap is the signal. Resist the
urge to "fix" a low recall number by copying these paraphrases into
`coding_tables.INTERVENTION_CUES` without thinking about whether the phrase is actually
unambiguous enough to bill on.
"""

from __future__ import annotations

# Fictional. No real patient names, ever — see evals/data/README.md.
PATIENT_NAMES: tuple[str, ...] = (
    "Rosalind Achterberg", "Marcus Delgado", "Priya Ramaswamy", "Devon Okafor",
    "Helena Kirchner", "Terrence Boyle", "Yuki Tanaka-Reyes", "Ingrid Solheim",
    "Camille Beaufort", "Nathaniel Osei", "Beatriz Villanueva", "Aleksander Nowak",
    "Fiona Macgregor", "Hassan Al-Rashid", "Margarethe Lindqvist", "Cormac Fitzgerald",
    "Imani Washington", "Rafael Santoro", "Lucia Marchetti", "Bjorn Haugen",
)

# Spoken forms per CPT code. The FIRST entry is the canonical service name; later entries get
# progressively looser, and the ones marked below are outside the cue table on purpose.
INTERVENTION_SPOKEN: dict[str, tuple[str, ...]] = {
    "97110": ("therapeutic exercise", "ther ex", "therapeutic exercises",
              "strength work"),               # paraphrase — not in the cue table
    "97140": ("manual therapy", "joint mobilization", "soft tissue mobilization",
              "hands-on work"),               # paraphrase — not in the cue table
    "97112": ("neuromuscular re-education", "neuro re-ed", "neuromuscular reeducation"),
    "97530": ("therapeutic activities", "ther act",
              "functional activities"),        # paraphrase — not in the cue table
    "97535": ("self-care training", "home management training"),
    "97035": ("ultrasound",),
    "97014": ("electrical stimulation", "e-stim"),
    "97010": ("hot pack", "cold pack", "moist heat"),
    "97124": ("massage",),
    "97116": ("gait training",),
}

INTERVENTION_LABEL: dict[str, str] = {
    "97110": "Therapeutic Exercise", "97112": "Neuromuscular Re-education",
    "97116": "Gait Training", "97140": "Manual Therapy", "97530": "Therapeutic Activities",
    "97535": "Self-Care/Home Management Training", "97035": "Ultrasound",
    "97014": "Electrical Stimulation", "97010": "Hot/Cold Packs", "97124": "Massage Therapy",
}

# Which treatments plausibly appear for a body part, split by how they bill. `timed` codes are
# the ones the 8-minute rule applies to; `untimed` are service-based modalities that must show up
# in a realistic note WITHOUT contributing to the timed total — the exact trap the eval checks.
TREATMENTS_BY_BODY_PART: dict[str, dict[str, tuple[str, ...]]] = {
    "shoulder": {
        "timed": ("97110", "97140", "97112", "97530", "97535"),
        "untimed": ("97010", "97014"),
        # Never performed for a shoulder — a clean distractor the extractor should only ever
        # report when the dictation explicitly (and wrongly) says it happened.
        "implausible": ("97116",),
    },
}

# Clinical detail appended to a treatment so the dictation reads like a real session rather than
# a list of code names.
TECHNIQUE_DETAIL: dict[str, tuple[str, ...]] = {
    "97110": ("scapular retraction and external rotation with theraband",
              "isometrics and active-assisted flexion in supine",
              "wall slides and serratus punches",
              "rotator cuff strengthening at ninety degrees abduction"),
    "97140": ("graded glenohumeral mobilizations, grade three anterior and inferior",
              "posterior capsule stretching and scapular mobilization",
              "soft tissue work to the upper trapezius and infraspinatus"),
    "97112": ("rhythmic stabilization and scapular control in quadruped",
              "proprioceptive drills on the bodyblade",
              "closed-chain shoulder stability work"),
    "97530": ("simulated overhead reaching to a cabinet shelf",
              "lifting and carrying tasks with a five pound weight",
              "reach-and-place activities at counter height"),
    "97535": ("reviewed dressing strategies and sleep positioning",
              "training on shower and grooming with the affected arm"),
    "97035": ("to the anterior shoulder at one point five watts per centimeter squared",
              "to the supraspinatus tendon"),
    "97014": ("to the posterior shoulder for pain modulation",
              "premodulated for pain control"),
    "97010": ("to the anterior shoulder afterward", "before treatment to warm the tissue"),
    "97124": ("to the upper trapezius",),
    "97116": ("in the hallway with contact guard",),
}

# How a therapist frames the diagnosis out loud. These carry the ICD context the extractor
# requires, and are also just how people actually talk.
DIAGNOSIS_FRAMES: tuple[str, ...] = (
    "Referring diagnosis is {dx}",
    "She was referred with a diagnosis of {dx}",
    "He was referred with a diagnosis of {dx}",
    "Medical diagnosis is {dx}",
    "Working diagnosis is {dx}",
    "Assessment is {dx}",
    "Treating diagnosis is {dx}",
)

# Minutes phrasings, keyed by the extraction basis each one exercises.
MINUTES_FRAMES: dict[str, tuple[str, ...]] = {
    "explicit": (
        "{spoken} minutes of {cue}",
        "{cue} for {spoken} minutes",
        "{cue}, {spoken} minutes",
        "we did {cue} for {spoken} minutes",
        "{spoken} minutes of {cue}, {detail}",
    ),
    "bare": (
        "{cue} {spoken}",
        "{cue}, {spoken}",
    ),
    "fraction": (
        "{cue} for {fraction} of the session",
    ),
}

SESSION_TOTAL_FRAMES: tuple[str, ...] = (
    "This was a {spoken} minute session.",
    "Total treatment time was {spoken} minutes.",
    "The session was {spoken} minutes.",
)

# Distractor frames. Each renders an intervention the extractor must NOT bill, and the sample
# records the reason as a gold label so a leak is attributable.
DISTRACTOR_FRAMES: dict[str, tuple[str, ...]] = {
    "negated": (
        "We did not do {cue} today.",
        "We did not do {cue} this visit.",
        "No {cue} today, {subj} was too sore.",
    ),
    "prior_visit": (
        "Last visit we did {cue}.",
        "Previously we were doing {cue}.",
        "At the last session we did {cue}.",
    ),
    "planned": (
        "Next visit we will add {cue}.",
        "Next time we plan to start {cue}.",
        "We will begin {cue} at the next session.",
    ),
    "home_program": (
        "{Poss} home program includes {cue}.",
        "{Poss} home exercise program has {cue}.",
        "For home {subj} is doing {cue}.",
    ),
    "self_corrected": (
        "We did {cue}, sorry, {corrected} instead.",
        "Then {cue}, I mean {corrected}.",
    ),
}

# MedASR-style disfluency. Two deliberate exclusions:
#   * "mm" (millimetres) and "er" (external rotation) collide with real clinical usage, which is
#     exactly why CLAUDE.md rule 8 keeps them out of the deterministic filler strip. Emitting them
#     here would be testing a rule that says "don't".
#   * "I mean" is a CORRECTION marker (coding_tables.CORRECTION_CUES), not a neutral filler.
#     Sprinkling it at random would manufacture self-corrections the gold labels don't know about,
#     turning a generator artifact into a phantom extractor failure. It appears only inside the
#     deliberate self_corrected frames above.
FILLERS: tuple[str, ...] = ("um", "uh", "like", "you know", "so")

OPENERS: tuple[str, ...] = (
    "Okay, {visit} for {name}, {side} {part}.",
    "Alright, this is {name}, {visit}, {side} {part}.",
    "{visit} for {name}, {side} {part}.",
)

CLOSERS: tuple[str, ...] = (
    "{Subj} tolerated the session well with no increase in symptoms.",
    "{Subj} tolerated treatment well, no adverse response.",
    "Patient tolerated everything without increased pain.",
    "Good response to treatment overall.",
    "Tolerated well, continue current plan of care.",
)

SUBJECTIVE: tuple[str, ...] = (
    "{Subj} reports the shoulder is feeling looser this week.",
    "{Subj} says reaching overhead is easier than last visit.",
    "Reports pain is better since the last session.",
    "{Subj} still has trouble sleeping on that side.",
    "Says the exercises are getting easier at home.",
)

# One pronoun set per sample. A dictation that flips between "she" and "he" mid-note is a
# generator artifact no therapist produces, and it would give the downstream note model a
# contradiction to resolve that has nothing to do with what we're measuring.
VOICES: tuple[dict[str, str], ...] = (
    {"subj": "she", "Subj": "She", "obj": "her", "poss": "her", "Poss": "Her"},
    {"subj": "he", "Subj": "He", "obj": "him", "poss": "his", "Poss": "His"},
)

VISIT_TYPES: dict[str, tuple[str, ...]] = {
    "initial": ("Initial Evaluation", "Initial evaluation, new patient",
                "Initial Evaluation, post-op week 4"),
    "followup": ("Follow-up, week 3", "Follow-up visit", "Follow-up, week 6",
                 "Follow-up, post-op week 8"),
}

FRACTIONS: tuple[tuple[str, float], ...] = (
    ("a third", 1 / 3), ("a half", 1 / 2), ("a quarter", 1 / 4), ("two thirds", 2 / 3),
)
