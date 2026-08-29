"""Deterministic safety-net corrections applied after parsing the model's output.

MedGemma 4B reliably (not occasionally) violates two prompt rules no amount of
rewording fixed across repeated testing: it tags every section [[CARRIED FORWARD]]
even when told only specific sections qualify, and it invents empty placeholder
sections ("Minutes: 0 / no X performed today") for treatments never mentioned. Since
these are systemic model behaviors rather than one-off mistakes, CLAUDE.md's standing
instruction to fix the underlying logic — not just the prompt — applies: enforce both
rules in code so the contract holds regardless of model compliance.
"""

import re

from app.generate import forms as forms_store
from app.generate.forms import CARRY_SECTION_LABELS

_ZERO_MINUTES_RE = re.compile(r"^\s*Minutes:\s*0\b", re.IGNORECASE)
_CODE_HEADING_RE = re.compile(r"\b(CPT|ICD)\b", re.IGNORECASE)
# A carry-forward form's spec labels its carried sections "<Section> [carry forward]"; the model
# routinely copies that bracketed instruction into the emitted heading ("## Precautions [carry
# forward]"). Strip it so the heading is clean — it never affects the carry logic (which matches the
# label substring either way), only the displayed heading. NOTE: this is the single-bracket spec
# INSTRUCTION, not the double-bracket "[[CARRIED FORWARD]]" OUTPUT tag (that's parsed separately).
_CARRY_INSTRUCTION_RE = re.compile(r"\s*\[\[?\s*carry\s*forward[^\]]*\]\]?", re.IGNORECASE)

# --- Manual muscle test notation ---------------------------------------------
# PTs write strength grades as shorthand ("3+/5", a range as "3+/5 to 4-/5"), but the
# model frequently echoes the spoken long form ("three plus to four minus out of
# five") straight from the dictation. The prompt asks for shorthand; this enforces it
# deterministically since the transform is bounded and unambiguous. Restricted to a
# denominator of five so it can NEVER touch a pain rating ("4 out of 10") or any other
# "out of N" phrase — grades are 0-5 with an optional +/- only.
_GRADE_WORD = {"zero": "0", "one": "1", "two": "2", "three": "3", "four": "4", "five": "5"}
_MOD = {"plus": "+", "minus": "-", "+": "+", "-": "-"}
_GRADE = r"(zero|one|two|three|four|five|[0-5])(?:\s*(plus|minus|\+|-))?"
_OUT_OF_FIVE = r"out\s+of\s+(?:five|5)"
_MMT_RANGE_RE = re.compile(rf"\b{_GRADE}\s+to\s+{_GRADE}\s+{_OUT_OF_FIVE}\b", re.IGNORECASE)
_MMT_SINGLE_RE = re.compile(rf"\b{_GRADE}\s+{_OUT_OF_FIVE}\b", re.IGNORECASE)


def _grade_token(num: str, mod: str | None) -> str:
    n = _GRADE_WORD.get(num.lower(), num)
    m = _MOD.get(mod.lower(), "") if mod else ""
    return f"{n}{m}/5"


# --- Dictated checklist affirmations -----------------------------------------
# The therapist sometimes reads a form aloud as "<fact>, yes". The prompt (rule 17)
# asks the model to convert these to declarative prose, but the 4B model frequently
# echoes the trailing ", yes" verbatim — observed repeated across a whole Fall Risk
# section and duplicated into the Objective Summary on a real generation run. The
# affirmation is safe to drop deterministically ONLY at end-of-statement position:
# "<fact>, yes" means the fact holds, so "<fact>" alone is the clean clinical form.
# The negation half ("<fact>, no") is deliberately NOT handled here — dropping ", no"
# would silently INVERT clinical meaning — so it stays a prompt-only mitigation plus
# clinician review (CLAUDE.md rule 17). Matching only a statement-final ", yes" (before
# a period/newline/end of body) also avoids touching a mid-clause "..., yes, and ...".
_CHECKLIST_YES_RE = re.compile(r",[ \t]*yes[ \t]*(?=[.\n]|$)", re.IGNORECASE)


def strip_checklist_affirmations(sections: list[dict]) -> list[dict]:
    """Drop a statement-final ", yes" the model echoed from a dictated checklist answer
    ("Patient reports fear of falling, yes." -> "Patient reports fear of falling.").
    Bounded to end-of-statement position so it never touches a mid-clause ", yes," and
    never the meaning-inverting ", no".
    """
    out = []
    for s in sections:
        body = _CHECKLIST_YES_RE.sub("", s["body"])
        out.append(s if body == s["body"] else {**s, "body": body})
    return out


