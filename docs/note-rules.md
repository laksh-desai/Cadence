# Note generation rules

Canonical source: `CLAUDE.md`. This file mirrors that section so it travels with the
rest of the docs; if the two ever disagree, `CLAUDE.md` wins — update this file to
match, not the other way around.

These were derived by testing the prototype and correcting real failures. Apply them
in every note-generation prompt (`app/generate/prompt.py`, `app/generate/rules.py`):

1. **Never invent clinical values** — minutes, vitals, pain levels, measurements,
   dates. If a required value is absent, flag it for the clinician; never guess.
2. **No inferring demographics** — never compute the patient's age from a date of
   birth, and never infer unstated demographics. Use only what is explicitly stated.
3. **Carry-forward means reconcile, not copy.** When today's session changes a
   carried value (ambulation distance, assistive device, assist level, stairs
   attempted, overall functional status), update that section to reflect today.
   Carried sections must never contradict today's treatment sections.
4. **Internal consistency** — today's findings take precedence; no two sections may
   contradict each other. Check this before finishing.
5. **Goals** — mark a goal MET only if today's data shows it achieved. When all
   short-term goals are met, the Plan must justify continued skilled care by
   reference to the remaining unmet long-term goals.
6. **Require-mode discipline** — only flag genuinely-absent values in sections that
   apply. Never flag treatments that weren't performed, never invent requirements (no
   billing-audit granularity, no fields borrowed from other note types), never put
   discrepancies or "consider documenting" suggestions in the missing list. If all
   required fields for applicable sections are present, flag nothing.
7. **Omit-mode discipline** — include only what was said; omit unmentioned sections;
   never infer.
8. **Charitable language handling / spoken-transcript cleanup** — the dictation is a
   raw MedASR speech-to-text transcript of the therapist talking, who is also a fluent
   but non-native English speaker. Expect spoken filler and hesitation words (um, uh,
   like, so, you know), false starts, repeated words, and mid-sentence self-corrections.
   Drop every filler and disfluency, keep only the corrected value on a self-correction,
   interpret imperfect grammar charitably, and render clean, professional clinical
   English without changing the facts. Unambiguous vocalized pauses (um, uh, hmm, and
   the like) are ALSO stripped deterministically from the dictation before generation
   in `app/generate/prompt.py:clean_dictation` — a model-independent backstop; tokens
   that collide with real clinical usage (`mm` = millimeters, `er`/`ER` = external
   rotation) are deliberately left for the prompt, never stripped.
9. **Unique, non-boilerplate** wording every session, built from the specific details
   stated. Two sessions must not read the same.
10. **"Minutes: __" belongs in the section body, never the heading** — headings stay
    clean section/CPT names.
11. **MedGemma 4B reliably over-tags `[[CARRIED FORWARD]]` and invents empty
    "not performed" treatment sections, regardless of prompt wording.** This is
    enforced deterministically in code (`app/generate/postprocess.py`), not relied on
    via prompting alone — see `CARRY_SECTION_LABELS` in `app/generate/forms.py`.
12. **Never let the model author a CPT or ICD-10 code** — observed it fabricate both,
    including a wrong ICD-10 code, with zero basis in the dictation. Enforced via
    `app/generate/postprocess.py:flag_code_sections`.
13. **Carry-forward reconciliation is not reliable for every section, even with the
    snapshot correctly available** — observed Functional Status punt with a
    `[[NEEDS:...]]` flag on a real second-visit test instead of synthesizing the
    update, while Gait Training in the same note correctly updated. Safe (no
    fabrication) but inconsistent; don't assume one successful test generalizes.
14. **Postprocess fixes close specific structural failure modes, not fabrication
    risk in general** — the model has also been observed inventing assistive
    devices and pain ratings outright with no pattern a code fix can catch. This is
    why clinician review of every note is non-negotiable.
15. **Complete extraction — never silently drop a stated fact (require mode).** Every
    stated medication/dose, diagnosis/PMH item, prior therapy, living environment, code
    status, goal, measurement, and plan value must appear; dropping is as serious as
    inventing. Root cause of the worst omissions was a template with nowhere to put the
    content — the Initial Eval template gained Medications, Allergies, Social
    History/Living Environment, clinical-complexity, discharge/transition, and
    participation sections. **Audit the template before tuning the prompt.** Enforced by
    `templates/initial.md` + the completeness paragraph in `MODE_RULE_REQUIRE`.
16. **Output/context ceiling caused silent truncation.** `num_ctx` was 4096 with no
    `num_predict`; a long dictation + template + rules overflowed it, dropping the
    transcript tail and cutting the note off mid-sentence ("Certification period").
    Raised to `num_ctx=8192` + `num_predict=3072` in `app/generate/ollama_client.py`.
    Genuinely huge dictations need chunked/two-pass generation, not a bigger context —
    **now implemented** in `app/generate/chunked.py` (`fit_dictation`), gated so a
    normal-length dictation is byte-identical (no extra model call) and only an
    overflowing one is split + condensed (fact-preserving) before the normal pipeline,
    with a visible "verify completeness" flag. Condense pass is a 4B call (rules 14/15),
    so not yet validated on a real 30-min+ dictation; unit-tested in `tests/test_chunked.py`.
