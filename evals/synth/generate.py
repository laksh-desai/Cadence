"""Deterministic, seeded, LABEL-FIRST synthetic PT dictation generator.

The order of operations is the whole design. Ground truth is DRAWN FIRST — diagnosis, ICD code,
which interventions were performed, how many minutes each took, the resulting timed total and
units — and only then is a dictation RENDERED that expresses it. The labels are therefore exact
by construction: they are the generator's input, not an interpretation of its output. Nothing
here calls a model, so it stays fully offline (200 samples in milliseconds) and no LLM's guess
ever becomes a gold label.

This does NOT violate the guardrail in docs/synthetic-data-plan.md ("Claude generates INPUTS, not
training labels"). That guardrail is about the gold NOTE a fine-tune would learn from, which must
be clinician-corrected. These labels are billing facts chosen up front by a seeded RNG, which is
a different kind of object entirely — and they are used only to SCORE extraction, never to train.

Seeding is per-sample and derived from a string INCLUDING the index, never sequential draws off
one shared stream. The consequence is practical: raising --count from 20 to 40 leaves samples
1-20 byte-identical, so the diff on a committed corpus file stays readable and re-running is
idempotent.
"""

from __future__ import annotations

import random
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta

from app.generate import coding_tables as tables
from app.generate.billing import (
    AMA_RULE_OF_EIGHTS,
    CMS_SUBSTITUTION,
    allocate_units,
    units_for_minutes,
)
from app.generate.cpt import is_timed
from evals.synth import banks, intake

#: Bump when a change alters the TEXT a given seed produces. `evals/results.py` refuses to compare
#: runs across versions without --force, because a corpus change and a code change would otherwise
#: be indistinguishable in a score diff.
# v2 (2026-08): initial evals became long-form intake dictations (`intake.py`, ~1,000-1,300
# words) instead of short follow-up-shaped text, several unsafe diagnosis paraphrases were
# removed, and the assessment line now names the formal diagnosis. Scores from v1 runs are
# not comparable to v2 runs.
# v3: the intake's chief-complaint and assessment lines now state the complaint the
# DIAGNOSIS implies rather than always "pain", which was asserting a pain diagnosis in a
# diagnosis-framing clause for stiffness patients.
GENERATOR_VERSION = 3

COMPLEXITIES: tuple[str, ...] = ("low", "medium", "high")
NOTE_TYPES: tuple[str, ...] = ("initial", "followup")

#: Synthetic ids are blocked per body part so `dataset.load_corpus`'s cross-file uniqueness check
#: can never collide — including with the hand-written records, which live below 1000.
ID_BLOCKS: dict[str, int] = {
    "shoulder": 1000, "knee": 2000, "lumbar": 3000, "cervical": 4000, "hip": 5000, "ankle": 6000,
}

_BASE_DATE = date(2026, 3, 2)

# How many timed treatments, and how many distractors, each complexity produces.
_PROFILE = {
    "low":    {"timed": (1, 2), "untimed": 0.0, "distractors": 0, "filler": 0.0,  "bare": 0.0},
    "medium": {"timed": (2, 3), "untimed": 0.4, "distractors": 2, "filler": 0.10, "bare": 0.0},
    "high":   {"timed": (3, 4), "untimed": 0.7, "distractors": 4, "filler": 0.22, "bare": 0.25},
}

_ONES = ("zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
         "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen",
         "eighteen", "nineteen")
