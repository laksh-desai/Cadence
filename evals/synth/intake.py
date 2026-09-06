"""Long-form initial-evaluation dictation, in the shape a real outpatient PT actually dictates.

Modelled on the ten hand-written long-form samples in `docs/synthetic-longform-inputs.md`
(911-1216 words each). The defining feature is NOT length for its own sake — it is that the
therapist reads the intake form aloud FIELD BY FIELD, so the dictation is a sequence of spoken
labels: "History of present illness, ...", "Precautions and contraindications, ...", "Prior living
environment, ...", "Objective short-term goals, ...". Harvesting those samples gives the field
order this module reproduces, and every label below appears in at least 6 of the 10.

Why this matters beyond realism: `templates/initial.md` asks for ~17 sections, and the previous
short intake (~220 words) left most of them thinly sourced or unsourced. A dictation that actually
contains each field is what lets rule 15 (never drop a stated fact) and rule 19 (never invent an
unstated one) be measured at all — with an empty source, every section the model fills is a
fabrication and the note tells you nothing about the model.

Region-specific where the clinical content genuinely differs (precautions, tests and measures,
musculoskeletal findings, functional mobility, goals); region-neutral everywhere else
(medications, allergies, social history, cognition, cardiopulmonary).
"""

from __future__ import annotations

import random

from evals.synth import banks

# --- identity ---------------------------------------------------------------------
_DECADES = ("forty", "fifty", "sixty", "seventy", "eighty")
_ONES = ("one", "two", "three", "four", "five", "six", "seven", "eight", "nine")


def _spoken_age(rng: random.Random) -> str:
    """"seventy-eight-year-old" — real dictations state the age in words, never digits."""
    return f"{rng.choice(_DECADES)}-{rng.choice(_ONES)}-year-old"


# --- region-specific clinical content ----------------------------------------------
PRECAUTIONS: dict[str, tuple[str, ...]] = {
    "shoulder": ("no lifting greater than five pounds with the involved arm, no active internal "
                 "rotation behind the back, and sling for community outings only",
                 "no overhead lifting greater than ten pounds and monitor for increased night pain"),
    "knee": ("weight bearing as tolerated on the involved side, no forced flexion beyond patient "
             "tolerance, and monitor the incision for signs of infection",
             "weight bearing as tolerated, avoid deep squatting and pivoting on the involved leg"),
    "lumbar": ("no lifting greater than fifteen pounds, avoid repeated end-range flexion, and "
               "monitor for any change in bowel or bladder function",
               "avoid prolonged sitting beyond thirty minutes and no lifting from the floor"),
    "cervical": ("avoid end-range extension and sustained overhead work, and monitor for any "
                 "increase in upper extremity numbness or tingling",
                 "no lifting greater than ten pounds overhead, avoid prolonged forward head posture"),
    "hip": ("posterior hip precautions in effect, no hip flexion beyond ninety degrees, no "
            "adduction past midline, and no internal rotation",
            "weight bearing as tolerated with a device, avoid prolonged single-leg stance"),
    "ankle": ("weight bearing as tolerated in the boot, avoid uneven surfaces, and monitor for "
              "increased swelling at the end of the day",
              "no running or cutting activity, avoid barefoot walking on hard floors"),
}

TESTS_AND_MEASURES: dict[str, tuple[str, ...]] = {
    "shoulder": ("Timed Up and Go fourteen seconds, QuickDASH score fifty-two, "
                 "hand grip strength symmetric bilaterally",
                 "QuickDASH score forty-eight, Timed Up and Go twelve seconds"),
    "knee": ("Timed Up and Go eighteen seconds, five times sit to stand nineteen seconds, "
             "knee outcome survey sixty-two percent",
             "Timed Up and Go sixteen seconds, thirty second chair rise eight repetitions"),
    "lumbar": ("Oswestry Disability Index forty-two percent, straight leg raise positive on the "
               "involved side at sixty degrees",
               "Oswestry Disability Index thirty-six percent, repeated extension centralizes symptoms"),
    "cervical": ("Neck Disability Index thirty-eight percent, Spurling test negative bilaterally, "
                 "deep neck flexor endurance twelve seconds",
                 "Neck Disability Index forty-four percent, cervical distraction relieves symptoms"),
    "hip": ("Timed Up and Go seventeen seconds, thirty second chair rise seven repetitions, "
            "Trendelenburg positive on the involved side",
            "Timed Up and Go fifteen seconds, single leg stance eight seconds on the involved side"),
    "ankle": ("Foot and Ankle Ability Measure sixty-four percent, single leg stance twelve seconds "
              "on the involved side, heel raise test eight repetitions",
              "Foot and Ankle Ability Measure seventy-one percent, single leg balance fourteen seconds"),
}

