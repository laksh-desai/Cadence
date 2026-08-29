"""Python port of cadence-prototype.html's buildPrompt() (lines 429-471)."""

import re
from dataclasses import dataclass

from app.generate.forms import CARRY_SECTION_LABELS, FormSpec, spec_section_labels
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


def _section_roster_rule(form: FormSpec) -> str:
    """MEASURED HARMFUL — NOT USED. Kept so the negative result stays with the idea.

    Enabling this (together with an extra template section, so the two are confounded and neither
    is individually convicted) took Follow-Up section coverage from **93% to 47%** over the same 5
    real records: three of five notes stopped after the treatment sections, with no Plan, no Goals
    and no Functional Status. Value capture rose 57% -> 65% at the same time, which is the trap —
    a note missing its Plan is not a better note for containing more measurements.

    The plausible mechanism, untested: naming the required sections right after the outline gives
    the model a short, concrete checklist to satisfy, and it satisfies the beginning of it and
    stops. Telling a 4B "do not stop early" appears to do less than telling it, implicitly, that
    there is a list it can finish.

    Do not re-enable without re-measuring, and change ONE thing at a time when you do — running
    this and a template edit together is why neither can be individually convicted here.

    Original intent below, still accurate as a description of the problem it was aimed at.

    Name the sections the template declares, and name the LAST one.

    Two measured failures, one cause. The prompt says `NOTE STRUCTURE FOR "Follow-Up Visit":` and
    the spec's own first line is `FOLLOW-UP VISIT — skilled interim visit…`, so the title appears
    twice in a row and the model turns it into a section heading (3 of 4 real notes). That
    consumes the real first section, and from there the whole note runs one section short — which
    is why those same notes also STOP EARLY, before Plan and the goals.
    That is worth stating plainly because it rules out the obvious explanation: the short notes
    used 7-13% of `num_predict`, so nothing was truncated. The model finished, one section adrift.

    The roster is DERIVED from the template via `spec_section_labels`, never hand-written, so it
    cannot drift from the outline it describes. It says the two things the failures need said: do
    not invent a section for the title, and here is the section you must not stop before.

    Deterministic repairs (rule 32) still clean up afterwards regardless — per rule 19, a prompt
    lowers the FREQUENCY of a failure class, never its risk.
    """
    labels = spec_section_labels(form.id)
    if not labels:
        return ""
    return "\n".join([
        'REQUIRED SECTIONS — every one of these must appear as its own "## " heading, in this '
        f"order: {', '.join(labels)}.",
        "- Do NOT create a section for the note's TITLE. The title is not a section.",
        f'- The final section is "{labels[-1]}" — write the whole note through to it; do not '
        "stop early.",
        "- Where the outline calls for a section per treatment performed, insert those in the "
        "place it indicates; that is the only addition allowed.",
    ])


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
        # `_section_roster_rule(form)` is deliberately NOT called here. It was measured and it made
        # the problem worse — see that function's docstring. The function is kept, unused, so the
        # negative result stays attached to the idea rather than being rediscovered.
        prior_block,
        f'THERAPIST\'S DICTATION OF TODAY\'S SESSION:\n"""{summary}"""{extra_block}',
        f"{WRITING_RULES_LEAD}\n- {mode_rule}\n{tail}",
        OUTPUT_FORMAT,
    ]
    return "\n\n".join(p for p in parts if p)


# --- "Ask for changes": choosing what to re-write ----------------------------------
#
# The whole-note rewrite below is the fallback, not the default, because asking a 4B model to
# re-emit ~2,000 tokens in order to change one line has three costs the clinician feels: most of
# the output budget goes on copying so the edit itself gets lost; untouched sections come back
# subtly reworded; and it takes minutes. Scoping the rewrite to the section the clinician actually
# named fixes all three at once, and makes collateral drift STRUCTURALLY impossible rather than
# merely discouraged — the other sections are carried across byte-identical and never shown to the
# model as something to reproduce.
#
# Selection is deterministic. A model deciding which section to edit would just move the guesswork
# somewhere less visible.
_REVISE_STOPWORDS = frozenset({
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "at", "for", "with", "by", "is", "are",
    "was", "were", "be", "it", "this", "that", "these", "those", "section", "sections", "please",
    "note", "make", "change", "should", "would", "could", "i", "we", "she", "he", "they",
})

#: Instructions that operate on the note's SHAPE rather than one section's content. Merging,
#: reordering, or moving a section changes which sections exist and in what order, which a
#: per-section splice cannot express — so these fall back to the whole-note rewrite.
_STRUCTURAL_INSTRUCTION_CUES = (
    "merge", "combine", "consolidate", "reorder", "re-order", "move ", "swap", "rearrange",
    "sort ", "to the top", "to the bottom", "at the top", "at the end", "order of",
    "split ", "separate into", "renumber",
)


def _significant_words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", (text or "").lower())
            if w not in _REVISE_STOPWORDS and len(w) > 1}


def is_structural_instruction(instruction: str) -> bool:
    low = (instruction or "").lower()
    return any(cue in low for cue in _STRUCTURAL_INSTRUCTION_CUES)


