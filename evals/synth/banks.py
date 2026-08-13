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
# How a therapist SAYS a body part, as opposed to the key the code tables use. "the lumbar is
# feeling looser" is not something anyone says; "the low back" is.
SPOKEN_PART: dict[str, str] = {
    "shoulder": "shoulder", "knee": "knee", "lumbar": "low back",
    "cervical": "neck", "hip": "hip", "ankle": "ankle",
}

# Regions where laterality is not normally spoken, because the structure is midline. Saying
# "right low back" in an opener would be unnatural and would also teach the extractor a laterality
# habit that real spine dictation does not have.
MIDLINE_PARTS: frozenset[str] = frozenset({"lumbar", "cervical"})

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
    "97012": ("mechanical traction", "traction"),
    "97542": ("wheelchair management",),
}

INTERVENTION_LABEL: dict[str, str] = {
    "97110": "Therapeutic Exercise", "97112": "Neuromuscular Re-education",
    "97116": "Gait Training", "97140": "Manual Therapy", "97530": "Therapeutic Activities",
    "97535": "Self-Care/Home Management Training", "97035": "Ultrasound",
    "97014": "Electrical Stimulation", "97010": "Hot/Cold Packs", "97124": "Massage Therapy",
    "97012": "Mechanical Traction", "97542": "Wheelchair Management",
}

# Which treatments plausibly appear for a body part, split by how they bill. `timed` codes are
# the ones the 8-minute rule applies to; `untimed` are service-based modalities that must show up
# in a realistic note WITHOUT contributing to the timed total — the exact trap the eval checks.
TREATMENTS_BY_BODY_PART: dict[str, dict[str, tuple[str, ...]]] = {
    # `implausible` codes are ones a therapist would not perform for that region. They make clean
    # distractors: the extractor should only ever report them when the dictation explicitly (and
    # wrongly) says they happened. Gait training is implausible for a shoulder or a neck; it is
    # entirely plausible for a knee, hip, or ankle, which is why the split is per body part.
    "shoulder": {
        "timed": ("97110", "97140", "97112", "97530", "97535"),
        "untimed": ("97010", "97014"),
        "implausible": ("97116",),
    },
    "knee": {
        "timed": ("97110", "97140", "97112", "97116", "97530"),
        "untimed": ("97010", "97014"),
        "implausible": ("97535",),
    },
    "lumbar": {
        "timed": ("97110", "97140", "97112", "97530"),
        "untimed": ("97010", "97012", "97014"),   # mechanical traction is a lumbar staple
        "implausible": ("97116",),
    },
    "cervical": {
        "timed": ("97110", "97140", "97112", "97530"),
        "untimed": ("97010", "97012", "97014"),
        "implausible": ("97116",),
    },
    "hip": {
        "timed": ("97110", "97140", "97112", "97116", "97530"),
        "untimed": ("97010", "97014"),
        "implausible": ("97535",),
    },
    "ankle": {
        "timed": ("97110", "97140", "97112", "97116", "97530"),
        "untimed": ("97010", "97014"),
        "implausible": ("97542",),
    },
}

# Clinical detail appended to a treatment so the dictation reads like a real session rather than
# a list of code names. Keyed by body part, then by code — a "scapular retraction" detail on a
# knee note would read as nonsense to the clinician reviewing the corpus, and the corpus is only
# useful while it looks like something a therapist would actually say.
_GENERIC_DETAIL: dict[str, tuple[str, ...]] = {
    "97010": ("afterward for symptom control", "before treatment to warm the tissue"),
    "97012": ("in supine at twenty-five percent body weight",),
    "97014": ("for pain modulation", "premodulated for pain control"),
    "97035": ("at one point five watts per centimeter squared",),
    "97124": ("to the surrounding musculature",),
    "97542": ("for propulsion mechanics",),
}