MSK_ASSESSMENT: dict[str, tuple[str, ...]] = {
    "shoulder": ("involved shoulder active flexion one hundred ten degrees, abduction ninety "
                 "degrees, external rotation forty degrees, internal rotation to the back pocket; "
                 "uninvolved side is full throughout. Strength, shoulder flexion four minus out of "
                 "five, abduction three plus out of five, external rotation four out of five, "
                 "grip five out of five bilaterally",),
    "knee": ("involved knee active range five to ninety degrees with a five degree extensor lag, "
             "passive range zero to one hundred degrees; uninvolved knee zero to one hundred "
             "thirty-five. Strength, quadriceps three plus out of five, hamstrings four out of "
             "five, hip abduction four minus out of five",),
    "lumbar": ("lumbar flexion limited to fingertips at the knees, extension twenty degrees and "
               "painful, side bending symmetric and limited by twenty-five percent. Strength, hip "
               "abduction four out of five bilaterally, great toe extension five out of five, "
               "straight leg raise sixty degrees on the involved side",),
    "cervical": ("cervical rotation sixty degrees to the right and fifty to the left, extension "
                 "limited by fifty percent and reproduces symptoms, flexion within normal limits. "
                 "Strength, upper extremity myotomes five out of five throughout, deep neck flexor "
                 "endurance reduced",),
    "hip": ("involved hip flexion ninety degrees, internal rotation fifteen degrees, external "
            "rotation thirty degrees, extension lacking ten degrees. Strength, hip abduction three "
            "plus out of five, hip extension four minus out of five, knee extension five out of five",),
    "ankle": ("involved ankle dorsiflexion five degrees, plantar flexion forty degrees, inversion "
              "and eversion limited by twenty-five percent; uninvolved side dorsiflexion fifteen "
              "degrees. Strength, ankle eversion four minus out of five, plantar flexion four out "
              "of five, dorsiflexion four plus out of five",),
}

FUNCTIONAL_MOBILITY: dict[str, tuple[str, ...]] = {
    "shoulder": ("bed mobility independent, transfers independent, gait independent without a "
                 "device, stairs independent with a rail. Reaching overhead limited to shoulder "
                 "height, unable to reach the top cabinet shelf, requires assistance with donning "
                 "a pullover shirt",),
    "knee": ("bed mobility independent, sit to stand with upper extremity support, ambulates two "
             "hundred feet with a rolling walker at supervision level with a shortened stance time "
             "on the involved side, negotiates four steps with one rail using a step-to pattern, "
             "community mobility not tested today",),
    "lumbar": ("bed mobility with increased time and log roll technique, sit to stand independent "
               "with a push off, ambulates community distances without a device, tolerates sitting "
               "twenty minutes and standing fifteen minutes before symptoms increase, unable to "
               "lift from floor level",),
    "cervical": ("bed mobility independent, transfers independent, gait independent without a "
                 "device, stairs independent. Unable to sustain computer work beyond thirty "
                 "minutes, reports difficulty checking the blind spot while driving",),
    "hip": ("bed mobility independent with increased time, sit to stand from a low surface requires "
            "upper extremity support, ambulates one hundred fifty feet with a single point cane "
            "with a Trendelenburg gait pattern, negotiates stairs step-to with one rail, car "
            "transfer requires assistance",),
    "ankle": ("bed mobility independent, transfers independent, ambulates two hundred fifty feet "
              "in the boot with an antalgic pattern, negotiates stairs reciprocally with a rail, "
              "unable to walk on uneven ground without symptoms",),
}

