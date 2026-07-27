"""Python port of cadence-prototype.html's buildPrompt() (lines 429-471)."""

import re
from dataclasses import dataclass

from app.generate.forms import CARRY_SECTION_LABELS, FormSpec
from app.generate.rules import (
    MODE_RULE_OMIT,
    MODE_RULE_REQUIRE,
    OUTPUT_FORMAT,
    WRITING_RULES_LEAD,
    WRITING_RULES_TAIL,
)

# Vocalized hesitation sounds that show up in raw speech-to-text but are never a
# meaningful clinical word. These are stripped from the dictation BEFORE it reaches
# the model, so a generated note can't echo them no matter how the model behaves --
# the model-independent half of the "notes must read clean, not spoken" fix (the
# WRITING RULES prompt is the other half, and also handles filler that DOES carry
# meaning in other contexts: like, so, you know, right, well, actually).
#
# Deliberately conservative: only tokens that are never a real clinical word appear
# here, so this can never delete content. Notably EXCLUDED, despite sounding like
# filler, because they collide with real PT/clinical usage: "mm" (millimeters),
# "er"/"ER" (external rotation; emergency room). Those are left for the prompt.
_FILLER_WORDS = [
    "um", "umm", "ummm", "uh", "uhh", "uhhh", "uhm",
    "erm", "ermm", "hmm", "hmmm", "mmhmm", "mhm",
]
# Match a filler only as a standalone token (not inside "summer", "number", "her"),
# case-insensitively, and swallow one trailing comma + surrounding spaces it leaves.
_FILLER_RE = re.compile(
    r"(?i)(?<![\w'])(?:" + "|".join(_FILLER_WORDS) + r")(?![\w'])[ \t]*,?"
)

# --- Transcript-export artifacts -------------------------------------------------
# MedASR itself emits none of these, but a clinician may PASTE a transcript made by an
# outside tool (Otter/Zoom/Teams exports) into the dictation box, which carries junk that
# only distracts the note model: timestamps, diarization speaker labels, and non-lexical
# ASR annotations. All are stripped deterministically here, at the same single chokepoint
# as the vocalized-pause fillers. Every pattern below is deliberately narrow so it can
# never remove a real clinical value (see the per-pattern collision notes).

# Non-lexical ASR annotations, a fixed vocabulary only (never "any bracketed text", so our
# own [[NEEDS: ...]] / [[CPT: ...]] output markers and any real bracketed aside are safe):
# [inaudible], (unintelligible), [BLANK_AUDIO], [background noise], [laughter]...
_ASR_ANNOTATIONS = [
    "inaudible", "unintelligible", "indiscernible", "crosstalk", "cross talk",
    "background noise", "background", "noise", "silence", "music", "laughter",
    "laughs", "laughing", "pause", "long pause", "coughing", "cough", "applause",
    "blank_audio", "blank audio", "no audio", "static",
]
_ANNOTATION_RE = re.compile(
    r"(?i)[\[(]\s*(?:" + "|".join(a.replace(" ", r"\s+") for a in _ASR_ANNOTATIONS) + r")\s*[\])]"
)
# Bracketed / parenthesized timestamps: [00:12:34], (1:05), [12:34].
_BRACKET_TS_RE = re.compile(r"[\[(]\s*\d{1,2}:\d{2}(?::\d{2})?(?:[.,]\d+)?\s*[\])]")
# Bare HH:MM:SS (two colons) never occurs in clinical dictation -> always a timestamp.
_HMS_RE = re.compile(r"(?<!\d)\d{1,2}:\d{2}:\d{2}(?:[.,]\d+)?(?!\d)")
# A bare MM:SS / HH:MM ONLY at the very start of a line = a leading transcript timestamp.
# Mid-sentence one-colon times (e.g. a dosing time "meds at 8:00") are deliberately kept,
# and minutes must be exactly two digits, so a "2:1" ratio is never touched.
_LEADING_TS_RE = re.compile(r"(?m)^[ \t]*\d{1,2}:\d{2}(?::\d{2})?(?:[.,]\d+)?[ \t]+")
# Diarization speaker labels at line start, from a fixed vocabulary (NOT arbitrary
# "Word:", so clinical labels like "Assessment:" or a plan line "PT:" are never removed):
# "Speaker 1:", "SPEAKER_02 -", "Therapist:", "Patient –".
_SPEAKER_RE = re.compile(
    r"(?im)^[ \t]*(?:speaker[ _]?\d+|spk[ _]?\d+|therapist|clinician|provider|doctor|"
    r"patient|client|caregiver|interviewer|examiner)\s*[:\-–]\s*"
)