TECHNIQUE_DETAIL_BY_PART: dict[str, dict[str, tuple[str, ...]]] = {
    "shoulder": {
        "97110": ("scapular retraction and external rotation with theraband",
                  "isometrics and active-assisted flexion in supine",
                  "wall slides and serratus punches"),
        "97140": ("graded glenohumeral mobilizations, grade three anterior and inferior",
                  "posterior capsule stretching and scapular mobilization",
                  "soft tissue work to the upper trapezius and infraspinatus"),
        "97112": ("rhythmic stabilization and scapular control in quadruped",
                  "proprioceptive drills on the bodyblade"),
        "97530": ("simulated overhead reaching to a cabinet shelf",
                  "lifting and carrying tasks with a five pound weight"),
        "97535": ("reviewed dressing strategies and sleep positioning",
                  "training on shower and grooming with the affected arm"),
        "97116": ("in the hallway with contact guard",),
    },
    "knee": {
        "97110": ("quad sets, straight leg raises, and terminal knee extensions",
                  "mini-squats and step-ups to a six inch step",
                  "stationary bike for range of motion and hamstring curls"),
        "97140": ("patellar mobilizations and tibiofemoral joint mobilization",
                  "scar mobilization at the portal sites and soft tissue work to the quadriceps"),
        "97112": ("single-leg balance on foam with perturbation",
                  "closed-chain proprioceptive drills on the wobble board"),
        "97530": ("floor-to-waist lifting and squat-to-stand transfers",
                  "simulated stair negotiation and curb management"),
        "97116": ("with a rolling walker in the parallel bars, working on heel strike",
                  "over level ground focusing on knee flexion during swing"),
    },
    "lumbar": {
        "97110": ("prone press-ups and transverse abdominis activation",
                  "bridging, bird-dog, and dead bug progressions",
                  "hamstring and hip flexor stretching in supine"),
        "97140": ("grade three central posteroanterior mobilizations at L4 and L5",
                  "soft tissue work to the lumbar paraspinals and quadratus lumborum"),
        "97112": ("lumbar stabilization with neutral spine control on the ball",
                  "motor control retraining for lifting mechanics"),
        "97530": ("floor-to-waist lifting mechanics with a ten pound crate",
                  "simulated work tasks with body mechanics training"),
        "97012": ("in supine at twenty-five percent body weight",),
    },
    "cervical": {
        "97110": ("deep neck flexor endurance work and scapular retraction",
                  "cervical range of motion in all planes and chin tucks",
                  "upper trapezius and levator scapulae stretching"),
        "97140": ("grade three unilateral posteroanterior mobilizations at C5 and C6",
                  "suboccipital release and soft tissue work to the upper trapezius"),
        "97112": ("postural retraining with mirror feedback",
                  "cervical proprioception and joint position sense drills"),
        "97530": ("workstation set-up and simulated computer work with posture cueing",
                  "overhead reaching with cervical control"),
        "97012": ("in supine at ten pounds intermittent",),
    },
    "hip": {
        "97110": ("clamshells, side-lying abduction, and bridging",
                  "hip abductor strengthening with a band and step-downs",
                  "hip flexor and piriformis stretching"),
        "97140": ("hip joint mobilization with a long-axis distraction",
                  "soft tissue work to the gluteus medius and tensor fasciae latae"),
        "97112": ("single-leg stance with pelvic control cueing",
                  "Trendelenburg correction with tactile feedback"),
        "97530": ("sit-to-stand from a low surface and floor transfers",
                  "car transfer training and simulated household tasks"),
        "97116": ("with a straight cane focusing on step length symmetry",
                  "over level ground working on stance-phase hip control"),
    },
    "ankle": {
        "97110": ("heel raises, ankle four-way with a band, and towel scrunches",
                  "eccentric heel drops off a step and calf stretching",
                  "dorsiflexion range of motion and intrinsic foot strengthening"),
        "97140": ("talocrural joint mobilization with an anterior-posterior glide",
                  "soft tissue work to the gastrocsoleus complex and plantar fascia"),
        "97112": ("single-leg balance on the wobble board with eyes closed",
                  "proprioceptive drills on the BOSU with perturbation"),
        "97530": ("step-over-obstacle drills and uneven-surface negotiation",
                  "simulated return-to-sport cutting and landing mechanics"),
        "97116": ("over level ground focusing on heel-toe progression",
                  "with a single-point cane working on push-off"),
    },
}