SHORT_TERM_GOALS: dict[str, tuple[str, ...]] = {
    "shoulder": ("patient will improve involved shoulder active flexion to at least one hundred "
                 "forty degrees in three weeks to allow overhead reaching; patient will don a "
                 "pullover shirt independently in four weeks",),
    "knee": ("patient will improve involved knee active flexion to at least one hundred five "
             "degrees and reduce the extensor lag to less than five degrees in three weeks to "
             "improve gait mechanics; patient will ambulate two hundred feet with the least "
             "restrictive device at supervision level in three weeks",),
    "lumbar": ("patient will tolerate sitting for forty-five minutes without an increase in "
               "symptoms in three weeks; patient will demonstrate correct hip hinge mechanics with "
               "a ten pound load in four weeks",),
    "cervical": ("patient will tolerate computer work for sixty minutes without an increase in "
                 "headache in four weeks; patient will improve cervical rotation to seventy degrees "
                 "bilaterally in three weeks",),
    "hip": ("patient will ambulate two hundred feet with a single point cane without a Trendelenburg "
            "pattern in four weeks; patient will perform sit to stand from a standard height chair "
            "without upper extremity support in three weeks",),
    "ankle": ("patient will ambulate community distances out of the boot without an antalgic "
              "pattern in four weeks; patient will improve ankle dorsiflexion to at least ten "
              "degrees in three weeks",),
}

LONG_TERM_GOALS: dict[str, tuple[str, ...]] = {
    "shoulder": ("patient will demonstrate five out of five involved shoulder strength and full "
                 "functional overhead reach in eight weeks; patient will sleep through the night "
                 "without positional pain and be independent with a home exercise program by "
                 "discharge",),
    "knee": ("patient will demonstrate five out of five involved lower extremity strength, "
             "ambulate in the community without an assistive device, and negotiate twelve stairs "
             "with one rail in eight weeks; patient will be independent with all activities of "
             "daily living including tub transfers by discharge",),
    "lumbar": ("patient will return to full work duties including lifting from floor level in ten "
               "weeks; patient will be independent with a home exercise program and a self "
               "management strategy for symptom flare-ups by discharge",),
    "cervical": ("patient will be headache free for two consecutive weeks and return to full work "
                 "duties in ten weeks; patient will be independent with a postural home program by "
                 "discharge",),
    "hip": ("patient will ambulate in the community without an assistive device and negotiate "
            "stairs reciprocally in ten weeks; patient will be independent with all activities of "
            "daily living including lower body dressing by discharge",),
    "ankle": ("patient will return to recreational running and uneven-terrain walking without "
              "symptoms in ten weeks; patient will demonstrate fifteen single leg heel raises and "
              "be independent with a home program by discharge",),
}

TREATMENT_APPROACHES: dict[str, str] = {
    "shoulder": "therapeutic exercise, neuromuscular re-education, manual therapy for range of "
                "motion, and therapeutic activities for functional reintegration",
    "knee": "therapeutic exercise, neuromuscular re-education, gait training, therapeutic "
            "activities, and manual therapy for range of motion",
    "lumbar": "therapeutic exercise, neuromuscular re-education for motor control, manual therapy, "
              "and therapeutic activities for body mechanics training",
    "cervical": "therapeutic exercise, manual therapy, neuromuscular re-education for postural "
                "retraining, and therapeutic activities for workstation tolerance",
    "hip": "therapeutic exercise, gait training, neuromuscular re-education, and therapeutic "
           "activities for functional transfers",
    "ankle": "therapeutic exercise, neuromuscular re-education for balance and proprioception, "
             "gait training, and manual therapy",
}

# --- region-neutral intake ---------------------------------------------------------
HPI_TEMPLATES: tuple[str, ...] = (
    "the patient reports a gradual onset of symptoms over approximately the past {onset} with no specific "
    "injury recalled, progressively worsening to the point of limiting daily activity. {Subj} saw "
    "{poss} primary care physician, imaging was obtained, and {subj} was referred to outpatient "
    "physical therapy. {Subj} reports difficulty sleeping due to the pain and increasing reliance "
    "on family for household tasks",
    "symptoms began approximately {onset} ago following a specific incident at home, and have not "
    "resolved with rest and over the counter medication. {Subj} was evaluated by {poss} physician, "
    "started on a course of anti-inflammatories, and referred here for skilled therapy. {Subj} "
    "reports the symptoms are worse at the end of the day and interfere with sleep",
)

CODE_STATUS: tuple[str, ...] = ("Code status full code", "Code status unknown",
                                "Code status full code per patient report")

RESPIRATORY: tuple[str, ...] = (
    "Respiratory status within functional limits, no use of supplemental oxygen",
    "Respiratory status within functional limits on room air, no shortness of breath at rest",
)

PRIOR_EQUIPMENT: tuple[str, ...] = (
    "Prior equipment, none, patient did not use an assistive device prior to this episode",
    "Prior equipment, a single point cane used only outside the home",
    "Prior equipment, a rolling walker issued at hospital discharge",
    "Prior equipment, none",
)