def select_revise_sections(sections: list[dict], instruction: str) -> list[str]:
    """Headings the instruction is talking about, or [] when it is not clearly about specific ones.

    An empty list means "fall back to the whole-note rewrite" — the safe direction. Guessing one
    section wrong is worse than rewriting everything: the clinician's change silently lands in the
    wrong place, or appears not to have happened at all.

    Scored by how much of a HEADING the instruction contains, not the reverse, so a long
    instruction cannot drag in unrelated sections. "Pain at rest should be 3 out of 10" covers all
    of "Pain - At Rest" (pain, rest) but only half of "Pain - With Movement" (pain), and the
    margin is what disambiguates them.
    """
    words = _significant_words(instruction)
    if not words:
        return []
    scored: list[tuple[float, str]] = []
    for s in sections:
        heading = (s.get("heading") or "").strip()
        tokens = _significant_words(heading)
        if not tokens:
            continue
        scored.append((len(tokens & words) / len(tokens), heading))
    if not scored:
        return []
    best = max(score for score, _ in scored)
    # A partial match is a guess. Require the instruction to name the WHOLE heading.
    if best < 1.0:
        return []
    winners = [h for score, h in scored if score >= 1.0]
    # Several sections matching completely is either a real duplicate-heading case (a merge, which
    # is structural and handled above) or an ambiguous single-word heading. Cap it so one request
    # can never trigger a near-whole-note rewrite through the "scoped" path.
    return winners if len(winners) <= 3 else []


def build_scoped_revise_prompt(form: FormSpec, sections: list[dict], targets: list[str],
                               instruction: str) -> str:
    """Ask the model to re-write ONLY the named sections. Everything else is spliced back
    untouched by the caller, so it never enters the prompt as something to copy."""
    wanted = {t.strip().lower() for t in targets}
    chosen = [s for s in sections if (s.get("heading") or "").strip().lower() in wanted]
    others = [(s.get("heading") or "").strip() for s in sections
              if (s.get("heading") or "").strip().lower() not in wanted]
    block = "\n\n".join(f"## {s['heading']}\n{s.get('body', '')}" for s in chosen)
    plural = "s" if len(chosen) != 1 else ""
    # ORDER IS LOAD-BEARING, and the first version of this prompt got it wrong. It opened with the
    # formatting rules and buried "apply the requested change" as a second bullet, and it offered
    # an escape hatch ("if the change does not affect a section, output it as given"). Measured on
    # the real model, the 4B took that path every time: it echoed the section back verbatim, so a
    # revision that ran in six seconds changed nothing. The change now comes LAST, phrased as the
    # imperative, with an explicit statement that the body must come back different — and the
    # escape hatch is gone, because the caller only ever sends sections the change DOES affect.
    # Two more things measured out of this prompt, both of which look like good ideas on paper:
    #
    #   * A LIST OF THE OTHER SECTION NAMES, given as "context only, do not output". The 4B echoed
    #     it verbatim into its answer. It was there to stop the model duplicating other sections'
    #     content into this one, which was a speculative worry; the echoing was real and measured.
    #   * ENDING ON THE INSTRUCTION. A prompt that ends with prose gets continued like prose —
    #     the model replayed the input section and carried on down the page. Ending on an explicit
    #     "REVISED SECTION:" cue turns the task from "continue this document" into "fill this in",
    #     which is the shape small instruct models actually follow.
    #
    # `others` is still accepted so the signature does not churn, and so the reason it is unused
    # is recorded where the next person would otherwise re-add it.
    _ = others
    return "\n".join([
        f'Revise one section of a physical therapist\'s "{form.name}".',
        "",
        f"CURRENT SECTION{plural.upper()}:",
        block,
        "",
        f'CHANGE THE CLINICIAN ASKED FOR:\n"""{clean_dictation(instruction)}"""',
        "",
        "RULES:",
        f"- Output the section{plural} with the SAME '## ' heading, then the new body. Nothing "
        "else — no preamble, no explanation, no other sections, no rules.",
        "- The new body MUST DIFFER from the current one. Returning the same text is not an answer.",
        "- Change ONLY what was asked; every other fact stays exactly as it is.",
        "- NEVER invent a clinical value (minutes, vitals, ROM, MMT, pain levels, measurements, "
        "dates). If the change needs a value that was not given, write [[NEEDS: ...]] instead.",
        "- To delete the section, output its heading and a body of exactly [[DELETE]].",
        "- Keep any [[NEEDS: ...]] and [[CPT: ...]] markers unless the change is about them.",
        "",
        f"REVISED SECTION{plural.upper()}:",
    ])


def build_revise_prompt(form: FormSpec, note_text: str, instruction: str) -> str:
    """Prompt to apply a clinician's plain-language edit to an already-generated note, re-emitting the
    WHOLE note in the same structure. The clinician stays in control — apply only what's asked, and
    never fabricate a value (same non-negotiable as first-pass generation).

    The FALLBACK path — used when `select_revise_sections` cannot confidently name the target, or
    when the instruction is structural (merge/reorder/move). See that function for why scoping is
    preferred when it applies.
    """
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