_TENS = ("", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety")


def spoken_number(n: int) -> str:
    """0-99 as a therapist says it. Dictation is speech, so the corpus must be spoken words —
    writing "20" would skip the spoken-to-digit normalization the extractor actually has to do."""
    if n < 20:
        return _ONES[n]
    tens, ones = divmod(n, 10)
    return _TENS[tens] + ("-" + _ONES[ones] if ones else "")


# ==================================================================================
# Gold labels
# ==================================================================================

@dataclass(frozen=True)
class GoldIntervention:
    code: str
    label: str
    minutes: int | None
    timed: bool
    billable: bool = True


@dataclass(frozen=True)
class GoldDistractor:
    """An intervention NAMED in the dictation that must not be billed, and why.

    `reason` is what makes a leak attributable: a scorer can say "the extractor billed a
    prior-visit treatment" rather than only "precision dropped".
    """
    code: str
    reason: str  # negated | prior_visit | planned | home_program | self_corrected


@dataclass(frozen=True)
class SyntheticSample:
    id: int
    patient_name: str
    diagnosis: str
    visit_type: str
    date: str
    transcript: str
    body_part: str
    icd_codes: tuple[str, ...]
    icd_descriptions: dict[str, str]
    interventions: tuple[GoldIntervention, ...]
    distractors: tuple[GoldDistractor, ...]
    total_timed_minutes: int
    expected_units: int
    expected_units_ama: int
    synth: dict = field(default_factory=dict)
    #: The ICD rule's formal clinical label. `diagnosis` holds what the therapist
    #: SAID (often a loose paraphrase, deliberately — see DIAGNOSIS_PARAPHRASES);
    #: this is what a roster or chart header should display. A roster reading
    #: "Worn discs" looks like a data-entry error, not like demo data.
    diagnosis_formal: str = ""

    @property
    def cpt_codes(self) -> tuple[str, ...]:
        """Derived, never drawn separately — so the field Tier A already scores stays exactly
        consistent with the richer intervention labels."""
        return tuple(dict.fromkeys(i.code for i in self.interventions if i.billable))

    def to_record(self) -> dict:
        """One JSONL line in the corpus schema (evals/data/README.md)."""
        return {
            "id": self.id,
            "patient_name": self.patient_name,
            "diagnosis": self.diagnosis,
            "visit_type": self.visit_type,
            "date": self.date,
            "transcript": self.transcript,
            "cpt_codes": [
                {"code": c, "description": banks.INTERVENTION_LABEL.get(c, "")}
                for c in self.cpt_codes
            ],
            "body_part": self.body_part,
            "icd_codes": [
                {"code": c, "description": self.icd_descriptions.get(c, "")}
                for c in self.icd_codes
            ],
            "interventions": [asdict(i) for i in self.interventions],
            "distractors": [asdict(d) for d in self.distractors],
            "total_timed_minutes": self.total_timed_minutes,
            "expected_units": self.expected_units,
            "expected_units_ama": self.expected_units_ama,
            "synth": self.synth,
        }


# ==================================================================================
# Drawing the ground truth
# ==================================================================================

def _minute_split(rng: random.Random, target_units: int, n: int, complexity: str) -> list[int]:
    """Per-treatment minutes whose TOTAL lands in the band for `target_units`.

    At high complexity the total is pushed onto a band EDGE (53 or 67 for 4 units), because an
    off-by-one in `units_for_minutes` is invisible mid-band and obvious at the boundary. That is
    the main thing generating buys over hand-writing cases.
    """
    low = 8 + 15 * (target_units - 1) if target_units else 0
    high = low + 14
    if not target_units:
        return [rng.choice((3, 5, 7))] * n if n else []

    if complexity == "high" and rng.random() < 0.5:
        total = rng.choice((low, high))            # sit exactly on the boundary
    else:
        total = rng.randint(low, high)

    if n == 1:
        return [total]

    # Jitter around an even split so durations look like a real session (18/22/15) rather than
    # a suspicious 14/14/14/14, then give the remainder to one part so they sum to `total`
    # exactly. The floor of 5 keeps every duration clinically plausible.
    floor = 5
    slack = total - floor * n
    if slack <= 0:
        return [max(floor, total // n)] * n
    parts = [floor] * n
    for _ in range(slack):
        parts[rng.randrange(n)] += 1
    return parts


def _diverging_split(rng: random.Random, n: int) -> list[int]:
    """Minutes where CMS substitution and the AMA rule of eights genuinely disagree.

    Each part earns its own AMA unit (8-14 min) but they sum sub-additively under CMS: two
    8-minute services are 1 CMS unit and 2 AMA units. Cadence must report both, so the corpus
    needs cases that prove it does.
    """
    return [rng.randint(8, 14) for _ in range(n)]


def _spoken_part(body_part: str) -> str:
    return banks.SPOKEN_PART.get(body_part, body_part)


def _draw_diagnosis(rng: random.Random, body_part: str):
    """Draw a diagnosis and the phrase the therapist will SAY for it.

    The phrase is drawn from `banks.DIAGNOSIS_PARAPHRASES` a fraction of the time — real wordings
    the cue table does NOT know. Before that, this did `rng.choice(rule.cues)`, straight out of the
    extractor's own cue list, which made ICD recall 100% by construction and measured nothing.
    The gold code is unchanged either way, so a paraphrase the extractor misses is a REAL miss.
    """
    rules = tables.ICD_BY_BODY_PART[body_part]
    rule = rng.choice(rules)
    paraphrases = banks.DIAGNOSIS_PARAPHRASES.get((body_part, rule.cues[0]), ())
    used_paraphrase = bool(paraphrases) and rng.random() < banks.DIAGNOSIS_PARAPHRASE_RATE
    phrase = rng.choice(paraphrases) if used_paraphrase else rng.choice(rule.cues)
    if body_part in banks.MIDLINE_PARTS or not rule.lateralized:
        # A midline region, or a condition ICD-10-CM codes the same either way. Speaking a side
        # here would be unnatural AND would train the extractor on a laterality habit real spine
        # dictation doesn't have.
        side = None
    else:
        # "bilateral" is drawn rarely: a real case (and it exercises the two-codes-for-one-rule
        # path) but an unrepresentative share of real visits.
        side = rng.choices(("right", "left", "bilateral", None), weights=(45, 40, 5, 10))[0]
    codes = rule.code_for(side)
    return rule, phrase, side, codes, used_paraphrase


def generate_sample(index: int, *, body_part: str, note_type: str, complexity: str,
                    seed: int, target_units: int = 4) -> SyntheticSample:
    """One fully-labeled synthetic sample. Deterministic in every argument."""
    rng = random.Random(
        f"v{GENERATOR_VERSION}|{body_part}|{note_type}|{complexity}|{seed}|{index}"
    )
    profile = _PROFILE[complexity]
    pool = banks.TREATMENTS_BY_BODY_PART[body_part]

    rule, dx_phrase, side, icd_codes, dx_paraphrase = _draw_diagnosis(rng, body_part)

    n_timed = rng.randint(*profile["timed"])
    timed_codes = rng.sample(pool["timed"], min(n_timed, len(pool["timed"])))
    diverging = complexity == "high" and rng.random() < 0.35
    minutes = (_diverging_split(rng, len(timed_codes)) if diverging
               else _minute_split(rng, target_units, len(timed_codes), complexity))

    interventions = [
        GoldIntervention(code=c, label=banks.INTERVENTION_LABEL[c], minutes=m, timed=True)
        for c, m in zip(timed_codes, minutes)
    ]
    if rng.random() < profile["untimed"]:
        u = rng.choice(pool["untimed"])
        # minutes=None: an untimed modality's duration is irrelevant to units, and leaving it
        # unstated is both realistic and the stricter test — a scorer must not expect one.
        interventions.append(GoldIntervention(code=u, label=banks.INTERVENTION_LABEL[u],
                                              minutes=None, timed=False))

    used = {i.code for i in interventions}
    candidates = [c for c in (*pool["timed"], *pool["untimed"], *pool["implausible"])
                  if c not in used]
    rng.shuffle(candidates)
    reasons = ["negated", "prior_visit", "planned", "home_program"]
    rng.shuffle(reasons)
    distractors: list[GoldDistractor] = []
    for reason, code in zip(reasons[:profile["distractors"]], candidates):
        distractors.append(GoldDistractor(code=code, reason=reason))
    # A self-correction needs a code to be corrected AWAY from, so it can only be added once a
    # real intervention exists to correct TO.
    corrected_from = None
    if complexity == "high" and interventions and len(candidates) > len(distractors):
        corrected_from = candidates[len(distractors)]
        distractors.append(GoldDistractor(code=corrected_from, reason="self_corrected"))

    if note_type == "initial":
        # An eval bills 97161/2/3 (a clinician JUDGEMENT call, surfaced not auto-assigned), never
        # treatment minutes — and the rendered dictation states no treatments at all.
        interventions, distractors, corrected_from = [], [], None

    total_timed = sum(i.minutes for i in interventions if i.timed and i.minutes)
    per_code = {i.code: i.minutes for i in interventions if i.timed and i.minutes}

    # Identity is drawn ONCE and shared between the record fields and the spoken opener. Drawing
    # them separately let the transcript greet a different patient, on a different visit type,
    # than the record claimed — a contradiction that would confuse the note model downstream and
    # has nothing to do with what this corpus measures.
    patient_name = rng.choice(banks.PATIENT_NAMES)
    visit_type = rng.choice(banks.VISIT_TYPES[note_type])
    voice = rng.choice(banks.VOICES)

    dx_formal = (f"{side.capitalize()} {rule.label}" if side and rule.lateralized else rule.label)
    transcript = _render(
        rng, body_part=body_part, complexity=complexity, dx_phrase=dx_phrase, side=side,
        interventions=interventions, distractors=distractors, corrected_from=corrected_from,
        total_timed=total_timed, patient_name=patient_name, visit_type=visit_type, voice=voice,
        note_type=note_type, dx_formal=dx_formal,
    )

    return SyntheticSample(
        id=ID_BLOCKS[body_part] + index,
        patient_name=patient_name,
        diagnosis=(f"{side.capitalize()} {dx_phrase}" if side else dx_phrase.capitalize()),
        diagnosis_formal=(f"{side.capitalize()} {rule.label}" if side and rule.lateralized
                          else rule.label),
        visit_type=visit_type,
        date=(_BASE_DATE + timedelta(days=index * 3)).isoformat(),
        transcript=transcript,
        body_part=body_part,
        icd_codes=tuple(icd_codes),
        icd_descriptions={c: rule.label for c in icd_codes},
        interventions=tuple(interventions),
        distractors=tuple(distractors),
        total_timed_minutes=total_timed,
        expected_units=units_for_minutes(total_timed),
        expected_units_ama=allocate_units(per_code, method=AMA_RULE_OF_EIGHTS).total_units,
        synth={
            "generator_version": GENERATOR_VERSION,
            "seed": f"v{GENERATOR_VERSION}|{body_part}|{note_type}|{complexity}|{seed}|{index}",
            "complexity": complexity,
            "note_type": note_type,
            "target_units": target_units,
            # True when the dictation speaks a wording the cue table does not know.
            # Lets a scorer separate "the extractor cannot read this phrasing" from
            # "the extractor is broken".
            "diagnosis_paraphrased": dx_paraphrase,
            "cms_units": allocate_units(per_code, method=CMS_SUBSTITUTION).total_units,
        },
    )


# ==================================================================================
# Rendering the dictation
# ==================================================================================

def _fillers(rng: random.Random, text: str, rate: float) -> str:
    """Sprinkle MedASR-style disfluency between clauses, at a complexity-scaled rate."""
    if rate <= 0:
        return text
    out = []
    for sentence in text.split(". "):
        if sentence and rng.random() < rate:
            sentence = rng.choice(banks.FILLERS) + ", " + sentence[0].lower() + sentence[1:]
        out.append(sentence)
    return ". ".join(out)


def _treatment_sentence(rng: random.Random, item: GoldIntervention, complexity: str,
                        total_timed: int, allow_bare: bool, body_part: str) -> tuple[str, bool]:
    """One treatment as speech. Returns (sentence, used_fraction)."""
    cue = rng.choice(banks.INTERVENTION_SPOKEN[item.code])
    detail = rng.choice(banks.technique_detail(body_part, item.code))

    if item.minutes is None:
        return (f"We also did {cue}" + (f", {detail}" if detail else ""), False)

    # A fraction is only renderable when a session total exists to state alongside it, and only
    # when it divides cleanly — otherwise the gold minutes and the spoken fraction disagree.
    if complexity == "high" and total_timed and rng.random() < 0.15:
        for name, share in banks.FRACTIONS:
            if total_timed and round(total_timed * share) == item.minutes:
                return (f"{cue} for {name} of the session", True)

    if allow_bare and rng.random() < 0.5:
        frame = rng.choice(banks.MINUTES_FRAMES["bare"])
        return (frame.format(cue=cue, spoken=spoken_number(item.minutes)), False)

    frame = rng.choice(banks.MINUTES_FRAMES["explicit"])
    return (frame.format(cue=cue, spoken=spoken_number(item.minutes), detail=detail), False)


def _render(rng: random.Random, *, body_part, complexity, dx_phrase, side, interventions,
            distractors, corrected_from, total_timed, patient_name, visit_type, voice,
            note_type="followup", dx_formal="") -> str:
    profile = _PROFILE[complexity]
    side_word = {"bilateral": "bilateral", None: ""}.get(side, side or "")

    parts = [rng.choice(banks.OPENERS).format(
        visit=visit_type, name=patient_name.split()[0],
        side=side_word, part=_spoken_part(body_part)).replace("  ", " ")]

    dx_spoken = f"{side} {dx_phrase}" if side and side != "bilateral" else (
        f"bilateral {dx_phrase}" if side == "bilateral" else dx_phrase)
    parts.append(rng.choice(banks.DIAGNOSIS_FRAMES).format(dx=dx_spoken) + ".")

    if note_type == "initial":
        # An evaluation is intake, not a treatment log — no "last visit", no per-treatment
        # minutes. `evals/synth/intake.py` renders it field by spoken field, matching the
        # ~1,000-1,300 word ScopeHealth-style dictations in docs/synthetic-longform-inputs.md.
        # It replaces the opener too, because a real eval opens with the patient's age and the
        # referring diagnosis rather than a follow-up greeting.
        return _fillers(rng, intake.render(rng, body_part=body_part, voice=voice, side=side,
                                           dx_phrase=dx_spoken, dx_formal=dx_formal),
                        _PROFILE[complexity]["filler"])

    subjective = banks.SUBJECTIVE + banks.SUBJECTIVE_BY_PART.get(body_part, ())
    parts.append(rng.choice(subjective).format(part=_spoken_part(body_part), **voice))

    # Treatments in RANDOM order — a real dictation does not follow the note's section order, and
    # an extractor that quietly relied on ordering would pass a sorted corpus and fail in the room.
    shuffled = list(interventions)
    rng.shuffle(shuffled)

    sentences: list[str] = []
    used_fraction = False
    for item in shuffled:
        sentence, frac = _treatment_sentence(
            rng, item, complexity, total_timed, rng.random() < profile["bare"], body_part)
        used_fraction = used_fraction or frac
        sentences.append(sentence)
    if sentences:
        parts.append("Today we did " + sentences[0] + "." if not sentences[0].lower().startswith("we")
                     else sentences[0].capitalize() + ".")
        for s in sentences[1:]:
            parts.append("Then " + s + "." if not s.lower().startswith("we") else s.capitalize() + ".")

    # The session total is only stated when a fraction needs it — stating it unconditionally
    # would hand the extractor a free anchor it will not have in the room.
    if used_fraction and total_timed:
        parts.append(rng.choice(banks.SESSION_TOTAL_FRAMES).format(spoken=spoken_number(total_timed)))

    for d in distractors:
        cue = rng.choice(banks.INTERVENTION_SPOKEN[d.code])
        if d.reason == "self_corrected":
            corrected = rng.choice(banks.INTERVENTION_SPOKEN[interventions[0].code])
            parts.append(rng.choice(banks.DISTRACTOR_FRAMES["self_corrected"]).format(
                cue=cue, corrected=corrected, **voice))
        else:
            parts.append(rng.choice(banks.DISTRACTOR_FRAMES[d.reason]).format(cue=cue, **voice))

    parts.append(rng.choice(banks.CLOSERS).format(**voice))
    text = " ".join(p.strip() for p in parts if p and p.strip())
    return _fillers(rng, text, profile["filler"])


def generate_corpus(*, body_part: str, note_type: str, count: int, complexity: str,
                    seed: int, target_units: int = 4) -> list[SyntheticSample]:
    """`count` samples. Sample N depends only on N, so growing a corpus never rewrites it."""
    if body_part not in banks.TREATMENTS_BY_BODY_PART:
        raise ValueError(f"no phrase bank for body part {body_part!r}; "
                         f"known: {sorted(banks.TREATMENTS_BY_BODY_PART)}")
    if note_type not in NOTE_TYPES:
        raise ValueError(f"note_type must be one of {NOTE_TYPES}, got {note_type!r}")
    if complexity not in COMPLEXITIES:
        raise ValueError(f"complexity must be one of {COMPLEXITIES}, got {complexity!r}")
    return [
        generate_sample(i, body_part=body_part, note_type=note_type, complexity=complexity,
                        seed=seed, target_units=target_units)
        for i in range(1, count + 1)
    ]