PRIOR_THERAPY: tuple[str, ...] = (
    "Prior therapy, yes, patient completed a course of outpatient physical therapy a few years ago "
    "for an unrelated problem",
    "Prior therapy, no, this is the patient's first course of physical therapy",
    "Prior therapy, yes, patient completed home health physical therapy after the surgery which is "
    "now transitioning to outpatient",
)

COGNITION: tuple[str, ...] = (
    "Prior cognitive assistance, patient lives independently and required no supervision, cognition "
    "intact and alert and oriented to person, place, and time",
    "Prior cognitive assistance, none required, patient is alert and oriented and follows multi-step "
    "instructions without difficulty",
)

STEADINESS: tuple[str, ...] = (
    "Steadiness, patient reports feeling unsteady on uneven ground and in low light",
    "Steadiness, patient denies unsteadiness on level surfaces",
    "Steadiness, patient reports occasional unsteadiness when turning quickly",
)

FEAR_OF_FALLING: tuple[str, ...] = (
    "Fear of falling, yes, particularly on stairs", "Fear of falling, no",
    "Fear of falling, yes, somewhat, especially outdoors",
)

CARDIOPULMONARY: tuple[str, ...] = (
    "Cardiopulmonary, patient denies chest pain and denies shortness of breath at rest, reports "
    "mild exertional dyspnea with stairs, blood pressure at rest one hundred thirty over eighty, "
    "heart rate seventy-four, oxygen saturation ninety-seven percent on room air",
    "Cardiopulmonary, no chest pain, no shortness of breath, blood pressure one hundred twenty-eight "
    "over seventy-eight, heart rate sixty-eight, oxygen saturation ninety-eight percent",
)

OTHER_SYSTEMS: tuple[str, ...] = (
    "Other systems, integumentary intact with no open areas, sensation intact to light touch "
    "throughout, coordination within normal limits, no edema noted, communication and cognition "
    "within functional limits",
    "Other systems, skin intact, sensation intact to light touch, mild pitting edema at the "
    "involved extremity, coordination within normal limits, communication intact",
)

EVALUATION_COMPLEXITY: tuple[str, ...] = (
    "Evaluation summary, history and comorbidities moderate, more than three body structures and "
    "functions involved, clinical presentation stable to evolving, clinical decision making "
    "moderate complexity",
    "Evaluation summary, history and comorbidities low, one to two body structures involved, "
    "clinical presentation stable, clinical decision making low complexity",
)

FREQUENCY: tuple[str, ...] = (
    "Frequency, patient will be seen two times a week for eight weeks",
    "Frequency, patient will be seen two to three times a week for six weeks",
    "Frequency, patient will be seen three times a week for twelve weeks",
)

DURATION: tuple[str, ...] = ("Duration, forty-five minutes per session",
                             "Duration, sixty minutes per session")

FOCUS: tuple[str, ...] = ("Focus of plan of treatment, restoration and compensation",
                          "Focus of plan of treatment, restoration")

PARTICIPATION: tuple[str, ...] = (
    "Participation, patient demonstrated understanding of the need for skilled services and is in "
    "agreement with the plan of care",
    "Participation, patient verbalized understanding of the plan of care and a family member will "
    "assist with the home program",
)

DISCHARGE_PLAN: tuple[str, ...] = (
    "Transition and discharge plan, anticipate discharge to an independent home exercise program "
    "with follow up with the referring provider",
    "Transition and discharge plan, discharge home at prior level of function with a home exercise "
    "program once goals are met",
)

REHAB_POTENTIAL: tuple[str, ...] = (
    "Potential for achieving rehab goals is good to excellent due to a high prior level of function "
    "and patient motivation",
    "Potential for achieving rehab goals is good, although the comorbidities may slow progress",
)


# --- fields the richest real examples carry (record 108 is 2,103 words) --------------
SURGICAL_HISTORY: tuple[str, ...] = (
    "Surgical history, an appendectomy in {poss} twenties and a cholecystectomy about ten years ago",
    "Surgical history, a right knee arthroscopy about fifteen years ago and a cesarean section",
    "Surgical history, none significant",
    "Surgical history, a prior rotator cuff repair on the other side a few years ago",
)

PRIOR_TREATMENT: tuple[str, ...] = (
    "Prior treatment, patient had a corticosteroid injection about three months ago which helped "
    "for a few weeks, and has been taking over the counter anti-inflammatories since",
    "Prior treatment, patient tried rest and activity modification without relief, and has not had "
    "any injections",
    "Prior treatment, patient completed a short course of home health physical therapy after the "
    "surgery and was issued a home program",
)