def _is_carry_forward_label(form_id: str, heading: str) -> bool:
    """Bidirectional substring match: the model sometimes writes the full verbose
    label as a heading (e.g. "Short-Term Goals [carry forward] each marked..."), but
    for forms whose spec lists Short-Term/Long-Term Goals under one combined "Goals"
    line (soappt), it sometimes collapses them into a single generic "Goals" heading
    instead. A one-directional check misses that collapsed case, so check both ways.
    """
    labels = CARRY_SECTION_LABELS.get(form_id, [])
    heading_lower = heading.lower()
    return any(label.lower() in heading_lower or heading_lower in label.lower() for label in labels)


# The model also writes the literal "[[CARRIED FORWARD]]" tag INTO the body text, not just onto the
# heading line the parser watches — so a non-carry form ends up with a stray tag rendered in every
# section (observed on a real non-carry Initial Evaluation run, #3). Match the tag anywhere.
_CARRY_TAG_RE = re.compile(r"\s*\[\[\s*CARRIED\s+FORWARD\s*\]\]", re.IGNORECASE)


def enforce_carry_tags(form_id: str, sections: list[dict]) -> list[dict]:
    """Keep [[CARRIED FORWARD]] only on sections that are actually carry-forward for this form
    (app.generate.forms.CARRY_SECTION_LABELS), handling BOTH the parsed heading flag and a literal
    tag the model dropped into the body. For an allowed section either signal means carried; for any
    other section the flag is cleared AND the literal body tag is stripped so it never renders.
    """
    out = []
    for s in sections:
        allowed = _is_carry_forward_label(form_id, s["heading"])
        body_has_tag = _CARRY_TAG_RE.search(s["body"]) is not None
        carried = allowed and (bool(s["carried_forward"]) or body_has_tag)
        body = _CARRY_TAG_RE.sub("", s["body"]).rstrip()  # the flag drives rendering, never a body tag
        out.append({**s, "carried_forward": carried, "body": body})
    return out


def drop_unperformed_treatment_sections(sections: list[dict]) -> list[dict]:
    """Drop any section whose body opens with "Minutes: 0" — a reliable signal the
    model invented a placeholder for a treatment that was never performed, rather
    than the (clinically nonsensical) idea that a treatment took zero minutes.
    """
    return [s for s in sections if not _ZERO_MINUTES_RE.match(s["body"])]


def flag_code_sections(sections: list[dict]) -> list[dict]:
    """CPT/ICD-10 code assignment is a billing/coding judgment call, not a
    transcription task — observed the model confidently fabricate both a CPT code
    and an ICD-10 code that didn't match the stated condition, for a dictation that
    never mentioned any code. Replace any CPT/ICD-headed section's body with an
    explicit gap marker rather than ever pass through a model-guessed code.
    """
    out = []
    for s in sections:
        if _CODE_HEADING_RE.search(s["heading"]):
            out.append({**s, "body": "[[NEEDS: code not stated by therapist — clinician to assign]]"})
        else:
            out.append(s)
    return out


# Block-format templates put codes as body FIELD lines ("Medical Diagnosis (ICD-10): M54.5",
# "Treatment Procedures (CPT): 97110") rather than their own heading, so flag_code_sections (which
# matches on the section HEADING) misses a model-authored code there. Observed: the block Initial Eval
# fabricated ICD-10 "M54.5" (low back pain) for a shoulder note and it passed through unflagged. Any
# field line whose LABEL names CPT or ICD gets its value replaced with the same gap marker — the model
# never authors a billing code (rule 12); the clinician assigns it.
_CODE_FIELD_LINE_RE = re.compile(r"(?im)^([^\n:]*\b(?:CPT|ICD(?:-?10)?)\b[^\n:]*:)[^\n]*$")


def flag_code_field_lines(sections: list[dict]) -> list[dict]:
    """Replace the value on any 'CPT'/'ICD'-labelled body field line with the code gap marker (the
    body-line analogue of flag_code_sections, for block-format notes that keep codes as fields)."""
    out = []
    for s in sections:
        body = _CODE_FIELD_LINE_RE.sub(
            lambda m: m.group(1) + " [[NEEDS: code not stated by therapist — clinician to assign]]",
            s["body"],
        )
        out.append(s if body == s["body"] else {**s, "body": body})
    return out