def strip_transcript_artifacts(text: str) -> str:
    """Remove pasted-transcript junk (timestamps, speaker labels, [inaudible]-type
    annotations) that carries no clinical meaning. Narrow by construction — see the module
    regexes — so it can only ever delete transcript scaffolding, never a stated value."""
    out = _ANNOTATION_RE.sub("", text)
    out = _BRACKET_TS_RE.sub("", out)
    out = _HMS_RE.sub("", out)
    out = _LEADING_TS_RE.sub("", out)
    out = _SPEAKER_RE.sub("", out)
    return out


def clean_dictation(text: str) -> str:
    """Strip unambiguous vocalized-pause fillers (um, uh, hmm...) AND pasted-transcript
    artifacts (timestamps, speaker labels, [inaudible]-type annotations) from a raw
    dictation, then tidy the whitespace/punctuation they leave behind, so the model never
    sees -- and so can never copy into the note -- speech-to-text hesitation noise or
    transcript scaffolding. Only unambiguous junk is removed; meaning-bearing words are
    left for the prompt to clean up.
    """
    if not text:
        return text
    out = _FILLER_RE.sub("", text)
    out = strip_transcript_artifacts(out)
    out = re.sub(r"\s+([,.;:!?])", r"\1", out)   # " ," / " ." artifacts -> ","/"."
    out = re.sub(r",\s*,", ", ", out)            # doubled commas from adjacent fillers
    out = re.sub(r"(^|[.!?]\s+),\s*", r"\1", out)  # stray comma opening a sentence
    out = re.sub(r"[ \t]{2,}", " ", out)         # collapse runs of spaces
    out = re.sub(r"[ \t]+\n", "\n", out)
    out = re.sub(r"\n{3,}", "\n\n", out)         # collapse blank lines left by stripped lines
    return out.strip()


NO_PRIOR_MESSAGE = (
    "No prior note on file: for any [carry forward] section, write the body as "
    "[[NEEDS: prior value required]] and do NOT tag that section's heading "
    "[[CARRIED FORWARD]] — there is nothing to carry forward yet."
)


@dataclass
class PatientContext:
    name: str
    sub: str  # "MRN ... · DOB ... · condition" display line — never parsed for age/DOB


def render_prior_block(form: FormSpec, snapshot: dict | None, use_prior: bool) -> str:
    """snapshot is a carry_snapshots row (as a dict) or None. Mirrors the prototype's
    `usePrior = form.carry && priorOn && p.prior` ternary: a carry-enabled form with
    no usable snapshot (missing, or the clinician toggled it off) still gets told to
    flag every carry-forward section, rather than silently omitting the instruction.
    """
    if not form.carry:
        return ""
    if not (use_prior and snapshot):
        return NO_PRIOR_MESSAGE

    lines = [
        "PRIOR NOTE (carry forward the indicated sections; "
        "update only if today's summary changes them):"
    ]
    if snapshot.get("precautions"):
        lines.append(f"Precautions: {snapshot['precautions']}")
    if snapshot.get("functional_status"):
        lines.append(
            f"Functional Status (carry forward unless changed today): "
            f"{snapshot['functional_status']}"
        )
    if snapshot.get("short_term_goals"):
        lines.append(
            f"Short-Term Goals (carry forward; mark MET if achieved):\n"
            f"{snapshot['short_term_goals']}"
        )
    if snapshot.get("long_term_goals"):
        lines.append(
            f"Long-Term Goals (carry forward; mark MET if achieved):\n"
            f"{snapshot['long_term_goals']}"
        )
    return "\n".join(lines)