IMAGING: tuple[str, ...] = (
    "Imaging, x-ray was obtained and was negative for acute fracture, with mild degenerative "
    "changes noted",
    "Imaging, MRI from about two months ago is consistent with the referring diagnosis",
    "Imaging, x-ray showed joint space narrowing and the patient brought a copy of the report",
    "Imaging, none obtained to date",
)

SLEEP: tuple[str, ...] = (
    "Sleep, patient reports waking two to three times a night due to pain and has been sleeping in "
    "a recliner since the symptoms began",
    "Sleep, patient reports difficulty falling asleep due to pain but sleeps through the night once "
    "asleep",
    "Sleep, patient reports sleep is largely unaffected",
)

ADL_DETAIL: tuple[str, ...] = (
    "Activities of daily living, upper body dressing requires setup, lower body dressing requires "
    "minimal assistance for socks and shoes, bathing requires contact guard for the tub transfer, "
    "grooming independent, toileting independent, feeding independent. Meal preparation is "
    "currently shared with a family member, medication management independent, and household "
    "mobility is independent with increased time",
    "Activities of daily living, patient is independent with upper body dressing, grooming, "
    "toileting, and feeding; requires minimal assistance for lower body dressing and contact guard "
    "for tub transfers. Meal preparation and laundry are being done by a family member since the "
    "symptoms began, and medication management is independent",
)

HOME_PROGRAM: tuple[str, ...] = (
    "Home exercise program issued today, four exercises with a printed handout: isometrics ten "
    "repetitions holding five seconds three times a day, active assisted range of motion ten "
    "repetitions three times a day, a gentle stretch holding thirty seconds twice a day, and "
    "postural retraining ten repetitions twice a day. Patient returned demonstration on all four "
    "and performed them correctly with verbal cueing only",
    "Home exercise program issued today, three exercises reviewed with a printed handout, ten to "
    "fifteen repetitions each, two to three times a day. Patient returned demonstration correctly "
    "and verbalized understanding of the frequency",
)

PATIENT_EDUCATION: tuple[str, ...] = (
    "Patient education, reviewed the precautions in detail, discussed activity pacing and symptom "
    "management, and reviewed the expected course of recovery. Patient verbalized understanding "
    "and asked appropriate questions",
    "Patient education, instructed in activity modification, ice and elevation as needed, and the "
    "importance of adherence to the home program. Patient verbalized understanding",
)

BARRIERS: tuple[str, ...] = (
    "Barriers to discharge, the stairs to the bedroom are the main environmental barrier; "
    "facilitators are that the patient is highly motivated, cognitively intact, and has supportive "
    "family",
    "Barriers to discharge, none significant; facilitators are a high prior level of function, good "
    "motivation, and a supportive home environment",
)