def normalize_strength_grades(sections: list[dict]) -> list[dict]:
    """Rewrite spelled-out manual muscle test grades into clinical shorthand
    ("three plus to four minus out of five" -> "3+/5 to 4-/5"). The range form is
    substituted first so its single trailing "out of five" (which applies to both
    sides) isn't consumed by the single-grade pass.
    """
    out = []
    for s in sections:
        body = _MMT_RANGE_RE.sub(
            lambda m: f"{_grade_token(m.group(1), m.group(2))} to {_grade_token(m.group(3), m.group(4))}",
            s["body"],
        )
        body = _MMT_SINGLE_RE.sub(lambda m: _grade_token(m.group(1), m.group(2)), body)
        out.append(s if body == s["body"] else {**s, "body": body})
    return out


def strip_carry_instruction_headings(sections: list[dict]) -> list[dict]:
    """Remove an echoed "[carry forward]" spec instruction from a section heading
    ("## Precautions [carry forward]" -> "## Precautions"). Cosmetic only — runs before
    enforce_carry_tags, which matches the section label either way."""
    out = []
    for s in sections:
        heading = _CARRY_INSTRUCTION_RE.sub("", s["heading"]).strip()
        out.append(s if heading == s["heading"] else {**s, "heading": heading})
    return out


_ECHO_MARKER_RE = re.compile(r"\[\[[^\]]*\]\]")


def _norm_echo(text: str) -> str:
    t = _ECHO_MARKER_RE.sub("", text)
    t = re.sub(r"[^\w\s]", " ", t.lower())
    return re.sub(r"\s+", " ", t).strip()


def _spec_instruction_phrases(spec: str) -> list[str]:
    """The guidance text after the 'Field — ...' / 'Field: ...' separator on each spec line — meta
    instructions like 'mark MET if today's data shows it achieved'. A body equal to one is an echo."""
    phrases = []
    for line in spec.splitlines():
        parts = re.split(r"\s+[—–]\s+|:\s+", line.strip(), maxsplit=1)
        instr = parts[1] if len(parts) == 2 else line
        n = _norm_echo(instr)
        if len(n.split()) >= 4:
            phrases.append(n)
    return phrases


def strip_spec_instruction_headings(form_id: str, sections: list[dict]) -> list[dict]:
    """Drop a template INSTRUCTION the model copied onto the heading line.

    The heading twin of `flag_template_echo`, which only ever looked at bodies. Observed on real
    Follow-Up generations (2 of 6 notes in a seeded batch):

        ## Precautions — weight-bearing status, range-of-motion limits, and any other precautions
           still in effect.
        ## Summary of Daily Skilled Services — 1-3 sentences on the skilled PT provided today.

    with correct clinical content in the body underneath. `split_folded_headings` cannot help:
    that repair requires an EMPTY body, and it MOVES text rather than deleting it — which is right
    for content on a heading line and wrong here, because this text is not content at all. It is
    the spec's own guidance, and it belongs in neither the heading nor the body.

    Why it matters beyond looking wrong on a note a payer reads: `cpt.code_for_heading` matches
    against the heading, so instruction text carrying an intervention name ("...note the
    therapeutic exercise performed...") could earn a chip for a treatment nobody performed - the
    misfire rule 12's heading-only design exists to prevent.

    Deletion is safe here in a way it is nowhere else in this module ONLY because the removed text
    is matched against the form's own spec, so it is verbatim template boilerplate rather than
    anything the clinician said. A tail that does not match the spec is left completely alone.
    """
    from app.generate.forms import FORMS

    form = FORMS.get(form_id)
    if form is None:
        return sections
    phrases = _spec_instruction_phrases(form.spec)
    if not phrases:
        return sections

    out = []
    for s in sections:
        heading = s.get("heading", "")
        parts = re.split(r"\s+[—–]\s+|\s+--\s+|:\s+", heading.strip(), maxsplit=1)
        if len(parts) != 2:
            out.append(s)
            continue
        label, tail = parts[0].strip(), _norm_echo(parts[1])
        # The label must survive as a real label, and the tail must be the template's own words.
        matched = tail and any(tail == p or tail.startswith(p) or p.startswith(tail)
                               for p in phrases if len(tail.split()) >= 4)
        if matched and label and len(label) <= MAX_LABEL_CHARS:
            out.append({**s, "heading": label})
        else:
            out.append(s)
    return out