def _carry_labels_rule(form: FormSpec) -> str:
    labels = CARRY_SECTION_LABELS.get(form.id)
    if not labels:
        return ""
    joined = ", ".join(labels)
    return (
        f"- The ONLY sections in this note that may ever be tagged [[CARRIED FORWARD]] "
        f"are: {joined}. Every other section — every treatment/CPT section, Pain, "
        f"Vitals, Response to Treatment, and the Plan — is written fresh from today's "
        f"dictation and must NEVER carry that tag, whether or not a prior note is on file."
    )


def build_prompt(
    form: FormSpec,
    patient: PatientContext,
    summary: str,
    prior_block: str,
    extra_info: str | None = None,
) -> str:
    # The dictation is a raw speech-to-text transcript from MedASR: strip unambiguous
    # spoken fillers (um, uh, hmm...) here, deterministically, so the note can never
    # echo them regardless of the model. Applied to both the summary and the extra
    # gap-filling details, and this is the single chokepoint for guided-mode text too.
    summary = clean_dictation(summary)
    extra_info = clean_dictation(extra_info)
    mode_rule = MODE_RULE_REQUIRE if form.mode == "require" else MODE_RULE_OMIT
    extra_block = (
        f'\nADDITIONAL DETAILS THE THERAPIST JUST PROVIDED (use to fill gaps they cover):\n'
        f'"""{extra_info}"""'
        if extra_info
        else ""
    )
    carry_labels_rule = _carry_labels_rule(form)
    tail = WRITING_RULES_TAIL if not carry_labels_rule else f"{carry_labels_rule}\n{WRITING_RULES_TAIL}"

    parts = [
        f'You are a documentation assistant for a physical therapist. Convert the '
        f'therapist\'s spoken summary into a complete, professional "{form.name}".',
        f"PATIENT: {patient.name}. {patient.sub}.",
        f'NOTE STRUCTURE FOR "{form.name}":\n{form.spec}',
        prior_block,
        f'THERAPIST\'S DICTATION OF TODAY\'S SESSION:\n"""{summary}"""{extra_block}',
        f"{WRITING_RULES_LEAD}\n- {mode_rule}\n{tail}",
        OUTPUT_FORMAT,
    ]
    return "\n\n".join(p for p in parts if p)


def build_revise_prompt(form: FormSpec, note_text: str, instruction: str) -> str:
    """Prompt to apply a clinician's plain-language edit to an already-generated note, re-emitting the
    WHOLE note in the same structure. The clinician stays in control — apply only what's asked, and
    never fabricate a value (same non-negotiable as first-pass generation)."""
    return "\n\n".join([
        f'You are revising an already-written "{form.name}" for a physical therapist. Apply the '
        f"clinician's requested change and output the COMPLETE revised note — every section, not just "
        f"the changed part.",
        f'CLINICIAN\'S REQUESTED CHANGE:\n"""{clean_dictation(instruction)}"""',
        f'CURRENT NOTE:\n"""{note_text}"""',
        "RULES:\n"
        "- Apply ONLY the requested change; keep every other section, field, and value exactly as written.\n"
        "- NEVER invent a clinical value (minutes, vitals, ROM, MMT, pain levels, measurements, dates). If "
        "the change needs a value that was not given, write [[NEEDS: ...]] instead of guessing.\n"
        "- Keep the same section headings and overall structure. When asked to shorten or reword, preserve "
        "every stated clinical fact.",
        OUTPUT_FORMAT,
    ])