def technique_detail(body_part: str, code: str) -> tuple[str, ...]:
    """Detail phrases for a treatment in a region, falling back to region-neutral wording."""
    return (TECHNIQUE_DETAIL_BY_PART.get(body_part, {}).get(code)
            or _GENERIC_DETAIL.get(code)
            or ("",))

# --- the ICD anti-circularity bank -------------------------------------------------
# Real ways a therapist NAMES a diagnosis that `coding_tables.ICD_BY_BODY_PART` does NOT list as
# a cue. Keyed by (body_part, rule.cues[0]) — the first cue identifies a rule, except that
# "segmental dysfunction" appears in both spine tables, hence the body part in the key.
#
# WHY THIS EXISTS. `_draw_diagnosis` used to pick the spoken phrase with
# `rng.choice(rule.cues)` — straight out of the extractor's own cue list. ICD recall was therefore
# 100% across 144 synthetic records by construction, measuring nothing except that the extractor
# recognizes the strings it was told to recognize. That is exactly the circularity CLAUDE.md rule
# 21 warns about, and it had been sitting in the eval unnoticed while the CPT side had a
# deliberate paraphrase gap all along (INTERVENTION_SPOKEN's "hands-on work", "functional
# activities"). These phrases restore the same honesty to the ICD half.
#
# A sample using one of these is still labeled with the CORRECT code, so a miss is a real miss and
# recall genuinely drops. Per rule 21(a), do NOT bulk-copy them into the cue table to make the
# number go up — decide phrase by phrase whether it is unambiguous enough to code on. Several
# below are deliberately ambiguous and should stay unmatched: "stiff shoulder" could be stiffness
# (M25.61-) or adhesive capsulitis (M75.0-), and guessing between them is a wrong claim.
DIAGNOSIS_PARAPHRASES: dict[tuple[str, str], tuple[str, ...]] = {
    # --- shoulder
    ("shoulder", "rotator cuff tendinopathy"): ("torn rotator cuff", "cuff tear", "RCT"),
    ("shoulder", "adhesive capsulitis"): ("capsulitis",),
    ("shoulder", "impingement syndrome"): ("impingement", "subacromial pain syndrome"),
    ("shoulder", "bicipital tendinitis"): ("long head biceps tendinopathy", "biceps tendonosis"),
    ("shoulder", "slap tear"): ("superior labrum tear", "labral pathology"),
    ("shoulder", "total shoulder arthroplasty"): ("shoulder replacement surgery", "new shoulder"),
    # --- knee
    ("knee", "anterior cruciate ligament tear"): ("blown ACL", "anterior cruciate rupture",
                                                  "ACL deficiency"),
    ("knee", "medial meniscus tear"): ("meniscal injury",),
    ("knee", "patellofemoral pain syndrome"): ("PFPS",),
    ("knee", "primary osteoarthritis of the knee"): ("degenerative knee", "wear and tear in the knee",
                                                     "tricompartmental OA"),
    ("knee", "total knee arthroplasty"): ("new knee", "knee replacement surgery"),
    # NB: "quad tendon irritation" was here and was a GENERATOR BUG, not a paraphrase — the
    # quadriceps tendon is a different structure from the patellar tendon and codes differently.
    # A wrong gold label is worse than a missing one; it would have scored a correct extraction
    # as a failure.
    ("knee", "patellar tendinitis"): ("patellar tendinosis", "jumpers knee"),
    # --- lumbar
    ("lumbar", "low back pain"): ("LBP", "back pain", "mechanical back pain"),
    ("lumbar", "sciatica"): ("sciatic pain", "radicular pain down the leg", "leg pain from the back"),
    ("lumbar", "herniated disc"): ("slipped disc", "disc bulge", "HNP"),
    ("lumbar", "lumbar spinal stenosis"): ("canal stenosis", "central stenosis", "narrowing of the canal"),
    ("lumbar", "degenerative disc disease"): ("degenerative discs", "disc disease", "worn discs"),
    ("lumbar", "lumbar sprain"): ("back strain", "pulled his back"),
    # --- cervical
    ("cervical", "cervicalgia"): ("neck ache", "sore neck"),
    ("cervical", "whiplash"): ("WAD", "flexion extension injury"),
    ("cervical", "cervical radiculopathy"): ("pinched nerve in the neck", "nerve root irritation"),
    ("cervical", "cervical disc herniation"): ("slipped disc in the neck", "disc bulge in the neck"),
    ("cervical", "cervicogenic headache"): ("headaches coming from the neck", "neck related headache"),
    # --- hip
    ("hip", "trochanteric bursitis"): ("GTPS",),
    ("hip", "primary osteoarthritis of the hip"): ("degenerative hip", "arthritic hip", "worn hip"),
    ("hip", "femoroacetabular impingement"): ("cam impingement", "pincer impingement"),
    ("hip", "total hip arthroplasty"): ("new hip", "hip replacement surgery"),
    ("hip", "hip labral tear"): ("torn labrum in the hip", "acetabular labrum injury"),
    ("hip", "iliotibial band syndrome"): ("ITB friction syndrome",),
    # --- ankle / foot
    ("ankle", "ankle sprain"): ("rolled ankle", "inversion injury", "turned his ankle"),
    ("ankle", "plantar fasciitis"): ("plantar heel pain",),
    ("ankle", "achilles tendinitis"): ("achilles tendinosis", "tendinopathy of the achilles"),
    ("ankle", "posterior tibial tendon dysfunction"): ("PTTD", "post tib dysfunction"),
    ("ankle", "osteoarthritis of the ankle"): ("degenerative ankle", "arthritic ankle"),
}