def flag_template_echo(form_id: str, sections: list[dict]) -> list[dict]:
    """Replace a section body that just parrots the template's own field INSTRUCTION (the model wrote
    'ambulation distance, assistive device, assist level, and stairs, updated to reflect today' as the
    Functional Status value — real run #15) with an explicit gap marker, so instruction text can never
    masquerade as clinical data. Conservative: only an exact echo (optionally after a short label
    prefix) is flagged, so a real note that merely shares a few words is never touched."""
    from app.generate.forms import FORMS

    form = FORMS.get(form_id)
    if form is None:
        return sections
    phrases = _spec_instruction_phrases(form.spec)
    out = []
    for s in sections:
        nb = _norm_echo(s["body"])
        echoed = bool(nb) and any(
            nb == p or (nb.endswith(p) and 0 < len(nb.split()) - len(p.split()) <= 3) for p in phrases
        )
        if echoed:
            out.append({**s, "body": f"[[NEEDS: {s['heading']} not documented — model repeated the "
                                     f"template instruction instead of a value]]"})
        else:
            out.append(s)
    return out


# --- folded-heading repair (CLAUDE.md rules 10 + 19) --------------------------------
# A section heading is a LABEL ("Functional Mobility / Gait" is 26 chars; the longest in any
# built-in template is well under this). Anything longer means the model wrote the section's
# CONTENT on the "## " line instead of in the body below it.
#
# This is a PRODUCTION contract, not an eval-only ruler — evals/score.py imports it from here.
# Measured on a real MedGemma 4B sweep (2026-08): on 2 of 3 notes the model folded the content into
# the heading and left EVERY body empty (8/14 headings over 80 chars, longest 339). Two things make
# that worse than it sounds:
#   * traceability.add_verification_flags inspects `body` ONLY, so the entire rule-20 verification
#     layer silently no-ops — an invented device and invented vitals passed through unflagged while
#     the note scored clean on every other invariant; and
#   * app.js:renderEditView renders the heading as a <span> and gives a textarea only for the body,
#     so the folded content is not even CORRECTABLE by the clinician without regenerating.
# Per rule 19 ("when a failure class is a detectable, meaning-safe pattern, move it into
# postprocess.py"), this is repaired deterministically rather than prompted or fine-tuned for.
MAX_HEADING_CHARS = 80

MAX_LABEL_CHARS = 60   # the longest label the repair is willing to MANUFACTURE
MAX_LABEL_WORDS = 8    # "Social History / Living Environment" is 5 words / 34 chars

_SEPARATORS = (" — ", " – ", " -- ", ": ", " - ")
_SENTENCE_END_RE = re.compile(r"(?<=[.!?])\s+")
# A "label" carrying a measured value is CONTENT, not a label ("Pain 8/10 at rest").
_VALUE_IN_LABEL_RE = re.compile(
    r"\b\d+\s*(?:/\s*\d+|minutes?\b|mins?\b|degrees?\b|°|feet\b|ft\b|lbs?\b|%"
    # Units added when the no-separator fold below was measured on real Follow-Up notes: without
    # `bpm`, "## Vitals 72 bpm, 78/45" split at the blood pressure and left the heart rate stranded
    # in the heading. Widening this regex only ever makes a candidate label MORE likely to be
    # rejected as content, which is the safe direction for both of its callers.
    r"|bpm\b|mmhg\b|kg\b|lb\b|cm\b|reps?\b|sec(?:onds?)?\b)", re.IGNORECASE)
_TRAILING_MINUTES_RE = re.compile(r"\s*\bminutes?\s*:?\s*$", re.IGNORECASE)

_FOLD_MARKER = (" [[NEEDS: the model wrote this section's content on the heading line — Cadence "
                "moved it into the body; check it is complete and belongs in this section]]")


#: The em/en dash specifically — the template specs' own "Label — description" format, which the
#: model echoes with the VALUE inline where the description should be. Distinguished from " - "
#: and ": ", which appear INSIDE legitimate labels ("Pain - At Rest", "Coordination / Sensation").
_STRONG_SEPARATORS = (" — ", " – ")