def render(rng: random.Random, *, body_part: str, voice: dict, side: str | None,
           dx_phrase: str, dx_formal: str) -> str:
    """One long-form initial-eval dictation (~1,000-1,300 words), field by spoken field.

    Deterministic in `rng`. Every clinical value stated here is a real fact the note must carry
    through, so the verification layer has something to anchor against.
    """
    part = banks.SPOKEN_PART.get(body_part, body_part)
    sided = f"{side} " if side and side != "bilateral" else ("bilateral " if side else "")

    # The presenting complaint must follow the DIAGNOSIS. Hardcoding "pain" here put the phrase
    # "patient presents with knee pain" — a diagnosis-framing clause — into the transcript of a
    # patient whose diagnosis was stiffness, so the extractor correctly read a pain diagnosis that
    # the gold label (stiffness) did not contain, and scored a false positive for doing exactly the
    # right thing. Ten of the corpus's remaining ICD false positives were this one generator bug
    # across three regions. Rule 21: when the score looks wrong, check the labels before the table.
    _stiff = any(w in dx_phrase.lower()
                 for w in ("stiff", "motion", "frozen", "capsulitis", "arthrofibrosis"))
    presenting = ("stiffness and decreased range of motion" if _stiff
                  else f"{sided}{part} pain")
    v = dict(voice)
    sex = "female" if v["subj"] == "she" else "male"
    meds = rng.sample(banks.MEDICATIONS, rng.randint(5, 7))
    pmh = rng.sample(banks.PAST_MEDICAL_HISTORY, rng.randint(3, 5))
    goals = rng.sample(banks.PATIENT_GOALS.get(body_part, ("return to normal activity",)),
                       min(2, len(banks.PATIENT_GOALS.get(body_part, ("x",)))))
    onset = rng.choice(("six weeks", "three months", "four weeks", "two months", "five months"))

    def pick(bank):
        return rng.choice(bank).format(**v)

    f = [
        f"Okay, physical therapy initial evaluation. Patient is a {_spoken_age(rng)} {sex} "
        f"referred to outpatient physical therapy, referring diagnosis {dx_phrase}.",

        f"Chief complaint, patient is complaining of {presenting}, and difficulty "
        f"with functional mobility and activities of daily living, requiring skilled physical "
        f"therapy to improve strength and range of motion, reduce risk of falls, and return to "
        f"prior level of function.",

        "History of present illness, " + rng.choice(HPI_TEMPLATES).format(onset=onset, **v) + ".",

        f"Prior medical history, {', '.join(pmh)}.",

        pick(SURGICAL_HISTORY) + ".",
        pick(PRIOR_TREATMENT) + ".",
        pick(IMAGING) + ".",

        f"Precautions and contraindications, {rng.choice(PRECAUTIONS[body_part])}.",

        pick(CODE_STATUS) + ".",
        pick(RESPIRATORY) + ".",

        f"Medications, patient takes {', '.join(meds)}.",

        rng.choice(banks.ALLERGIES).format(**v) + ".",

        pick(PRIOR_THERAPY) + ".",

        f"Prior living environment, {rng.choice(banks.SOCIAL_HISTORY).format(**v).lower()}.",

        pick(COGNITION) + ".",

        f"Prior living description, {rng.choice(banks.OCCUPATION).format(**v).lower()}.",

        pick(PRIOR_EQUIPMENT) + ".",

        f"Prior level of function, {rng.choice(banks.PRIOR_LEVEL_OF_FUNCTION).format(**v).lower()}.",

        "Prior level of function source, patient report.",

        f"History of falls, {rng.choice(banks.FALL_RISK).format(**v).lower()}.",

        pick(STEADINESS) + ".",
        pick(FEAR_OF_FALLING) + ".",

        f"Pain, {rng.choice(banks.PAIN_REPORTS).format(**v).lower()}, described as an ache in the "
        f"{sided}{part}, worse at night and with activity.",

        f"Tests and measures, {rng.choice(TESTS_AND_MEASURES[body_part])}.",

        f"Musculoskeletal assessment, {rng.choice(MSK_ASSESSMENT[body_part])}.",

        "Neuromuscular, sensation intact to light touch throughout, no reported numbness or tingling.",

        pick(CARDIOPULMONARY) + ".",
        pick(OTHER_SYSTEMS) + ".",

        f"Functional mobility assessment, {rng.choice(FUNCTIONAL_MOBILITY[body_part])}.",

        pick(ADL_DETAIL) + ".",
        pick(SLEEP) + ".",

        f"Patient goals, {v['subj']} would like to {' and to '.join(goals)}.",

        f"Assessment summary, patient presents with {presenting}, decreased range of motion, "
        f"and strength deficits consistent with {dx_formal.lower()}, superimposed on multiple "
        f"comorbidities, limiting functional mobility and safe community ambulation and requiring "
        f"skilled physical therapy to restore strength and mobility, reduce fall risk, and return "
        f"the patient to prior level of function. Patient is at increased risk for deconditioning, "
        f"further falls, and loss of independence without skilled intervention.",

        pick(EVALUATION_COMPLEXITY) + ".",

        f"Objective short-term goals, {rng.choice(SHORT_TERM_GOALS[body_part])}.",
        f"Objective long-term goals, {rng.choice(LONG_TERM_GOALS[body_part])}.",

        f"Plan of treatment, treatment approaches include {TREATMENT_APPROACHES[body_part]}.",

        pick(FREQUENCY) + ".",
        pick(DURATION) + ".",
        "Certification period starting today for sixty days.",
        pick(REHAB_POTENTIAL) + ".",
        pick(FOCUS) + ".",
        pick(HOME_PROGRAM) + ".",
        pick(PATIENT_EDUCATION) + ".",
        pick(PARTICIPATION) + ".",
        pick(DISCHARGE_PLAN) + ".",
        pick(BARRIERS) + ".",
    ]
    return " ".join(f)