#: Share of samples that speak a paraphrase instead of a canonical cue, where one exists. High
#: enough that the honest recall is visible; low enough that the corpus still mostly reads like
#: standard clinical documentation.
DIAGNOSIS_PARAPHRASE_RATE = 0.4

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

# Region-neutral, so a new body part needs no new entries here.
SUBJECTIVE: tuple[str, ...] = (
    "{Subj} reports the {part} is feeling looser this week.",
    "Reports pain is better since the last session.",
    "Says the exercises are getting easier at home.",
    "{Subj} reports {poss} {part} is still sore in the mornings.",
    "{Subj} says the {part} tolerated last session well.",
)

# Region-specific functional complaints, so the corpus reads like a real note rather than a
# template with the body part swapped in.
SUBJECTIVE_BY_PART: dict[str, tuple[str, ...]] = {
    "shoulder": ("{Subj} says reaching overhead is easier than last visit.",
                 "{Subj} still has trouble sleeping on that side.",
                 "{Subj} reports {poss} can now reach the second shelf."),
    "knee": ("{Subj} says stairs are still the hardest part.",
             "{Subj} reports less swelling at the end of the day.",
             "{Subj} says {subj} can walk to the mailbox now without stopping."),
    "lumbar": ("{Subj} reports sitting for more than twenty minutes still aggravates it.",
               "{Subj} says the leg symptoms are not going past the knee anymore.",
               "{Subj} reports {subj} could load the dishwasher without a flare."),
    "cervical": ("{Subj} reports fewer headaches this week.",
                 "{Subj} says turning to check the blind spot while driving is easier.",
                 "{Subj} reports less tingling into the arm."),
    "hip": ("{Subj} says getting in and out of the car is easier.",
            "{Subj} reports {subj} can lie on that side for part of the night now.",
            "{Subj} says the limp is less noticeable by the afternoon."),
    "ankle": ("{Subj} reports the first steps in the morning are less painful.",
              "{Subj} says {subj} managed uneven ground in the yard without rolling it.",
              "{Subj} reports {subj} can stand at work for a full shift now."),
}