def is_folded_heading(section: dict) -> bool:
    """True if the model wrote this section's CONTENT or VALUE on the heading line.

    An empty body is required either way — that is what distinguishes a folded heading from a
    long-but-real one, and "empty" means empty AFTER stripping `[[...]]` markers so it matches how
    evals/score.py computes `empty_bodies` (that invariant is this repair's tripwire).

    Two shapes qualify:
      * an over-long heading, where the model wrote whole paragraphs on the `## ` line; and
      * a SHORT heading carrying a value after an em/en dash — `## Vitals — BP: 120/80 mmHg,
        HR: 72 bpm`, `## Pain - At Rest — 3/10`, `## Short-Term Goals — MET`. Observed six times
        in one real generation. These are the same failure under the length threshold, and they
        matter for the same reason: with an empty body, `flag_unsupported_vitals` and
        `flag_unanchored_in_sections` cannot see the value, so an INVENTED blood pressure passes
        unflagged. Restricted to the em/en dash because " - " and ": " occur inside legitimate
        labels — splitting `## Pain - At Rest` on its hyphen would mangle a real template heading.

    A third shape was added after measuring 4 real Follow-Up generations: the SAME value fold with
    NO SEPARATOR AT ALL — `## Vitals 122/76`, `## Pain - At Rest 1/10`, `## Vitals 72 bpm, 78/45`,
    every one with an empty body. The dash requirement above missed all of them, so three of four
    real follow-ups carried a blood pressure that `flag_unsupported_vitals` could not see and
    `renderEditView` gave the clinician no box to correct. It is recognised by the VALUE itself
    rather than by punctuation: a heading whose tail begins a measured value, with a legitimate
    section label in front of it. `## Response to Treatment Good` is deliberately NOT caught —
    "Good" is a value to a reader but not a mechanically detectable one, and inventing a rule to
    split on a trailing adjective would start mangling real labels.

    A CPT/ICD-headed section is excluded on purpose: `flag_code_sections` REPLACES the whole body
    of one, so splitting first would hand it content that then gets wiped. Rule 12 wins there.
    """
    heading = section.get("heading", "") or ""
    if _ECHO_MARKER_RE.sub("", section.get("body", "") or "").strip():
        return False
    if _CODE_HEADING_RE.search(heading):
        return False
    return (len(heading) > MAX_HEADING_CHARS
            or any(sep in heading for sep in _STRONG_SEPARATORS)
            or _bare_value_split(heading) is not None)


def _bare_value_split(heading: str) -> int | None:
    """Index at which a heading stops being a label and starts being a measured value, or None.

    `"Vitals 122/76"` -> 7. The left side must still read as a section label, which is what keeps
    a legitimate numeric label ("6-Minute Walk Test", "10 Meter Walk") from being cut in half:
    those do not match `_VALUE_IN_LABEL_RE` at all, so there is no candidate split to begin with.
    """
    m = _VALUE_IN_LABEL_RE.search(heading)
    if m is None or m.start() == 0:
        return None
    if _valid_label(heading[:m.start()]) is None:
        return None
    return m.start()


def _valid_label(raw: str) -> str | None:
    """A candidate left-hand side, or None if it reads as content rather than a section label."""
    label = raw.strip().strip(" .,;:—–-")
    if not label or len(label) > MAX_LABEL_CHARS:
        return None
    if len(label.split()) > MAX_LABEL_WORDS:
        return None
    if not re.search(r"[A-Za-z]", label):
        return None
    if _VALUE_IN_LABEL_RE.search(label):
        return None
    if label.count("[[") != label.count("]]"):   # never bisect a marker
        return None
    return label


def _split_points(heading: str) -> list[tuple[int, int]]:
    """Candidate (split_at, resume_at) pairs, excluding any that fall inside a `[[...]]` marker.

    For a SHORT heading only the em/en dash counts. `## Pain - At Rest — 3/10` must split at the
    em dash, not at the hyphen inside its own label; and a sentence boundary in a short heading is
    almost certainly punctuation in the label rather than a fold.
    """
    spans = [m.span() for m in _ECHO_MARKER_RE.finditer(heading)]
    inside = lambda i: any(s < i < e for s, e in spans)  # noqa: E731
    long_heading = len(heading) > MAX_HEADING_CHARS
    out: list[tuple[int, int]] = []
    for sep in (_SEPARATORS if long_heading else _STRONG_SEPARATORS):
        start = 0
        while (i := heading.find(sep, start)) != -1:
            if not (inside(i) or inside(i + len(sep))):
                out.append((i, i + len(sep)))
            start = i + 1
    if long_heading:
        for m in _SENTENCE_END_RE.finditer(heading):
            if not (inside(m.start()) or inside(m.end())):
                out.append((m.start(), m.end()))
    # The separator-less value fold. Offered LAST and only when nothing else applies, so a heading
    # that does have a dash still splits there — the dash is the stronger signal of where the
    # label ends.
    if not out and (at := _bare_value_split(heading)) is not None and not inside(at):
        out.append((at, at))
    return sorted(set(out))