17. **Spoken-artifact cleanup beyond fillers (prompt-level).** Convert dictated
    checklist answers ("worries about falling, yes") to declarative sentences (never
    emit "..., yes"/"..., no" or question+answer); repair garbled ASR, marking
    unrecoverable text `[[NEEDS: unclear dictation "..."]]`; on a self-contradiction or
    two-values-for-one-field record the standard value + append `[[NEEDS: dictation also
    stated "..." — clinician to confirm]]`. Prompt-only mitigations (no safe
    deterministic rewrite) — clinician review still applies. Flags reuse `[[NEEDS: ...]]`
    because that is the only marker the UI renders in amber. **Exception (backed by
    code):** a statement-final checklist *affirmation* "..., yes" — echoed verbatim by
    the model regardless of prompt — is stripped deterministically in
    `app/generate/postprocess.py:strip_checklist_affirmations` (bounded to end-of-statement
    so it never touches a mid-clause "..., yes, and ..."). The *negation* "..., no" is
    left prompt-only because dropping it would invert clinical meaning.
18. **Map values by meaning, standardize notation, don't duplicate.** Plan-of-treatment:
    Frequency=visits/week, Duration=weeks, Intensity=min/session regardless of the label
    spoken ("duration sixty minutes" → Intensity). MMT grades in standard notation
    ("3+/5", "3+/5 to 4-/5") — also enforced deterministically in
    `app/generate/postprocess.py:normalize_strength_grades` (denominator-five only, so
    it never touches a pain rating). Each section in its own words at its own level — no
    identical sentences pasted across sections. Every section ends on a complete
    sentence with its full value. All in `WRITING_RULES_LEAD`.
19. **Completeness must not become confabulation.** Confirmed on a real Initial Eval run
    after the rule-15 template expansion: the model filled unmentioned exam sections
    (ROM, skin/neuro/cognition, cardiopulmonary O2, coordination/sensation/edema) with
    invented normals ("intact", "unremarkable", "no edema", "O2 normal") — reading the
    forceful rule-15 completeness wording as "every section must be filled." Countered in
    `MODE_RULE_REQUIRE`: completeness means every STATED fact appears, NOT that every
    section is filled; asserting an unstated normal/negative exam finding is fabrication
    as serious as dropping a stated fact — omit or flag `[[NEEDS: not documented]]`,
    never fabricate a normal. The prompt half is best-effort (other prompt-only mitigations 17,
    18(c) each failed on the same run), but this class now ALSO has a deterministic backstop — see
    rule 20: you don't distinguish a stated-normal from an invented-normal by the text, you flag
    any normal whose body system the dictation never mentions. Clinician review remains the backstop.
20. **Local verification layer — deterministic hallucination flags** (`app/generate/traceability.py`,
    run in `/api/generate` after postprocess via `add_verification_flags`). Appends amber
    `[[NEEDS: ...]]` markers, model-independently, for (a) **unanchored clinical values** — a
    number in the note (pain X/10, MMT X/5, minutes, ROM degrees, ambulation distance) absent from
    the dictation → probable fabrication (`normalize_for_matching` bridges spoken↔written incl. MMT
    ranges, denominator distributing to both grades); (b) **unsupported normals** — a "normal"
    exam finding about a body system the dictation never mentions (rule 19); (c) **unsupported
    vitals** — a BP/HR/O2 value whose type the dictation never mentions (type-mention, so spoken
    idioms and honest "HR: Not stated" don't false-flag; BP pattern rejects dates); (d) **invented
    assistive devices** — a cane/walker/… whose head noun the dictation never mentions (rule 14),
    negation-aware; (e) **cross-section paste-duplication** — an exact long sentence repeated across
    2+ sections (rule 18c). All FLAG, never delete (hedged — a real dictated value/normal is
    indistinguishable in text), leaning on clinician review. Verified on real generations.

## Standing workflow instruction

When a generated note is wrong, fix the underlying prompt/logic so that entire class
of mistake is prevented going forward — do not just patch the single note. Add the
new correction to the rules above (and to `CLAUDE.md`) so it persists.

## Two completeness modes

- **REQUIRE mode** — all applicable fields required; flag genuinely-missing values;
  used for clinical/billing documents: Initial Evaluation, Follow-Up Visit,
  Discharge Summary, Progress Report, SOAP-format PT Follow-Up.
- **OMIT mode** — include ONLY what was explicitly stated; drop empty sections; never
  infer: SOAP Note, MSK Assessment/Treatment, After-Visit Letter, Referral Letter,
  SMART Goal Note, Issues List.

## Carry-forward forms

Follow-Up Visit, Discharge Summary, Progress Report, SOAP-format PT Follow-Up pull
precautions/functional status/goals forward from the prior note. The Initial
Evaluation never carries forward (it is the first visit).