# One pronoun set per sample. A dictation that flips between "she" and "he" mid-note is a
# generator artifact no therapist produces, and it would give the downstream note model a
# contradiction to resolve that has nothing to do with what we're measuring.
VOICES: tuple[dict[str, str], ...] = (
    {"subj": "she", "Subj": "She", "obj": "her", "poss": "her", "Poss": "Her"},
    {"subj": "he", "Subj": "He", "obj": "him", "poss": "his", "Poss": "His"},
)

VISIT_TYPES: dict[str, tuple[str, ...]] = {
    # No post-op variant here: the intake block renders a GRADUAL onset, and "post-op week 4"
    # alongside "onset was gradual about two months ago" is a contradiction a clinician spots
    # instantly. Post-surgical evals need their own onset story before that variant comes back.
    "initial": ("Initial Evaluation", "Initial evaluation, new patient",
                "Initial Evaluation, new referral"),
    "followup": ("Follow-up, week 3", "Follow-up visit", "Follow-up, week 6",
                 "Follow-up, post-op week 8"),
}

FRACTIONS: tuple[tuple[str, float], ...] = (
    ("a third", 1 / 3), ("a half", 1 / 2), ("a quarter", 1 / 4), ("two thirds", 2 / 3),
)


# ==================================================================================
# Initial-evaluation intake
# ==================================================================================
# An INITIAL EVAL is not a short follow-up with a different title. `templates/initial.md` asks for
# ~17 fields — medications, allergies, past medical history, social history and living
# environment, prior level of function, ROM and strength by region, goals, plan of treatment — and
# a dictation that contains none of them leaves the 4B model to invent them all. Observed on the
# first demo seed: the model wrote "Ibuprofen 400mg, twice daily" and "no known drug allergies"
# for a dictation that mentioned neither. That is CLAUDE.md rule 19 (completeness over-read as
# "every section must be filled") firing because the SOURCE was empty, and rule 15's fix applies
# in reverse — the template was fine; the dictation had nothing to put in it.
#
# These banks give an initial-eval dictation real intake to be extracted FROM, so the note is
# filled from stated facts and the gap flags mean something.

MEDICATIONS: tuple[str, ...] = (
    "lisinopril ten milligrams daily", "metformin five hundred milligrams twice a day",
    "atorvastatin twenty milligrams at bedtime", "levothyroxine eighty-eight micrograms daily",
    "amlodipine five milligrams daily", "ibuprofen two hundred milligrams as needed for pain",
    "acetaminophen one thousand milligrams three times a day as needed",
    "omeprazole twenty milligrams daily", "sertraline fifty milligrams daily",
    "apixaban five milligrams twice a day", "gabapentin three hundred milligrams at night",
    "a daily multivitamin", "vitamin D two thousand units daily",
)

ALLERGIES: tuple[str, ...] = (
    "No known drug allergies", "Allergic to penicillin, it gives her a rash",
    "Allergic to sulfa drugs", "No known drug allergies except codeine, which makes him nauseous",
    "Allergic to latex",
)

PAST_MEDICAL_HISTORY: tuple[str, ...] = (
    "hypertension", "type two diabetes", "high cholesterol", "hypothyroidism",
    "atrial fibrillation", "asthma", "osteoarthritis in the other knee", "chronic kidney disease",
    "a prior back surgery", "depression", "obstructive sleep apnea",
)

SOCIAL_HISTORY: tuple[str, ...] = (
    "Lives alone in a single story home with one step to enter",
    "Lives with {poss} spouse in a two story home, bedroom upstairs, fourteen steps with a rail",
    "Lives with {poss} spouse in a ranch home, no steps to enter",
    "Lives alone in a second floor apartment with no elevator",
    "Lives with {poss} daughter who assists with meals and transport",
)