def _truncate_at_word(text: str, limit: int) -> str:
    """Cut at the last space at or before `limit`, backing off if that would bisect a marker."""
    if len(text) <= limit:
        return text.strip()
    cut = text.rfind(" ", 0, limit + 1)
    cut = cut if cut > 0 else limit
    for s, e in (m.span() for m in _ECHO_MARKER_RE.finditer(text)):
        if s < cut < e:
            cut = s
    return text[:cut].strip().strip(" .,;:—–-") or text[:limit].strip()


def split_folded_headings(sections: list[dict]) -> list[dict]:
    """Move content the model wrote on the `## ` line down into the body (rules 10 + 19).

    Text is MOVED, never rewritten — only the separator and boundary whitespace are dropped, and
    any existing body is appended below rather than replaced (so a model-authored
    `[[CARRIED FORWARD]]` body tag survives for `enforce_carry_tags` two steps later).

    When no clean split point exists the whole heading still moves, under a word-boundary
    truncation, and earns a `[[NEEDS: ...]]` marker. Leaving it alone is not the safer option: the
    eval invariant that would catch it never runs in the clinic, and the content would stay both
    unverifiable and uneditable. A clean split is a confident, meaning-safe move and gets no marker
    (same posture as `normalize_strength_grades`); the fallback is a GUESS about where the label
    ends, and that is what earns the flag.
    """
    out = []
    for s in sections:
        if not is_folded_heading(s):
            out.append(s)
            continue
        heading = s["heading"]
        label = moved = None
        for split_at, resume_at in _split_points(heading):
            candidate = _valid_label(heading[:split_at])
            if not candidate:
                continue
            # Rule 10: "Minutes: 25" belongs in the body, whole. If the label ends on a dangling
            # "Minutes", shift the cut left so the number travels with its word.
            if (m := _TRAILING_MINUTES_RE.search(candidate)):
                shifted = _valid_label(candidate[:m.start()])
                if shifted:
                    split_at = heading.find(candidate) + m.start()
                    resume_at = split_at
                    candidate = shifted
            label, moved = candidate, heading[resume_at:].strip()
            break

        if label is None:
            if len(heading) <= MAX_HEADING_CHARS:
                # A SHORT heading we couldn't parse is left exactly as it was. The truncation
                # fallback exists for long folded prose; applying it to a short label would
                # mangle a legitimate heading to no benefit.
                out.append(s)
                continue
            # No clean split in a long heading — move everything, truncate the label, and flag.
            label = _truncate_at_word(heading, MAX_LABEL_CHARS)
            moved = heading.strip() + _FOLD_MARKER

        body = s.get("body", "") or ""
        out.append({**s, "heading": label,
                    "body": moved + ("\n" + body if body.strip() else "")})
    return out


# --- the spec-title heading (CLAUDE.md rule 32) --------------------------------------
# Measured on 4 real Follow-Up generations: 3 of them turned the template's own TITLE LINE into a
# section heading —
#
#     ## Follow-Up Visit
#     Precautions [carry forward] — weight-bearing status, no lifting over ten pounds overhead.
#
# — which does two things at once, and the second is the damaging one. It invents a section nobody
# asked for, and it CONSUMES the real first section: "Summary of Daily Skilled Services" is gone,
# and the Precautions content is filed under a heading that is not Precautions. `Precautions` is a
# CARRY-FORWARD label, so `forms.CARRY_SECTION_LABELS` and `carry_forward` stop matching it and the
# next visit has nothing to carry.
#
# The repair is safe because it is anchored twice: the heading must equal the form's own ALL-CAPS
# title (never a declared section), AND the body must OPEN with a label the template actually
# declares. Both come from the spec, so this can only ever relabel a section the template named —
# it cannot invent one. When the body reveals no label the section is left exactly as it is, since
# a miss is recoverable and a wrong relabel is not.
_LABEL_LEAD_RE_CACHE: dict[str, re.Pattern] = {}


def _label_lead_re(label: str) -> re.Pattern:
    """Matches a body that opens with `<label>` plus the spec's own decoration and separator:
    "Precautions [carry forward] — ", "Precautions: ", "Precautions - "."""
    if label not in _LABEL_LEAD_RE_CACHE:
        _LABEL_LEAD_RE_CACHE[label] = re.compile(
            r"^\s*" + re.escape(label) + r"\s*(?:\[[^\]]*\])?\s*(?:[—–:-]\s*)?",
            re.IGNORECASE)
    return _LABEL_LEAD_RE_CACHE[label]


def _leading_declared_label(form_id: str, body: str) -> str | None:
    """The declared section label a body opens with, longest first so "Pain - At Rest" is not
    matched as the shorter "Pain"."""
    labels = sorted(forms_store.spec_section_labels(form_id), key=len, reverse=True)
    for label in labels:
        if _label_lead_re(label).match(body or ""):
            return label
    return None


def relabel_spec_title_heading(form_id: str, sections: list[dict]) -> list[dict]:
    """Rename a section whose heading is the template's TITLE to the section its body actually is."""
    title = forms_store.spec_title(form_id)
    if not title or not sections:
        return sections
    declared_lower = {d.lower() for d in forms_store.spec_section_labels(form_id)}
    out = list(sections)
    for i, sec in enumerate(out):
        heading = _norm_echo(sec.get("heading", ""))
        if heading != _norm_echo(title) or heading in declared_lower:
            continue
        label = _leading_declared_label(form_id, sec.get("body", ""))
        if label is None:
            continue     # cannot tell what it is — leave it alone rather than guess
        out[i] = {**sec, "heading": label,
                  "body": _label_lead_re(label).sub("", sec.get("body", "")).lstrip()}
    return out


def strip_redundant_body_label(form_id: str, sections: list[dict]) -> list[dict]:
    """Drop a body's opening restatement of ITS OWN heading.

    The model routinely writes the spec's label again as the body's first words —
    `## Long-Term Goals` / "Long-Term Goals [carry forward] — Returning to a full workday…". The
    removed text is the template's own label for that very section, so nothing the clinician said
    can be lost; and it only fires when the label matches the heading the section already has.
    """
    out = []
    for sec in sections:
        heading = (sec.get("heading") or "").strip()
        body = sec.get("body") or ""
        stripped = _label_lead_re(heading).sub("", body).lstrip() if heading else body
        # Never empty a section by removing its whole body — that would trade a cosmetic problem
        # for a lost one.
        out.append({**sec, "body": stripped} if stripped.strip() else sec)
    return out


def split_shifted_section_bodies(form_id: str, sections: list[dict]) -> list[dict]:
    """Recover a section whose content the model filed under the PREVIOUS heading.

    The same shift that produces the spurious title heading continues down the note:

        ## Pain - At Rest 1/10
        Pain - With Movement 4/10

    At-Rest's value is stranded on the heading line and With-Movement's content is sitting in
    At-Rest's body, so With-Movement does not exist as a section at all. Splitting it back out
    both restores it and leaves an empty body behind — which is exactly the shape
    `split_folded_headings` then repairs, moving "1/10" down where the verification layer can see
    it. That chain is why this runs BEFORE the fold repair.

    Three guards, and the middle one is what makes this safe:
      * the label must be one the TEMPLATE declares — never arbitrary capitalised text;
      * that section must be ABSENT from the note. A Plan body that opens "Short-Term Goals will
        be reassessed…" is prose, and the giveaway is that Short-Term Goals already exists as its
        own section. We only ever recover something genuinely missing;
      * it must be at the very START of the body, not mentioned partway through.
    """
    declared = forms_store.spec_section_labels(form_id)
    if not declared:
        return sections
    present = {(s.get("heading") or "").strip().lower() for s in sections}
    out: list[dict] = []
    for sec in sections:
        body = sec.get("body") or ""
        heading_l = (sec.get("heading") or "").strip().lower()
        label = None
        for cand in sorted(declared, key=len, reverse=True):
            cl = cand.lower()
            if cl == heading_l or cl in heading_l:
                continue                       # this section's own label — a different repair
            if cl in present:
                continue                       # already exists, so this is prose about it
            if _label_lead_re(cand).match(body):
                label = cand
                break
        if label is None:
            out.append(sec)
            continue
        moved = _label_lead_re(label).sub("", body).lstrip()
        out.append({**sec, "body": ""})
        out.append({"heading": label, "body": moved,
                    "carried_forward": sec.get("carried_forward", False)})
        present.add(label.lower())
    return out