# {Subj}/{subj}/{poss} are filled from the sample's single VOICE — a note that says "She works
# from home" and then "He was independent" is a generator artifact no therapist produces.
OCCUPATION: tuple[str, ...] = (
    "{Subj} works part time as a cashier",
    "{Subj} is retired, previously a high school teacher",
    "{Subj} works from home at a desk",
    "{Subj} is a delivery driver, currently on modified duty",
    "{Subj} is a nurse and is on {poss} feet all shift",
    "{Subj} is retired and volunteers twice a week",
)

# Region-neutral: "stopped doing anything overhead" is a shoulder story and read as nonsense on a
# knee patient.
PRIOR_LEVEL_OF_FUNCTION: tuple[str, ...] = (
    "Prior level of function was fully independent, walking in the community without a device",
    "Prior level of function independent, {subj} walked about a mile a day for exercise",
    "Prior level of function independent with all activities of daily living",
    "{Subj} was independent but had been limiting activity for about a year because of this",
)

PATIENT_GOALS: dict[str, tuple[str, ...]] = {
    "shoulder": ("reach the overhead cabinets", "sleep on that side again", "get back to swimming"),
    "knee": ("get up and down the stairs without the rail", "return to walking the dog",
             "kneel in the garden again"),
    "lumbar": ("sit through a full workday", "lift her grandchild", "get back to the gym"),
    "cervical": ("drive and check the blind spot comfortably", "work at the computer without headaches"),
    "hip": ("get in and out of the car easily", "walk to the shops without stopping"),
    "ankle": ("get back to running", "stand a full shift at work", "walk on uneven ground safely"),
}

# ROM and strength phrased the way a therapist dictates them, per region. The numbers are real
# values the note must carry through, and the verification layer anchors against them.
OBJECTIVE_BY_PART: dict[str, tuple[str, ...]] = {
    "shoulder": ("Right shoulder active flexion one hundred ten degrees, abduction ninety degrees, "
                 "external rotation forty degrees, left side is full",
                 "Strength, shoulder flexion four minus out of five, abduction three plus out of five",),
    "knee": ("Knee active range five to ninety degrees, extension lacking five degrees",
             "Strength, quadriceps three plus out of five, hamstrings four out of five",),
    "lumbar": ("Lumbar flexion limited to fingertips at the knees, extension twenty degrees",
               "Strength, hip abduction four out of five bilaterally, straight leg raise sixty degrees",),
    "cervical": ("Cervical rotation sixty degrees to the right and fifty to the left",
                 "Strength, deep neck flexor endurance twelve seconds",),
    "hip": ("Hip flexion ninety degrees, internal rotation fifteen degrees",
            "Strength, hip abduction three plus out of five on the involved side",),
    "ankle": ("Ankle dorsiflexion five degrees on the involved side, fifteen on the other",
              "Strength, ankle eversion four minus out of five",),
}

PAIN_REPORTS: tuple[str, ...] = (
    "Pain is worst seven out of ten, best two out of ten, currently four out of ten",
    "Pain worst eight out of ten, best three out of ten, current six out of ten",
    "Pain is worst five out of ten, best one out of ten, currently three out of ten",
)

FALL_RISK: tuple[str, ...] = (
    "No falls in the past year", "One fall about eight months ago in the bathroom, no injury",
    "No falls, but {subj} reports feeling unsteady on uneven ground",
)

PLAN_OF_TREATMENT: tuple[str, ...] = (
    "Plan is twice a week for six weeks, forty-five minutes a session, certification period sixty days",
    "Plan is three times a week for eight weeks, sixty minutes a session, certification period sixty days",
    "Plan is twice a week for twelve weeks, forty-five minutes a session, certification period sixty days",
)

ASSESSMENT_LINES: tuple[str, ...] = (
    "Assessment is that skilled physical therapy is medically necessary, rehab potential is good",
    "Clinical complexity is moderate given the comorbidities, rehab potential is good",
    "Skilled PT medically necessary for strength and mobility deficits limiting function",
)