#: A heading remainder that continues the LABEL rather than starting a VALUE. "Plan of Treatment"
#: begins with the declared label "Plan", and splitting it would invent a section called "Plan"
#: with a body of "of Treatment". A value never opens with one of these.
_LABEL_CONTINUATION_RE = re.compile(r"^(?:of|for|and|with|to|in|on|at|the|a|an)\b", re.IGNORECASE)


def split_declared_label_headings(form_id: str, sections: list[dict]) -> list[dict]:
    """Move a NON-NUMERIC value off a heading line, using the template's own label as the anchor.

    `split_folded_headings` finds this shape when the stranded value is a measurement, because a
    measurement is mechanically recognisable. It cannot find `## Response to Treatment Good` —
    "Good" is a value to a reader and nothing to a regex — so that section kept an empty body,
    which meant `renderEditView` gave the clinician no box to correct it.

    Having the declared labels makes it tractable: the heading is `<a label the template asked
    for>` + a remainder, and the body is empty, so the remainder is content. The guard is that the
    remainder must look like a VALUE and not like the rest of a label — otherwise "Plan of
    Treatment" splits into a "Plan" section whose body is "of Treatment".
    """
    declared = sorted(forms_store.spec_section_labels(form_id), key=len, reverse=True)
    if not declared:
        return sections
    out = []
    for sec in sections:
        heading = (sec.get("heading") or "").strip()
        if _ECHO_MARKER_RE.sub("", sec.get("body", "") or "").strip():
            out.append(sec)                      # a real body — nothing is stranded
            continue
        if _CODE_HEADING_RE.search(heading):
            out.append(sec)                      # rule 12 owns these
            continue
        for label in declared:
            if len(heading) <= len(label) or not heading.lower().startswith(label.lower()):
                continue
            remainder = heading[len(label):].strip(" .,;:—–-")
            if not remainder or _LABEL_CONTINUATION_RE.match(remainder):
                continue
            sec = {**sec, "heading": label, "body": remainder}
            break
        out.append(sec)
    return out


def apply(form_id: str, sections: list[dict]) -> list[dict]:
    # strip_carry_instruction_headings runs FIRST: it is heading-only, so it must clear an echoed
    # "[carry forward]" spec instruction before the split could strand it in the body where
    # nothing strips it.
    sections = strip_carry_instruction_headings(sections)
    # Then the general spec-instruction strip, BEFORE the fold repair. Order matters: if such a
    # heading also had an empty body, split_folded_headings would MOVE the instruction text down
    # into the body, where it would masquerade as clinical content and no later pass removes it.
    # Stripping first means the fold repair only ever sees real content.
    sections = strip_spec_instruction_headings(form_id, sections)
    # Then the TITLE heading, before the fold repair and before enforce_carry_tags: the section it
    # rescues is usually a CARRY-FORWARD one, and it can only be matched to its real label while
    # that label is still sitting at the front of the body.
    sections = relabel_spec_title_heading(form_id, sections)
    sections = strip_redundant_body_label(form_id, sections)
    # Before the fold repair: this leaves an empty body behind, which is precisely the shape the
    # fold repair then fixes by moving the stranded value off the heading line.
    sections = split_shifted_section_bodies(form_id, sections)
    # The split must precede the zero-minutes drop. That drop matches "Minutes: 0" at the START OF
    # THE BODY, so a folded "Minutes: 0 — ultrasound not performed today" leaves an empty body, the
    # drop never fires, and the invented placeholder section survives into the note. Splitting
    # first restores the marker to the body's first line. Everything downstream gains for the same
    # reason: enforce_carry_tags stops matching a carry label inside a 339-char haystack, and
    # normalize_strength_grades / strip_checklist_affirmations / traceability finally see content.
    sections = split_folded_headings(sections)
    # After the value-shaped fold repair, for the ones it cannot recognise: a non-numeric value
    # stranded on a heading that starts with one of the template's own section labels.
    sections = split_declared_label_headings(form_id, sections)
    sections = drop_unperformed_treatment_sections(sections)
    sections = enforce_carry_tags(form_id, sections)
    sections = flag_template_echo(form_id, sections)
    sections = flag_code_sections(sections)
    sections = flag_code_field_lines(sections)
    sections = normalize_strength_grades(sections)
    sections = strip_checklist_affirmations(sections)
    return sections
