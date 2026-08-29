# Cadence — Claude Code Project Guide

Cadence is a **local, offline, HIPAA-conscious desktop app** that turns a physical
therapist's spoken summary of a session into a completed clinical note, filling the
practice's existing templates automatically. It replaces a paid cloud service
(ScopeHealth) for a single small PT practice. The therapist dictates a short summary
after each session; Cadence transcribes it, fills the correct note template, flags
missing required fields instead of inventing them, carries forward the right sections
from prior visits, and writes each note uniquely (no boilerplate) so insurance
submissions don't look templated.

---

## Non-negotiable constraints

- **Everything runs locally. No protected health information (PHI) ever leaves the
  machine — with exactly one sanctioned exception: Google Workspace.** The practice
  has a signed Business Associate Agreement with Google under its Workspace business
  account, and this is the **only** third party PHI may ever be sent to.
  - This is a narrow, deliberate carve-out, not a general opening. No other
    third-party service — cloud AI, analytics, storage, anything — may ever process
    real patient data, BAA or not, unless explicitly re-authorized in this file.
  - The BAA covers the practice's **Google Workspace business account** specifically.
    Before sending PHI to any Google product/feature (e.g. Sheets), confirm it's
    reached through that same business account — a personal/consumer Google account
    is **not** covered and must never receive PHI.
  - This exception covers data the practice explicitly chooses to sync to Google
    (e.g. a patient/notes view in Google Sheets). It does not change anything about
    local generation, local model inference, or local storage — those still never
    leave the device.
- The prototype (`cadence-prototype.html`, at the repo root) **no longer calls any
  model.** It formerly POSTed to a cloud model (Anthropic) as a stand-in for the local
  model, using FAKE data only; that live cloud call has been removed. It is now a
  **static UX/note-quality reference** — its Generate button points the user to the
  running local app (`http://127.0.0.1:8420`) instead of generating anything itself,
  and it makes no outbound calls (only Google Fonts and that local link). The
  production app (`app/`) is where real, fully-local generation happens. Never
  reintroduce a cloud generation path here or wire real patient data to it — it is
  unrelated to, and not covered by, the Google Workspace exception above.
- **The clinician reviews and signs every generated note.** Cadence drafts; it never
  finalizes clinical content on its own, and never fabricates clinical values.

## Target hardware (both development and deployment)

Lenovo ThinkPad, Intel Core i5-8365U (4 cores / 8 threads, 8th gen, **no dedicated
GPU** — Intel UHD 620), 16 GB RAM, 238 GB SSD. **CPU-only inference.** This caps the
local LLM at roughly 4B parameters. Do not assume a GPU or large VRAM.

**Generation takes 5–9 minutes per note, not the 1–2 this file used to claim.** Measured across
21 real generations on the DEV box: median 7.0 min, range 4.6–9.5, 21 of 21 over the old budget,
and the target ThinkPad is SLOWER than that box. The floor was set by a **91-word follow-up**, so
the cost is output length and template size, not how much the therapist said. That number is not
reachable by tuning — see rule 26 for why the two obvious levers don't work and what was built
instead.

## Production stack

- **Transcription (speech-to-text): implemented.** Local **MedASR**
  (`google/medasr`, Conformer-CTC, ~105M params), run via `transformers` + CPU-only
  `torch` in `app/transcribe/medasr_client.py`. Audio is captured and WAV-encoded
  entirely client-side (`app/ui/static/app.js`) and POSTed to `/api/transcribe` —
  no audio ever leaves the device. The model is gated on Hugging Face; see
  `docs/medasr-setup.md` for the one-time account/token setup. Loaded once at
  FastAPI startup; if setup isn't done yet, the rest of the app still works and
  the mic buttons surface a clear, actionable error instead of crashing anything.
- **Note generation (form-filling):** **MedGemma 4B (text-only)**, the medical-tuned
  Gemma variant, run locally via Ollama, CPU-only, ~Q4 quantization (~3–4 GB RAM).
- **Storage:** encrypted local SQLite (`app/storage/`) for patients and saved
  notes — Fernet-encrypted at rest, decrypt-to-temp-on-start / re-encrypt-on-write.
- **Roster sync:** optional bidirectional Google Sheets sync for the patient
  roster (`app/integrations/`) — see the Google Workspace BAA exception above.
- **Packaging:** a local FastAPI backend serving a browser UI (`app/ui/`), launched
  via a desktop shortcut (`launcher.py`) that starts the server and opens the
  browser. The model server (Ollama) and the FastAPI app both stay local-only.
- MedGemma "isn't yet clinical grade" per Google; expect to validate and likely
  fine-tune on the clinician's own reviewed notes. Every note is clinician-reviewed
  regardless of model quality. The same caution applies to MedASR's transcription
  output per its own usage terms — it's a draft input to note generation, never
  the final record.

---

## The note templates (3 built-in)

The practice trimmed the built-in set to **three** templates (the rest were removed at the
clinician's request and moved to `templates/_archive/` — recoverable, not loaded). Users add back
any other note types themselves via the **Templates** tab (create / duplicate / edit — see
Conventions). All are filled from the same dictation. Completeness modes:

**REQUIRE mode** — all applicable fields required; flag genuinely-missing values:
- **Initial Evaluation** (`initial`, `templates/initial.md`) — full-intake baseline, carry-forward
  OFF. **Field-per-section** outline (one `## ` section per field) keeping all rule-15 completeness
  sections (Medications, Allergies, Social History / Living Environment, clinical complexity,
  discharge/transition, participation, etc.). No codes block (rule 12). Surfaces the
  evaluation-complexity CPT flag.
- **Initial Evaluation — Updated Version** (`initial_updated`, `templates/initial_updated.md`) —
  the clinician's own 4-**block** outline verbatim (═══ dividers; includes a CPT/ICD codes block,
  handled by the deterministic guards); carry-forward OFF; surfaces the eval-complexity flag. Kept
  alongside `initial` deliberately (the clinician wanted both; names unchanged so they're
  distinguishable). This is the ONE remaining block-format template — see the tradeoff note below.
- **Follow-Up Visit** (`followup`, `templates/followup.md`) — interim skilled visit, field-per-section,
  **carry-forward ON**. Carry section labels (`Precautions`, `Functional Status`, `Short-Term Goals`,
  `Long-Term Goals`) + their `[carry forward]` markers are preserved so `CARRY_SECTION_LABELS` /
  `carry_forward.CARRY_FIELD_HEADING_MAP` match.

**OMIT mode** — none built-in anymore (the omit-mode note types — SOAP, MSK, After-Visit Letter,
Referral, SMART, Issues — were the removed ones). Omit mode still exists and is selectable when
creating a custom template.

**Carry-forward forms:** only **Follow-Up Visit**. The Initial Evaluations never carry forward.
Custom templates are always non-carry (v1).

### Block-format vs field-per-section (resolved — the reason `initial`/`followup` are field-per-section)

> **Read rule 27 alongside this.** Everything below is still why the forms are shaped as they are,
> but the risk assessment in it is out of date: measured on 25 real generations, `initial_updated`'s
> block format is the BEST-behaved of the three (100% template conformance) and the
> field-per-section Follow-Up is the worst (62%, dropping its carry-forward sections). Treat this
> section as the design rationale, not as a live worry.

Confirmed on real generations: block-outline templates (═══ dividers + `Field:` labels) do NOT map
cleanly to the app's `## <section>`-per-field pipeline. The 4B model is **nondeterministic** about
them — sometimes a `## ` per BLOCK, sometimes it folds the WHOLE note under one `## <TITLE>` heading
with the fields as `Field: value` body lines. That breaks per-field features:
- **CPT chips:** `cpt.suggest_codes` matches a treatment's own section HEADING (deliberately — rule
  12; matching prose would misfire), so block output (treatment as a body line) gets no `[[CPT: …]]`.
  Do NOT "fix" by body-scanning for interventions — that reintroduces rule 12's misfire risk.
- **Per-section review/edit** collapses to one/few big sections.
So the clinician chose: **generate field-per-section, then group into the 4 SOAP fields as a
copy transform.** `initial` and `followup` are now field-per-section (CPT chips + per-field review +
carry-forward all work); `initial_updated` stays block by explicit request (an eval, non-carry, so
the CPT-per-treatment gap barely applies). The **"Copy for Office Ally"** control (`app.js`
`soapGroups` / `officeAllyHTML` / `wireOfficeAlly`, keyword classifier `SOAP_RULES`) buckets any
note's sections into Subjective/Objective/Assessment/Plan for one-click copy into each Office Ally
field. **Belt-and-suspenders:** `carry_forward.extract_snapshot_fields` still keeps its
`_find_labeled_value` body-scan fallback (heading match first, then scan bodies for `Functional
Status: …` lines), so carry-forward survives even if `initial_updated`-style block output or a model
regression ever folds a note (verified 4/4 on a real single-section Follow-Up). `test_carry_extract.py`
locks both paths.

Reference template structures live in `templates/`; archived built-ins in `templates/_archive/`.

---

## Generation rules (hard-won — keep and extend these)

These were derived by testing the prototype and correcting real failures. Apply them in
every note-generation prompt:

1. **Never invent clinical values** — minutes, vitals, pain levels, measurements,
   dates. If a required value is absent, flag it for the clinician; never guess.
2. **No inferring demographics** — never compute the patient's age from a date of
   birth, and never infer unstated demographics. Use only what is explicitly stated.
3. **Carry-forward means reconcile, not copy.** When today's session changes a carried
   value (ambulation distance, assistive device, assist level, stairs attempted,
   overall functional status), update that section to reflect today. Carried sections
   must never contradict today's treatment sections.
4. **Internal consistency** — today's findings take precedence; no two sections may
   contradict each other. Check this before finishing.
5. **Goals** — mark a goal MET only if today's data shows it achieved. When all
   short-term goals are met, the Plan must justify continued skilled care by reference
   to the remaining unmet long-term goals.
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
   interpret imperfect grammar charitably, and render clean professional clinical
   English without changing the facts. Unambiguous vocalized pauses (um, uh, hmm, and
   the like) are ALSO stripped deterministically before generation in
   `app/generate/prompt.py:clean_dictation` — a model-independent backstop applied at
   the single dictation chokepoint (so it also covers guided-mode assembled text).
   Tokens that collide with real clinical usage (`mm` = millimeters, `er`/`ER` =
   external rotation) are deliberately excluded from the strip and left to the prompt.
9. **Unique, non-boilerplate** wording every session, built from the specific details
   stated. Two sessions must not read the same.
10. **"Minutes: __" belongs in the section body, never the heading.** Headings must
    stay clean section/CPT names (e.g. "## Therapeutic Exercise"); a heading like
    "## Minutes: 20 Therapeutic Exercise" is wrong. State this explicitly in the
    output-format instructions — local models default to folding it into the heading
    if not told otherwise. **Now also enforced deterministically** by
    `postprocess.split_folded_headings`, which moves a folded heading's content down into the body
    and keeps "Minutes: N" together with its number — see rule 19's backstop list.
11. **MedGemma 4B reliably over-tags `[[CARRIED FORWARD]]` and invents empty
    "not performed" treatment sections, regardless of how explicitly the prompt
    forbids it** (confirmed across repeated runs with progressively more directive
    wording, including naming the exact allowed sections). This is a model-capability
    limit, not a prompt-wording bug — per the "isn't yet clinical grade" note above,
    don't keep burning effort on prompt rewording for this specific failure. Instead
    it is corrected deterministically in code, after parsing, in
    `app/generate/postprocess.py`: any section whose body opens with "Minutes: 0" is
    dropped (treated as not performed), and `[[CARRIED FORWARD]]` is stripped from any
    section whose heading isn't one of the form's real carry-forward labels
    (`app/generate/forms.py:CARRY_SECTION_LABELS`, matched bidirectionally since some
    forms' specs invite a collapsed heading like "Goals" instead of separate
    Short-Term/Long-Term headings). Keep this enforcement in place even if prompt
    wording improves later — it's a cheap, reliable backstop either way.
12. **Never let the model author a CPT or ICD-10 code.** Observed it confidently
    fabricate both for an MSK note where the dictation never mentioned any code or
    diagnosis classification — and the ICD-10 code it picked (M25.51, "pain in joint,
    pelvic region and thigh") didn't even match the stated condition (ankle sprain).
    Code assignment is a billing/coding judgment call for the clinician, never an
    inference target. Enforced deterministically in
    `app/generate/postprocess.py:flag_code_sections` — any section whose heading
    contains "CPT" or "ICD" always gets replaced with a `[[NEEDS: ...]]` marker,
    regardless of what the model wrote there. **CPT *suggestion* (added later, still
    honouring this rule):** the model still never authors a code, but outpatient PT CPT
    codes are a small closed set that maps 1:1 from the intervention the therapist
    explicitly named — the note's own treatment-section headings — so a DETERMINISTIC
    table (`app/generate/cpt.py:suggest_codes`, wired into `/api/generate` after the
    verification layer) attaches a confirmable `[[CPT: <code> <label> — confirm]]` marker
    to each treatment section. It also STRIPS any code the model wrote (the
    followup/progress/soappt specs literally ask for "cpt", so the 4B model sometimes
    emits one — and sometimes the wrong one; confirmed on a real run where it put "97110"
    in the heading), substituting the table's. Judgment-heavy cases are deliberately NOT
    auto-assigned: evaluation complexity (97161/2/3) is surfaced as a review flag for the
    clinician to pick, and units / the 8-minute rule / modifiers are left to the biller
    (payer-specific, high liability). The clinician confirms/edits/removes every code in
    the editable review step before signing — Cadence drafts codes, the clinician bills.
    ICD-10 stays banned entirely (open-ended, no safe deterministic map). The `[[CPT: ...]]`
    marker renders as a distinct blue "code" chip (vs the amber gap chip) in `app.js`.
    **NARROWED (2026-08) — ICD-10 is no longer banned outright, and billing is now also read from
    the DICTATION.** Three amendments, each deliberately as narrow as its justification:
    (a) **ICD-10 from a per-body-part CLOSED table only.** The original ban's reasoning —
    "open-ended, no safe deterministic map" — holds for ICD-10-CM as a whole (~70k codes) but not
    for a single body region's outpatient-PT differential, which is a closed set of ~8-14 codes the
    therapist names aloud as the referring/working diagnosis. **Six regions are covered — shoulder,
    knee, lumbar, cervical, hip, ankle/foot — and each is a SEPARATE closed table, not one merged
    list.** Adding a region is a data-only change (an `ICD_BY_BODY_PART` entry, a `BODY_PART_CUES`
    entry, a `TABLE_PROVENANCE` entry, and a phrase bank in `evals/synth/banks.py`); no logic in
    `billing.py`, `score.py`, `server.py`, or `app.js` changes, and the UI picker reads
    `BODY_PARTS` over the API. Two structural points that only appear once there is more than one
    region: `body_part_for` returns **None on a tie** rather than picking a winner, because a wrong
    table yields a confidently-wrong chip; and `IcdRule.lateralized` is False where ICD-10-CM gives
    one code regardless of side (most lumbar/cervical codes, plantar fasciitis), so no "confirm
    right or left" gap is raised for a distinction the code set does not make. Sign-off is
    **per region** (`TABLE_PROVENANCE`), so the practice can verify the regions it actually sees
    first and unverified ones stay visibly unverified. The narrowing is exactly that wide:
    `app/generate/coding_tables.py:ICD_BY_BODY_PART`, matched only inside a clause that FRAMES
    something as the diagnosis (`ICD_CONTEXT_CUES`) and never one that hedges it
    (`ICD_HEDGE_CUES`, so "worried about a rotator cuff tear" yields nothing), laterality taken
    only from what was said (unstated → the "unspecified" variant PLUS a gap flag, never a guessed
    side), all candidates returned and none auto-picked. **The model still never authors a code** —
    `postprocess.flag_code_sections` / `flag_code_field_lines` are unchanged and still strip
    anything it writes. The table carries `ICD10CM_YEAR` / `ICD_TABLE_VERIFIED_BY` /
    `ICD_TABLE_VERIFIED_ON`, and `tests/test_billing_extract.py` **FAILS while the latter two are
    blank** — a stale or unverified code rendered as a confident chip is worse than no chip, which
    is the exact failure this rule was written about.
    (b) **Scanning the DICTATION is permitted where scanning the NOTE is not.** The prohibition
    above is about the note's prose. The dictation carries the same class of risk through different
    failure modes — negation, prior visits, plans, home program, self-correction — so
    `app/generate/billing.py` guards it in four layers: clause-scoped matching (never a
    whole-transcript substring test), strong vs weak cue tiers (a technique name like "stretching"
    never bills on its own authority), a status enum (`performed | negated | prior_visit | planned |
    home_program | uncertain`) that EXCLUDES WITH A VISIBLE REASON rather than dropping, and
    `confirm_required=True` hard-coded and asserted on every path. **Policy on the asymmetry: a
    MISSED intervention is a safe failure the clinician adds back; a LEAKED negated or prior-visit
    one is an OVERBILL. Tune toward precision.** Measured by `distractor_leaks` in
    `evals/score.py`. This is not theoretical — the eval harness caught a real leak before ship
    (synthetic record 1021: "joint mobilization, I mean strength work" billed the RETRACTED
    treatment, because the self-correction check wrongly required the replacement phrase to also
    be a recognized cue).
    (c) **Units are computed, but never as a single number.** `billing.units_for_minutes` is the
    8-minute rule over TIMED codes only — the service-based modalities (97010, 97012, 97014, 97016,
    97018, 97022, 97024, 97150) and the 97161/2/3 evaluations are excluded via `cpt.TIMED_CODES`,
    because counting their minutes inflates the unit total. Since CMS substitution and the AMA rule
    of eights genuinely disagree (97110=8min + 97140=8min → 1 unit vs 2), BOTH are returned, each
    labelled with its method, and the disagreement is shown. This does not reopen "units are left
    to the biller" — it surfaces the arithmetic with its assumptions named, and the biller still
    decides. The draft is response metadata (`GenerateResponse.billing`), deliberately NOT a note
    section, so nothing above changes about what the model is allowed to write.
    **Confirmed on REAL generations (2026-08, MedGemma 4B, 3-record sweep), and the result is the
    argument for the whole design:** on 2 of 3 notes the model folded the section CONTENT into the
    `## ` headings and left EVERY body empty (8/14 headings over 80 chars, longest 339) — which per
    `evals/score.py:MAX_HEADING_CHARS` silently no-ops the ENTIRE rule-20 verification layer, since
    it inspects `body` only. **Billing was nonetheless 100% correct on those same notes** (CPT 3/3,
    minutes 3/3 exact, units exact, zero leaks), because it is derived from the DICTATION and never
    from the note. This is why `_billing_draft` is also computed on the `parse_plain is None`
    early-return path: the billing draft is the one part of the pipeline that survives the model
    ignoring its output contract. The same run also showed the two code sources earning their
    keep — the model titled a section "## Simulated Overhead Painting Task", which
    `cpt.suggest_codes` cannot match to 97530 by heading, so the note-side chip was missing
    entirely while the dictation-side extraction found it and `billing.reconcile` raised it as a
    `dictation_only` rule-15 omission.
    **(d) Two more leaks, both found by a hand-written control the day it was written (2026-08,
    `evals/data/longform_intake.txt`), and both in the same sentence pair.** The therapist said
    "we did not do any manual therapy today and I did not do any electrical stimulation", then a
    sentence later "I considered functional electrical stimulation for the left dorsiflexors but I
    want to check with the surgeon first". 97014 was **billed as performed**.
    * **Contemplating a treatment is not performing it.** "Considered" was not a recognised
      exclusion cue, and the "planned for a future visit" that followed sat in a LATER clause, so
      clause scoping — correctly — never saw it. Fixing the scope would have widened it for
      everything; the fix belongs on the verb. `TEMPORAL_FUTURE_CUES` gained a deliberation family
      ("considered", "thinking about", "pending", "may add", …). Same shape as the rule-21(b)
      noun-form fix, and the same safe direction: a future cue can only move a treatment OUT of
      the billable set.
    * **An explicit negation must not be silently outvoted.** The negation WAS detected correctly
      and then discarded, because `_dedupe` keeps the most billable mention of a code. Two mentions
      that contradict each other cannot be resolved automatically, so the code now drops to
      `uncertain` carrying BOTH clauses, and the clinician decides. Blanket "negation wins" would
      be wrong too — "no manual therapy at first … later we did fifteen minutes" is real — so the
      answer is to stop guessing, which is what the status enum exists for.
    The 162-record corpus was unchanged by both (zero leaks before and after), which is the point:
    this class only appears in speech nobody thought to generate.
13. **Carry-forward reconciliation ("update, don't copy") is not reliable for every
    section, even when the prior snapshot and today's data are both available in the
    prompt.** Confirmed case: a real second-visit test (used_prior: true, snapshot
    correctly populated) where Gait Training correctly reflected today's updated
    values (300ft, no device, independent stairs) but Functional Status — the
    section this exact behavior is named for — punted with
    `[[NEEDS: ambulation distance, assistive device, stair climbing]]` instead of
    synthesizing the update, despite the same information being available both in
    the carried snapshot and in today's dictation. This is a *safe* failure (no
    fabrication, no stale/contradictory data shown, and the gap marker still renders
    visibly via the UI's amber-highlight styling even when it doesn't also make it
    into the structured missing-list array) but it is a real shortfall against the
    feature's core value proposition. Don't assume reconciliation works reliably
    just because it worked in an earlier test — it's inconsistent run to run.
14. **Residual hallucination risk beyond what's been deterministically fixed**: in
    the same MSK test, the model also invented a specific assistive device ("ambulates
    with a cane") and specific pain ratings ("4/10 at rest, 5/10 with movement") that
    were never stated, with no prior-note context to have leaked from (MSK doesn't
    carry forward). No general-purpose code fix catches arbitrary invented prose the
    way the structural fixes above catch tag/heading/code patterns — this is exactly
    why clinician review of every note is a non-negotiable constraint, not a
    nice-to-have. Don't treat the postprocess fixes in this file as having solved
    fabrication risk generally; they've only closed the specific, structural failure
    modes observed so far.
15. **Complete extraction — never silently drop a stated fact (require mode).** Every
    clinical fact the therapist states must appear somewhere in the note: every
    medication with its dose, every diagnosis/PMH item, prior therapy, living
    environment, code status, every goal, every measurement, every plan value.
    Dropping a stated fact is as serious as inventing one. A dictated 11-medication
    list and most of a PMH were dropped — and the root cause was often that the
    template had **nowhere to put the content**: the Initial Evaluation template had
    no Medications, Allergies, Social History/Living Environment, clinical-complexity,
    discharge/transition, or participation fields, so no prompt rule could have saved
    them. Fix the template first (audit its sections against a real note), then the
    prompt. Enforced by the expanded `templates/initial.md` sections + the completeness
    paragraph in `MODE_RULE_REQUIRE` (`app/generate/rules.py`). When a required field
    genuinely wasn't stated, flag it — don't invent it.
16. **Output/context ceiling caused silent truncation and a thin transcript tail.**
    `num_ctx` was 4096 with no `num_predict`; a long (~20-minute) dictation plus the
    full template and rules overflowed it, so Ollama dropped the tail of the transcript
    AND cut the note off mid-sentence (observed ending: the dangling fragment
    "Certification period"). Raised to `num_ctx=8192` + explicit `num_predict=3072` in
    `app/generate/ollama_client.py`. This is not a prompt problem — no rule wording
    fixes a dropped context window. For a genuinely huge dictation that still overflows
    8192, the right fix is chunked/two-pass generation (fill the template in labeled
    passes), NOT an ever-larger single context — a 4B model's attention over a very
    long context degrades, giving the tail the least attention. **Now implemented** in
    `app/generate/chunked.py` (`fit_dictation`), wired into `/api/generate` before
    `build_prompt`: if the dictation would overflow the budget (`num_ctx - num_predict -
    prompt-scaffold`), it is split at sentence boundaries and each chunk is rewritten by
    the same local model into clean, fact-preserving prose, then the concatenation feeds
    the normal pipeline. **Conservative by construction:** a normal-length dictation is
    returned unchanged with zero extra model calls (byte-identical normal path, verified
    by a real run reporting `condensed=False`), so only a genuinely huge dictation takes
    the new route — trading the old SILENT truncation for a condensed pass plus a visible
    "verify completeness" flag appended to the missing-info list. Caveats (per rules
    14/15): the condense pass is itself a 4B call and could drop a fact, and verification
    still anchors against the RAW dictation so a condense-introduced value with no basis
    is flagged.
    **NOW VALIDATED (2026-08), and the validation failed the feature. Two things were wrong, and
    the second is the interesting one.** `scripts/validate_longform.py` runs a hand-authored
    2,363-word intake (`evals/data/longform_intake.txt`) with a 78-fact ledger tagged head / mid /
    tail, as an **A/B against the silent truncation condensing replaces** — because the claim is
    comparative, and a one-armed run could only ever say "the condensed note is imperfect", which
    was never in dispute.
    (a) **The threshold was documented wrong by nearly 2x.** The budget is not `num_ctx`, it is
    `num_ctx - num_predict - the prompt scaffolding` — for an Initial Evaluation, ~2,255 tokens,
    about **1,350 words or a ~10-minute dictation**. `chunked.py` claimed "a ~20-minute dictation
    already fits". It does not: a real long-form intake measures 1.60x over. Condensing is a
    ROUTINE path for a full evaluation, not the rare escape hatch it was written as.
    (b) **The condense pass did its stated job and made the note far worse.** Raw **59/78** facts;
    condensed **18/78**, in double the time (29.6 min vs 15.3). Yet the condensed TEXT retained
    **73/78** — the facts were all still there. The cause was one clause in the condense prompt:
    "do NOT format it as a note — just clean sentences". A therapist dictating a long intake
    SIGNPOSTS it out loud ("Medications." … "Cervical range of motion, active." … "Short term
    goals, four weeks."), and flattening that into narrative removed the only map the 4B writer
    has. It produced 5 sections instead of 18 and lost the entire middle and tail. The prompt now
    requires those spoken labels to be preserved, one per line, in order.
    **The transferable lesson: fact retention is not the objective, RECOVERABLE fact retention is.**
    A preprocessing step can score 94% on content and still destroy the note, and no
    content-only metric would show it. This is also why the A/B framing matters — graded alone,
    18/78 reads as "imperfect, as the caveats said"; against 59/78 it reads as "ship the
    truncation instead".
    (c) **The fix for (b) made it fabricate, and THAT is why condensing is now OFF BY DEFAULT.**
    Rewriting the condense prompt to preserve the therapist's spoken section labels worked — the
    labels and their lists came back intact. Underneath one of them, the model had rewritten the
    CONTENT. Five specific dictated short-term goals ("patient will ambulate three hundred feet
    with a rolling walker and supervision only"; "improve Berg Balance Scale to forty five out of
    fifty six") came back as five generic ones ("Improve balance and reduce fall risk"; "Improve
    ability to ambulate safely"). Every number gone, every goal invented, in a passage that reads
    perfectly professional.
    **Nothing in Cadence can catch that.** `traceability` flags values in the NOTE that are absent
    from the DICTATION — here the note ends up with FEWER values, not invented ones, so no flag
    fires. It is rule 14's "arbitrary invented prose" class, introduced by a second model call the
    clinician never sees, upstream of every guard. Truncation is the strictly better failure: it
    loses the tail VISIBLY and it cannot invent.
    So `chunked.CONDENSE_ENABLED` defaults to False (`CADENCE_CONDENSE_LONG_DICTATION=1` re-enables
    it for an experiment), an over-budget dictation takes the raw path, and `_finalize_note` now
    warns on `still_over` whether or not condensing ran — "part of it was not seen ... check every
    section, especially the beginning and end, or split the visit into two shorter dictations."
    The silent case, which is what this rule was written about, is still impossible.
    **The general principle, which is worth more than this feature:** a preprocessing step that
    RE-WRITES clinical content puts a model call upstream of every verification layer, where by
    construction nothing can check it. Cleanup that DELETES on a matched pattern
    (`clean_dictation`'s vocalized pauses) is safe because the deletion is bounded and inspectable.
    Cleanup that PARAPHRASES is not, at 4B, on clinical content.
    **Next thing to try, and it is the option this rule originally rejected:** raise `num_ctx` so a
    long-form intake simply fits (3,599 + 2,865 + 3,072 needs ~9.5k; 12288 would do it) and delete
    the second pass entirely. The rejection was "a 4B model's attention over a very long context
    degrades" — true, but the raw arm ALREADY feeds a 6,464-token prompt and scores 76%, so
    degraded attention is measurably the cheaper problem. It costs KV-cache memory on a box that
    is already swapping (`docs/performance-tuning.md`), so measure it there before adopting it.
    Re-measure with `scripts/validate_longform.py` after ANY change to the condense prompt, the
    rules, or a template — the last of those moves the budget. `--condense-only` scores the
    intermediate for half the runtime.
17. **Spoken-artifact cleanup beyond fillers (prompt-level; clinician review still
    required).** The transcript also carries dictated *checklist* answers ("Patient
    worries about falling, yes"), garbled ASR passages, and self-contradictions that
    must not pass through raw. The prompt now instructs: convert checklist answers to
    declarative sentences (never emit "..., yes"/"..., no" or a question+answer);
    repair garbled ASR into clear clinical English, marking truly-unrecoverable text
    `[[NEEDS: unclear dictation "..." — clinician to confirm]]`; and on a
    self-contradiction or two-values-for-one-field ("no known allergies except sulfa";
    two visit frequencies) record the standard value and append `[[NEEDS: dictation
    also stated "..." — clinician to confirm]]` rather than reproducing both. These are
    prompt-only mitigations — there is no safe deterministic rewrite for arbitrary
    spoken prose — so, like rule 14, they lean on clinician review, not a guarantee.
    All such flags reuse the `[[NEEDS: ...]]` marker because that is the only form the
    UI renders in amber (`app/ui/static/app.js`); a bare `⚠` would show as plain text.
    **One narrow, bounded piece of this IS backed by code:** the checklist *affirmation*
    "..., yes" is the only structurally-detectable, meaning-safe half, and the 4B model
    echoes it verbatim regardless of the prompt (observed six times in one real Fall Risk
    section, duplicated into the Objective Summary). A statement-final ", yes" is
    therefore stripped deterministically in
    `app/generate/postprocess.py:strip_checklist_affirmations` (bounded to end-of-statement
    position so it never touches a mid-clause "..., yes, and ..."). The *negation* half
    "..., no" is deliberately left prompt-only — dropping it would silently invert
    clinical meaning ("unsteady, no" ≠ "unsteady") — and so remains a best-effort
    mitigation plus clinician review, exactly like garbled-ASR repair and conflict
    flagging above.
18. **Map values by meaning, standardize notation, don't duplicate across sections.**
    (a) Map plan-of-treatment values by content, not the spoken label: Frequency =
    visits/week, Duration = total weeks, Intensity = minutes/session — so "duration
    sixty minutes" is Intensity, not Duration. (b) Write MMT strength grades in standard
    notation ("3+/5", ranges "3+/5 to 4-/5"), not spelled out — and, because the model
    routinely echoes the spoken long form, this one is ALSO enforced deterministically
    in `app/generate/postprocess.py:normalize_strength_grades` (bounded to a denominator
    of five so it can never touch a pain rating like "4 out of 10"). (c) Each section is
    written in its own words at its own level of detail (Objective Summary = brief
    overview; the detailed sections carry the full findings) — never paste identical
    TUG/MMT/ROM sentences into several sections (verbatim duplicates are now also flagged
    deterministically — rule 20(e)). (d) Every section ends on a complete
    sentence with its full stated value; a stated label ("Certification period") is
    always followed by its value. All prompt-level, in `WRITING_RULES_LEAD`.
19. **Completeness must not become confabulation — the model fills empty exam sections
    with invented normals.** Confirmed on a real Initial Eval generation run (not a unit
    test) after the rule-15 template expansion: for sections the dictation never
    addressed, the model wrote unstated findings — "ROM limited... decreased flexion and
    extension", "Skin intact. Neurological exam unremarkable. Cognitively intact.",
    "O2 at rest and with activity normal", and "Coordination intact. Sensation intact.
    No edema noted." The forceful rule-15 completeness wording ("dropping a stated fact
    is as serious as inventing one") was over-read by the 4B model as "every section must
    be filled." Countered in the prompt (`MODE_RULE_REQUIRE`) by stating explicitly that
    completeness means every STATED fact appears, NOT that every section is filled, and
    that asserting an unstated normal/negative exam finding ("intact", "unremarkable",
    "within normal limits", "no edema", "O2 normal") is fabrication exactly as serious as
    dropping a stated fact — such a section must be omitted or flagged
    `[[NEEDS: not documented]]`, never filled with a fabricated normal. **UPDATE (see rule
    20):** the original "no safe structural signal" claim here was too strong. You can't tell a
    stated-normal from an invented-normal by the *assertion text* (a real "sensation intact" is
    indistinguishable from an invented one) — but you don't need to: you check whether the
    dictation mentions that body SYSTEM at all. `traceability.flag_unsupported_normals` now
    deterministically flags any normal exam finding whose system the dictation never mentions,
    which catches exactly this empty-exam-section case. It flags (never deletes) and can still
    miss a normal for a system that WAS mentioned but with a different finding, so per rule 14
    clinician review remains the backstop. Note
    that on the same run the other prompt-only mitigations (rule 17 checklist "..., yes"
    cleanup; rule 18(c) no-cross-section-duplication; rule 17 dictated-conflict flagging)
    each failed at least once, so treat every prompt-only rule on this model as
    best-effort and re-verify with a REAL generation, never unit tests alone.
    **Directly observed across three real runs of the identical dictation with no prompt
    change between them:** the empty-exam-section behavior OSCILLATED — one run correctly
    wrote "Not documented"/"not detailed in the dictation" for the untouched sections, the
    next regressed to fabricated "intact"/"no edema"/"O2 normal"; the checklist "..., yes"
    artifact appeared once in one run and six times (duplicated across two sections) in the
    next; and the discharge-plan restatement and "community mobility not tested" line were
    present in two runs and dropped in a third. This run-to-run nondeterminism (temp 0.3)
    IS the takeaway: a prompt fix lowers the *frequency* of a failure class, never its
    *risk*. The corollary that earned its own proof this session: the deterministic
    backstops (num_ctx anti-truncation, MMT shorthand, checklist "..., yes" strip,
    CPT/ICD flagging, carry-tag/zero-minute enforcement) held on 100% of runs, while every
    prompt-only rule fluctuated — so when a failure class is a detectable, meaning-safe
    pattern, move it into `postprocess.py`; reserve prompting for the classes that have no
    safe mechanical rewrite (arbitrary invented prose, cross-section paraphrase, meaning
    inversion), and lean on clinician review there.
    **A second 2026-08 addition is `postprocess.strip_spec_instruction_headings`** — the model
    copying the template's field INSTRUCTION onto the heading line (`## Precautions — weight-bearing
    status, range-of-motion limits, and any other precautions still in effect.`) with correct
    clinical content in the body underneath, on 2 of 6 real Follow-Up generations. It is the HEADING
    twin of `flag_template_echo`, which only ever inspected bodies, and `split_folded_headings`
    cannot cover it: that repair requires an EMPTY body and MOVES text, which is right for content
    and wrong for boilerplate that belongs in neither the heading nor the body. It matters past
    looking machine-made on a note a payer reads, because `cpt.code_for_heading` matches the
    HEADING, so instruction text naming an intervention could earn a chip for a treatment nobody
    performed. This is the ONE place in `postprocess.py` that DELETES rather than flags or moves,
    and only because the removed text is matched against the form's own `spec` — verbatim template
    boilerplate, never anything the clinician said. An unmatched tail is left alone. It runs before
    the fold repair, or an instruction on an empty-bodied heading gets relocated into the body where
    nothing removes it.
    **The 2026-08 addition to that backstop list is `postprocess.split_folded_headings`** — the
    model writing a section's CONTENT on the `## ` line and leaving the body empty, measured on
    2 of 3 notes in a real sweep (8/14 headings over 80 chars, longest 339). It was the worst
    failure of this class precisely because it was INVISIBLE: `traceability.add_verification_flags`
    inspects `body` only, so the entire rule-20 layer silently no-opped while the note scored clean
    on every other invariant — and `app.js:renderEditView` gives a textarea only for the body, so
    the content was not even correctable by the clinician. Text is MOVED, never rewritten. Since
    the repair now runs at the same threshold `evals/score.py` checks, that invariant went
    permanently green, so `folded_headings_raw` counts the fold on the RAW parse BEFORE the repair
    — otherwise a worsening model would be silently absorbed.
20. **Local verification layer — deterministic hallucination flags in the note**
    (`app/generate/traceability.py`, run in `/api/generate` after postprocess via
    `add_verification_flags`). Appends amber `[[NEEDS: ...]]` markers for two model-independent
    fabrication classes so the clinician's eye is drawn to them before signing; works identically
    on any model — five fabrication/quality classes:
    (a) **Unanchored clinical values** (`flag_unanchored_in_sections`) — a value in the NOTE
    (pain X/10, MMT X/5, minutes, ROM degrees, ambulation distance) that does not appear in the
    dictation → probable fabrication. `normalize_for_matching` bridges spoken↔written forms
    ("four out of ten"↔"4/10", "one hundred twenty degrees"↔"120 degrees", and MMT ranges "three
    plus to four minus out of five"↔"3+/5 to 4-/5" — the spoken denominator distributes to BOTH
    grades; getting that wrong false-flagged a real dictated range on a live run, now a locked
    regression test).
    (b) **Unsupported normals** (`flag_unsupported_normals`) — a NORMAL exam finding ("skin
    intact", "sensation intact", "no edema", "O2 normal") about a body system the dictation never
    mentions → the invented-normal class of rule 19. Keyword-anchored per system with broad stems
    so a differently-phrased real normal ("no swelling" for edema, "alert and oriented" for
    cognition) still anchors and isn't false-flagged. Matches synonyms too ("integumentary" for
    skin — a real-run miss now covered).
    (c) **Unsupported vitals** (`flag_unsupported_vitals`) — a BP/HR/O2 value in the note whose
    vital TYPE the dictation never mentions. Type-mention, not value-matching, because spoken idioms
    ("one thirty over eighty") don't normalize to "130/80"; HR/O2 require an actual value so an
    honest "HR: Not stated" is never flagged (a real-run regression), and the BP pattern rejects
    "12/08/2026" so a note date isn't misread as a blood pressure.
    (d) **Invented assistive devices** (`flag_unsupported_devices`) — a cane/walker/crutches/
    wheelchair/rollator named in the note whose head noun the dictation never mentions (rule 14's
    "ambulates with a cane"); negated mentions ("without a cane") are skipped.
    (e) **Cross-section paste-duplication** (`flag_cross_section_duplication`) — the same substantial
    sentence (>= 8 words) repeated near-verbatim across 2+ sections (rule 18c); only exact long
    sentences, since brief summary overlap is by design. Style/non-boilerplate flag, not a fabrication.
    (f) **Fabricated pain-slot scores** (`flag_unanchored_pain_fields`) — a rigid "Worst/Best/Current:
    /10" pain template (the block `initial_updated`) pressures the 4B model to FILL the slots even
    when no score was dictated (observed: a real note invented "Worst 10 / Best 10 / Current 10" for a
    dictation that named pain locations but no numbers). Catches the bare field form ("Worst: 10") that
    (a) misses because it only sees written "N/10"; flags a Worst/Best/Current value whose "N/10"
    equivalent isn't in the dictation.
    All FLAG, never delete — a genuinely dictated value/normal/device is indistinguishable from an
    invented one in text (rules 14/19), so these are hedged "verify" aids leaning on the
    non-negotiable clinician review, not rewrites. Confirmed on real generations: one flagged
    invented skin/neuro/O2/sensation/coordination normals (leaving dictated cognition and a
    "edema not documented" alone); a second flagged an invented cane/walker goal and a fabricated
    40-minute session intensity, and surfaced the two edge cases fixed above. All flags reuse
    `[[NEEDS: ...]]` because that is the only marker the UI renders in amber.
    **(g) The NORMALIZER was wrong in three ways, and two of them produced FALSE flags on
    correctly-transcribed values** (2026-08, found by the long-form control before a single note
    was generated — the ledger's self-check against its own source transcript failed 4/78, which
    is what a ruler that checks itself is for). All three are spoken forms a PT uses constantly:
    * **"one thousand feet" → "1 thousand feet".** `thousand` was not a scale word, so a perfectly
      ordinary community-distance goal did not match the note's "1000 feet" and the `distance`
      pattern flagged it as fabricated. A false amber flag on a real value is worse than a miss —
      it teaches the clinician to skim past the flags that matter.
    * **"point six eight" → "point 14".** The parser SUMMED the digits after "point", so a
      dictated gait speed normalized to a number nobody said, and the note's honest "0.68 meters"
      had nothing to anchor to. Spoken decimals are read digit by digit now.
    * **"one thirty eight over eighty two" → "39/82".** The colloquial hundreds form summed to 39.
      No live false flag (rule 20(c) had already routed vitals around value-matching for exactly
      this reason) but the normalizer was inventing a number, which no downstream consumer should
      inherit. Now scoped to the "<value> over <value>" idiom on BOTH sides, because that is the
      only place the reading is unambiguous — "one thirty" alone is a clock time as often as a
      pressure.
    **Deliberately NOT done:** now that spoken BPs normalize, rule 20(c)'s reason for type-matching
    vitals instead of value-matching them is weaker, and a `\d{2,3}/\d{2,3}` value pattern would
    catch a fabricated BP or a fabricated Berg/SCIM score — a real fraud-risk class that is
    currently invisible. It was left out because only the two commonest idioms are covered, a note
    re-composing a value differently would false-flag, and rule 24's lesson is that a measurement
    which manufactures findings is worse than no measurement. Add it WITH a real-note measurement,
    not on the strength of the argument.

21. **Synthetic evals measure the extractor, not the world — keep the non-circular control.**
    `evals/synth/` generates labeled dictations LABEL-FIRST (draw the diagnosis, interventions,
    minutes and units, THEN render speech expressing them), seeded per-sample so a corpus is
    deterministic and growing it never rewrites earlier records. Ground truth is therefore exact by
    construction, and no LLM's guess ever becomes a gold label. **But the generator and the
    extractor share an author**, so a synthetic-only score can sit at 100% while both are wrong
    about how a real therapist talks. Three things keep that honest, and none is optional:
    (a) `evals/synth/banks.py` deliberately includes PARAPHRASES the cue table does not know
    ("hands-on work", "functional activities", "strength work"). A sample using one is still
    labeled with the correct code, so the extractor genuinely misses it and recall genuinely drops
    — that gap is the signal. Do NOT "fix" a low recall by copying paraphrases into
    `coding_tables.INTERVENTION_CUES` without first deciding whether the phrase is unambiguous
    enough to bill on.
    (b) The 8 hand-written `evals/data/shoulder.jsonl` records stay as the control, and their
    billing gold fields must be labeled BY HAND — never by running the extractor and accepting its
    output, which would make the measurement perfectly circular. **The control immediately earned
    its cost**: on its first run it caught three defects the synthetic corpus could not, because
    the generator only ever renders phrasings it was given —
    (i) a FOUR-CODE OVERBILL on record 108, where "Interventions **planned** include therapeutic
    exercise, neuromuscular re-education, manual therapy, and therapeutic activities" billed all
    four as performed, because every `TEMPORAL_FUTURE_CUES` entry was a VERB form ("plan to",
    "will add") and a real evaluation note used the NOUN form;
    (ii) a false-positive ICD (M25.512) from a HISTORY clause, because "history of" was a
    diagnosis-CONTEXT cue, so a four-year-old symptom became a billable diagnosis; and
    (iii) a missed ICD on a post-surgical header ("ten weeks post left SLAP repair, type two
    labral tear"), which carried no recognized diagnosis context.
    All three are fixed with regression tests. **The current gold labels were hand-read from the
    transcripts by Claude, NOT by the clinician** — `gold_provenance.verified_by` in the JSONL is
    still blank and must be filled by the clinician or a coder before these numbers mean anything
    clinically. One known remaining gap is deliberate: record 106 states its diagnosis as a bare
    header phrase ("Follow up, ..., left shoulder impingement, week two") with no framing at all,
    and is left unmatched rather than loosening the context rule — a missed ICD is a safe failure,
    a false one is a claim.
    (c) `evals/results.py` reports every aggregate three ways — `synthetic`, `handwritten`, `all`.
    Reading only `all` hides the comparison. **The DIRECTION of the gap is the diagnosis, and the
    two directions mean opposite things:**
    *synthetic scoring HIGHER* is the circularity failure — the generator taught the extractor its
    own vocabulary and the score is measuring that agreement rather than the world.
    *synthetic scoring LOWER* means the generator is stress-testing harder than reality, which is
    the intended state and is where the corpus currently sits (2026-08: synthetic CPT 86% billed
    vs hand-written 100%, because `banks.py` deliberately speaks paraphrases the cue table does not
    know while a real therapist mostly says the service's own name).
    The two sets are complementary, not redundant, and neither replaces the other: the synthetic
    corpus stresses **vocabulary** (unknown phrasings for a known service), and the hand-written
    control stresses **structure** (how minutes, negations, and post-op framings are actually
    spoken — "we spent about twenty-five minutes on", "held off on the e-stim", "she's four weeks
    out from"). Every defect found so far came from the structural axis, which is exactly the axis
    a template generator cannot probe.
    Same spirit as rule 19's "re-verify with a REAL generation, never unit tests alone": a green
    eval is evidence, not proof.
    **The ICD half of this was CIRCULAR for a while and nobody noticed** — worth knowing because it
    is the easiest mistake to repeat. `_draw_diagnosis` picked the spoken diagnosis with
    `rng.choice(rule.cues)`, straight out of the extractor's OWN cue list, so ICD recall read 100%
    across 144 records while measuring nothing but that the extractor recognizes the strings it was
    told to recognize. The CPT side had had a deliberate paraphrase gap all along; the ICD side had
    no equivalent. Adding `banks.DIAGNOSIS_PARAPHRASES` (real wordings the table does NOT know)
    dropped honest recall to **79% — and to 9% on paraphrased samples**. After admitting the
    unambiguous ones it is **92% with 0 false positives and 0 laterality errors**.
    **The rejections are the interesting half.** A paraphrase is only admitted if it NAMES the
    diagnosis; a SYMPTOM with several causes is left unmatched on purpose — "heel pain" (fat pad,
    calcaneal stress fracture, Sever's), "anterior knee pain", "lateral hip pain" (bursitis vs
    gluteal tendinopathy), "stiff shoulder" (M25.61 stiffness vs M75.0 capsulitis). The sharpest is
    **"PF", which means plantar fascia to a foot therapist and patellofemoral to a knee therapist**
    and can never be safely expanded. Two of these had been written into the generator as gold
    LABELS, which is worse than a missing cue: labelling a symptom with one specific diagnosis
    scores a correct extraction as a failure and creates pressure to admit an unsafe cue. Same
    class as the "quad tendon irritation" bug (the quadriceps and patellar tendons are different
    structures). **When honest recall looks low, check the gold labels before touching the cue
    table.**
    (d) **Read the ERROR DIRECTION, not just the accuracy percentage.** "units exact 57%" reads
    alarming and is nearly meaningless on its own; the number that carries billing risk is
    `units_overstated` (0 across 162 records), because over-counting is an overbill while
    under-counting is a safe gap the clinician fills from the visible missing-minutes flag. The
    same split applies to detection: `cpt_detection_recall` (87%) is what Cadence bills without
    asking, `cpt_surfaced_recall` (100%) is what it bills OR raises for confirmation, and the gap
    between them is clinician work rather than error. A metric that hides direction invites the
    wrong fix — chasing "units exact" upward would mean auto-billing ambiguous phrases, which is
    exactly the trade rule 12 forbids.
    **The sharpest instance of this, worth internalising:** `units_exact` sat at 56% on the
    synthetic corpus, which reads like broken arithmetic. It was not. In every failing record the
    code WAS detected, the minutes WERE extracted exactly, and the only thing standing between the
    draft and the gold answer was a confirmation click on a weak-cue line. `units_exact_if_confirmed`
    is **100% across all 162 records** — the unit math has never once been wrong. The 56% was
    measuring the weak-cue policy wearing an arithmetic label. Hence `BillingDraft.units_if_confirmed`,
    computed server-side (never in JavaScript — the 8-minute rule lives in ONE place, the same
    reason `TIMED_CPT` was deleted from `app.js`) and surfaced in the review card as "confirming
    the lines above would add N timed min → X units instead of Y", so the clinician sees the
    consequence of the click rather than a number that silently under-reports.

22. **Clinician corrections are captured, and the only trainable corpus is the synthetic one.**
    Two halves, and the second is a hard constraint rather than a preference.
    (a) **Capture.** Every clinician correction used to be destroyed: `app.js` wrote edits into the
    section body in place, and the "Ask for changes" instruction — the clinician saying in their own
    words what was wrong, the highest-signal correction data the app sees — was never persisted at
    all. The `notes` table now stores `original_sections_json`, `revise_instructions_json`,
    `edited_section_count`, and generation provenance (`model_id`, `template_spec_sha`, …). **NULL
    means "not captured" and 0 means "accepted as generated"** — a `NOT NULL DEFAULT 0` on the edit
    count would make every pre-capture note look blindly-accepted and destroy the exact signal being
    built. This is real patient content: it stays in the encrypted row, is deliberately NOT on the
    HTTP read surface, and `tests/test_correction_capture.py` enforces that no export path exists.
    (b) **Training.** There is no GPU on either machine (dev box `torch+cpu`; target ThinkPad has
    Intel UHD 620), a 4B QLoRA needs 10-16 GB VRAM, so training is NECESSARILY off-device — and
    off-device is a third party that is not Google Workspace. **Therefore the only trainable corpus
    Cadence can ever have is `(synthetic dictation → clinician-corrected note)`. Real corrected
    notes can inform prompt rules, backstops, and measurement; they can never be training data.**
    That does not change if the corpus grows or a deadline tightens — it follows from where the
    compute lives. The `synthetic` column exists so a future export must filter `WHERE synthetic=1`
    at the SQL level rather than trusting someone to remember which patient was fake. Full recipe,
    including why deterministically-rendered targets are the wrong shortcut (they teach templated
    prose, violating rule 9, and are circular per rule 21): `docs/finetune-when-viable.md`.

## Standing workflow instruction

When a generated note is wrong, **fix the underlying prompt/logic so that entire class
of mistake is prevented going forward** — do not just patch the single note. Add the new
correction to the rules above so it persists.

## Conventions

- The prototype is the behavioral reference for UX and note quality; preserve its
  proven behavior when rebuilding into the real app.
- Keep per-form generation prompts fixed and tested, not ad hoc. **Templates are now
  runtime-editable** (a "Templates" tab in the UI + `/api/forms/{id}/template` endpoints):
  a clinician can view every form's outline large/readable beside the dictation box, edit
  a built-in's outline (stored as a spec-only *override* in `templates/overrides/`, leaving
  the shipped `templates/*.md` pristine and one-click resettable), and create/duplicate/
  delete their own **custom templates** (full files in `templates/custom/`). The template's
  outline body *is* the generation spec (`FormSpec.spec` → `build_prompt`), so an edit changes
  what the model is told to produce — clinician review still applies. The store lives in
  `app/generate/forms.py` (`create_custom_template`/`duplicate_template`/`edit_template`/
  `reset_template`/`delete_custom_template`/`reload_forms`); `FORM_ORDER` stays the fixed
  BUILT-IN set, custom templates append after it via `ordered_form_ids()`. Custom templates
  are **always non-carry** in v1 (carry-forward needs per-form `CARRY_SECTION_LABELS` +
  `carry_forward.CARRY_FIELD_HEADING_MAP` wiring only the built-ins have). Guided `steps`
  are still authored only in the built-in frontmatter (a duplicate copies them; created-from-
  scratch templates have none and simply get no guided mode).
- The prototype's demo cloud path has been removed (it no longer calls any model). Keep
  it that way: the prototype must never make outbound model calls or touch real data.
- **Input modalities (reference: Twofold AI).** Twofold offers four ways to get a session
  into the tool — (1) type rough notes directly, (2) upload a recording, (3) dictate a session
  summary, (4) live in-session capture — and it's a good UX template for Cadence's input surface.
  Each maps to a LOCAL implementation (Cadence never sends audio or text off-device); all four now
  exist. (1) free-text dictation box; (2) **audio-file upload** ("Upload audio" → `/api/transcribe`,
  `setupAudioUpload`); (3) mic → MedASR (`setupDictation`); (4) **live in-session capture**
  (`setupLiveCapture` in `app.js`) — continuous, hands-off recording of the whole visit,
  auto-chunked into ~3-min segments each transcribed locally by a **single serialized MedASR
  worker** (one pass at a time, to respect the CPU-only budget), accumulating into the dictation
  box; recording never blocks on transcription (segments queue and drain in the background). The
  borrowed idea is the input *flexibility*, never the cloud architecture — every mode stays fully
  on-device.
  **Live-capture v1 limits (documented, not bugs):** no **speaker diarization** — the transcript
  mixes clinician + patient, so it's a rougher input to generation than a dictated summary (the
  clinician reviews/edits the transcript before Generate, and the rule-19/20 verification flags
  still run); CPU transcription can lag a long session (bounded only by queue memory); and a
  recorded visit needs the patient's **consent** (surfaced in the UI copy). Speaker attribution and
  chunked *generation* for very long transcripts (rule 16) remain future work.
- **Generation is queued, not awaited** (rule 26). `POST /api/generate/jobs` returns immediately;
  the "Notes in progress" tray under the nav is visible from every tab and is how the clinician
  tracks a note while doing something else. One serialized worker, an append-only buffer read by
  cursor so a reload reattaches, in-memory only (an unreviewed draft never touches the encrypted
  store), and a queue POSITION rather than an invented ETA. `/api/generate/stream` and
  `/api/generate` both still exist and share `_generation_setup`/`_finalize_note` with the queue,
  so the three paths cannot drift.
- **Guided dictation** (the Home dictate card's "Guided" mode) walks the clinician
  through the selected form one section at a time, each with a concrete example,
  because a static "what to mention" list couldn't tell them which of a dense form's
  ~14 sections *this* dictation was missing. The per-section content lives in each
  template's `steps:` frontmatter (`label` + `example` + optional flag), parsed into
  `FormSpec.steps` (`app/generate/forms.py`). **Invariant: `steps` are a dictation aid
  only and must NEVER enter the generation prompt** — `build_prompt` uses `form.spec`
  exclusively; `tests/test_forms_guide.py` locks this in. Guided mode is a pure input
  helper: it assembles the answered sections into the normal free-text dictation and
  hands off to the same `/api/generate` pipeline (the model still structures the note
  and the after-generate gap-flagging still catches skips) — it does not map fields
  directly or change model behavior. Free dictation remains the default mode.

23. **Three more ICD narrowings, and the reason each is narrow (2026-08, 1,440-case sweep).**
    Rule 12(a) opened ICD-10 to per-body-part closed tables. Running long-form (~1,000-word)
    evaluation dictations against it found three ways a closed table still emits a wrong claim.
    Each fix is deliberately as narrow as its justification, all in `billing.py:detect_icd`.
    (a) **Code the diagnosis, not its symptoms.** A long dictation names the SYMPTOM repeatedly
    ("Chief complaint, … shoulder pain"; "Assessment summary, patient presents with shoulder pain")
    while the diagnosis is stated once, so a generic pain code rode along on nearly every eval —
    **152 false positives, ICD precision 64%**. ICD-10-CM says code the established diagnosis and
    not its symptoms; billing M25.512 alongside M75.41 is a duplicate claim line. `IcdRule` gained
    `symptom_only`, set on the 10 pain/stiffness rules, and they are dropped when a definitive
    diagnosis is also found — but **kept when the symptom is all the therapist gave**, because then
    it is the only honest code available. Precision 64% → 90% from this alone.
    (b) **Mutually exclusive variants can't both be true.** M48.062 (stenosis WITH neurogenic
    claudication) and M48.061 (WITHOUT) were both emitted for one patient. The per-clause `break`
    cannot catch it: a long dictation states the diagnosis more than once at different precision —
    the full phrase in the referral, the bare phrase in the assessment — which is two clauses and so
    two codes. `IcdRule.family` marks variants exclusive; the first match wins, which is the most
    specific because rules are ordered that way.
    (c) **A side mentioned in the transcript is not the diagnosis's side.** The laterality fallback
    scanned the WHOLE dictation. Defensible at 35–120 words, where a lone side mention almost
    certainly was the diagnosis; a ~1,000-word intake states a side constantly in places that say
    nothing about the diagnosis ("right straight leg raise negative"), and the fallback promoted the
    first — turning an unspecified sciatica (M54.30) into a confident right-sided claim. Rule 12
    already said an unstated side yields the unspecified code plus a gap flag, **never a guess**;
    the transcript-wide fallback simply was one. The fix is a WINDOW, not diagnosis-clauses-only: a
    side is often a bare fragment beside the diagnosis carrying no context of its own ("Left knee.
    Diagnosis is degenerative knee."), and scoping to diagnosis clauses alone silently dropped it —
    caught by an existing test. A neighbour donates a side only if it is a bare fragment (≤ 5
    words); a full adjacent sentence is about its own subject, and borrowing from it moves the bug
    one clause over rather than fixing it. That last case was found by a test written for the fix,
    not by the corpus.
    Net across 1,440 cases / 5 seeds: **zero CPT false positives, zero laterality errors, zero
    distractor leaks, zero overstated units; ICD precision 99.2%, recall 97.0%.** The 12 remaining
    ICD false positives are all the DESIGNED rule-21(a) paraphrase-gap fallback — none standalone.
    Those paraphrases stay rejected on purpose: **"new hip" collides with "new hip pain"** (recent
    onset, not a replacement — a false Z47.1 aftercare claim), "pulled his back" straddles sprain
    S33.5 and strain S39.012, and "turned his ankle" is a mechanism, not a diagnosis.

24. **The note WRITER now has a scored harness too — and a measurement tool can fabricate findings.**
    `scripts/audit_notes.py` measures generated notes against the dictations that produced them,
    checking the two directions that matter and are deterministically checkable, with **no LLM
    judge** (which would be circular per rule 21): **DROPPED** (a stated fact the note doesn't
    carry — rule 15) and **INVENTED** (a fact the note asserts that the dictation never stated —
    rules 14/19). Medications are the probe: a closed, explicitly-stated list of proper nouns that
    either appear in the source or don't, no paraphrase question, and the exact failure rule 15 was
    written about. Structural and fabrication counts call the SAME functions the pipeline runs, so
    the audit cannot drift from the app. First run over 18 real MedGemma notes: **61 medications
    named, 61 traceable, 0 invented, 0 dropped; 0 folded headings; 8 invented assistive devices, all
    caught by the rule-20 layer** (rule 14's "ambulates with a cane" recurring in 6 of 6 follow-ups).
    The medication result is the rule-15 intake work confirmed end-to-end — the same pipeline used
    to write "Ibuprofen 400mg, twice daily" for a dictation naming no drug at all.
    **The process lesson is worth more than the numbers.** Getting there took three corrections to
    the AUDIT itself, and its first "honest" reading was **15 dropped medications** when the true
    answer was **0**: the `flag_*` functions return the whole section list rather than a findings
    list (so every fabrication column read the section count); requiring a NUMERIC dose scored three
    notes that had carried every medication perfectly ("Levothyroxine eighty-eight micrograms
    daily") as having dropped all of them, measuring dose FORMAT and reporting it as lost facts; and
    requiring a capital initial missed drugs written mid-list in lowercase. A metric that
    manufactures alarming findings about the thing it exists to reassure you about is worse than no
    metric. **Verify a new measurement against a case you have read by hand before believing it** —
    the discipline rule 21(b) applies to gold labels, applied to the ruler.

25. **When a score looks wrong, suspect the generator before the cue table.** Ten ICD false
    positives across three regions traced to `evals/synth/intake.py` hardcoding "patient presents
    with {part} pain" in the assessment summary — a diagnosis-FRAMING clause — so a patient whose
    diagnosis was *stiffness* had a pain diagnosis in their transcript. The extractor read it
    correctly and was scored a false positive for doing the right thing. The tempting fix (loosen
    or special-case the cue table) would have damaged a component that was already correct. This is
    rule 21's "check the gold labels before touching the cue table" recurring on the RENDERING side
    rather than the label side, and it is why the sweep prints the spoken diagnosis beside every
    mismatch — a bare count of false positives would have sent the fix to the wrong file.

26. **The 1–2 minute generation budget is unreachable on this hardware, so the WAIT was removed
    instead of the minutes.** Measured: median 7.0 min over 21 real generations, 21 of 21 over
    budget, floor set by a 91-word follow-up. This file previously floated three fixes; two of them
    do not survive the measurement, and knowing why saves someone re-trying them:
    * **"Cut `num_predict`."** 3072 is a CEILING, not a target. A note is ~1,200–2,500 tokens, so
      the ceiling never binds — lowering it would truncate long notes before it saved a second.
    * **"Generate per-section."** The same total output tokens through more prompts, and each
      section would lose the whole-note context that internal consistency (rule 4) depends on.
    Time is output-tokens ÷ tok/s, and both are already near their floor (see
    `docs/performance-tuning.md`: the biggest lever is free RAM, not config). So the third option is
    the real one, and it is a PRODUCT change rather than a speed one: **generation moved off the
    request into a server-side queue** (`app/generate/jobs.py`, `POST/GET/DELETE
    /api/generate/jobs`). The clinician starts a note, walks to the next patient, dictates that one
    too, and reviews both at the end of the block; a "Notes in progress" tray under the nav shows
    every note queued, writing, or waiting for review, from any tab. Design points that are
    load-bearing rather than incidental:
    * **ONE worker, strictly serialized.** Two 4B generations on 4 CPU cores run twice as slowly
      each and double the memory pressure that is the actual bottleneck. Same reason live capture
      uses a single serialized MedASR worker.
    * **The buffer is append-only and read by CURSOR**, so closing the tab, switching patients, or
      reloading reattaches to a running note. The old `/api/generate/stream` tied a note's life to
      one HTTP connection; it still exists for tooling and for watching a single note write.
    * **Jobs are in memory and die with the server, deliberately.** A generated note is an
      unreviewed draft, and persisting unreviewed model output beside signed records is the wrong
      place for it. The queue survives the browser, which is the case that happens.
    * **The tray shows a queue POSITION, never an ETA.** Throughput on this box swings with
      whatever else is open, so a minutes estimate would be a number Cadence cannot stand behind.
    * Switching patients DETACHES the live tail (the job keeps running) — streaming patient A's
      note into a view headed by patient B is how a note gets reviewed against the wrong chart.

27. **Template conformance is now measured, and it caught the wrong form being worried about.**
    This file spent a long section on `initial_updated`'s block format being the risky one. Scored
    against the 25 stored real generations (`docs/synthetic-run-outputs-full.json`) with the new
    `scripts/audit_notes.py` conformance metric — did the note produce the sections its template
    actually named? — the ranking inverts:
    **`initial_updated` 28/28 = 100% (7 runs). `initial` 225/238 = 95%. `followup` 25/40 = 62%.**
    The block form is the *best behaved* of the three; the field-per-section Follow-Up is the worst,
    and it drops exactly the sections that matter most — `Summary of Daily Skilled Services`
    (replaced by an invented `## Follow-Up Visit` title), `Plan`, and the CARRY-FORWARD labels
    `Precautions` / `Short-Term Goals` / `Long-Term Goals` that `CARRY_SECTION_LABELS` depends on.
    Treat the block-vs-field tradeoff section above as history: it is still the reason the forms are
    shaped as they are, but it is no longer where the risk lives. Two lessons:
    (a) A structural worry recorded once tends to outlive the evidence for it. Re-measure before
    acting on one — the fix for `initial_updated` would have been work spent on the healthy form.
    (b) The metric had to be verified against notes read BY HAND before being believed (rule 24).
    Its first two versions were wrong in opposite directions: filtering spec lines by instruction
    WORDS silently dropped two real sections whose guidance text contained "NEVER", and an
    unanchored `## ` regex matched the `"## "` inside the specs' own prose. Both would have made a
    conforming note look broken.

28. **A folded heading does not need a separator, and the ones without one were invisible.**
    Rule 19's `split_folded_headings` repairs `## Vitals — BP: 120/80` (em dash) and long prose
    headings. Measuring the 4 real Follow-Up notes above found the same fold with **no punctuation
    at all** — `## Vitals 122/76`, `## Vitals 72 bpm, 78/45`, `## Pain - At Rest 1/10`,
    `## Therapeutic Exercise 20 minutes`, every one with an EMPTY body — on 3 of 4 notes. Same
    consequences as rule 19 describes and for the same reason: `traceability` reads bodies only, so
    a blood pressure on the heading line is never checked against the dictation, and
    `renderEditView` gives a textarea only for the body, so the clinician cannot correct it either.
    The repair now recognises the boundary by the VALUE rather than by punctuation: a heading whose
    tail starts a measured quantity, with a legitimate label in front of it. Across all 25 real
    runs this took empty bodies from 8 to 3, and every remaining one is genuinely empty or carries
    a non-numeric value. **`## Response to Treatment Good` is deliberately NOT repaired** — "Good"
    is a value to a reader but not a mechanically detectable one, and a rule that split on a
    trailing adjective would start cutting real labels in half. Same discipline as rule 17's
    refusal to strip a checklist ", no": when the safe half is separable, take only that half.

29. **Shipping: the program and the clinician's data are different things, and updates are where
    that stops being philosophy.** Until v1.0 Cadence was one folder with the encrypted database
    sitting inside it next to the code. Installing a new version alongside the old one breaks that
    immediately — the database is either stranded in the previous version folder or a fresh empty
    one appears and the clinician opens Cadence to an empty roster. So `app/paths.py` splits them:
    `CADENCE_DATA_DIR` holds storage / the clinician's templates / credentials, outside every
    version folder. **Unset, every path is byte-identical to what it was** — that is why a checkout
    and all 716 tests are unaffected, and it is deliberate, because a data-location change that
    silently moved a patient database would be the worst possible bug in that file.
    The install layout, and the reason for each part:
    `versions/<v>/` (replaced wholesale), `data/` (never touched), `current` → a directory
    JUNCTION, not a symlink, because Windows creates junctions without administrator rights and an
    update the clinician cannot run is not an update. `current` is repointed LAST, so an
    interrupted update leaves an unused folder rather than a half-broken install.
    Built-in templates ship WITH the code and an update should replace them; only overrides and
    custom templates are the clinician's. `schema.sql` likewise travels with the code — a version's
    migrations are part of that version.
    Three refusals matter more than the happy path: the updater will not run while the app is open
    (reusing the DATABASE LOCK rather than inventing a second liveness check that could disagree
    with it), `scripts/release.py` will not build from a dirty tree or a version that is already
    tagged, and the release zip is an ALLOWLIST — a denylist that misses one entry ships a patient
    database, and `tests/test_release_packaging.py` asserts both directions (nothing sensitive in,
    the app itself not accidentally excluded out).
    **There is no auto-update.** An update changes what notes SAY — a prompt rule, a backstop, a
    template — so the clinician reads what changed, in clinical language, and decides. Verified end
    to end on a simulated install: a patient created under 1.0.0 was visible from 1.0.1, and the
    note still carried `app_version = 1.0.0`, which is the point of stamping it.

30. **The billing gate is COMPUTED, not configured.** `cpt.billing_enabled()` returns False while
    any ICD region is unverified, so v1.0 ships with CPT/ICD suggestions hidden and a Status line
    saying why — and turns them on by itself the moment the last region is signed off. A flag
    someone has to remember to set is a flag someone forgets. The failing sign-off test protects
    the developer; this protects the clinician, and only one of those still works after the code
    leaves this machine. `CADENCE_BILLING=on|off` overrides it for development and the eval
    harness, and the gate lives at the SERVER boundary so `billing.extract` / `cpt.suggest_codes`
    stay pure and the harness keeps measuring the extractor regardless.

31. **"Ask for changes" — rewrite the section, not the note. Measured 3/5 → 4/5 applied, 4 damaged
    sections → 0, minutes → seconds.** The whole-note rewrite asked a 4B model to re-emit ~2,000
    tokens to change one line; on a real 14-section note it returned the note byte-identical twice
    in five, and one "successful" revision DELETED FOUR SECTIONS and reworded four more. Collateral
    drift in a clinical note is worse than a missed edit — the clinician asks to reword the
    assessment and the medication list quietly changes. Scoping fixes it structurally rather than
    by instruction: only the named section is sent and returned, everything else is spliced through
    byte-identical, so the model **cannot** reword what it never saw. Selection is deterministic
    (`select_revise_sections`) and REFUSES on a partial match, because editing the wrong section is
    worse than editing them all; structural requests (merge / reorder / move) still take the
    whole-note path, since a per-section splice cannot change which sections exist.
    **Three prompt failures were measured, not guessed, and each is now a test:**
    (a) leading with the formatting rules and burying the change made the model echo the section
    back unchanged; the change now comes LAST and says the body MUST DIFFER;
    (b) a "here are the other section names, for context, do not output them" block was echoed
    VERBATIM into the answer — it guarded a speculative problem and caused a measured one;
    (c) a prompt ending in prose gets CONTINUED like prose, so it now ends on a bare
    `REVISED SECTION:` cue, which turns the task from "continue this document" into "fill this in".
    The general lesson is about the loop, not the prompt: going from a 4-minute whole-note revision
    to a 20-second scoped one is what made three iterations affordable in the time one measurement
    used to take. **Cheap feedback is a correctness feature.**

32. **The Follow-Up conformance defect (rule 27) had ONE root cause, and it disabled a feature one
    visit later.** On 3 of 4 real Follow-Up generations the model turned the template's own TITLE
    LINE into a section heading:
    `## Follow-Up Visit` / body `Precautions [carry forward] — weight-bearing status…`
    That does two things at once. It invents a section nobody asked for, and it CONSUMES the real
    first one — "Summary of Daily Skilled Services" vanishes and the Precautions content is filed
    under a heading that is not Precautions. **`Precautions` is a carry-forward label**, so
    `CARRY_SECTION_LABELS` stops matching it and the NEXT visit has nothing to carry forward. A
    heading bug that looks cosmetic silently switches off carry-forward one visit downstream, which
    is why "the note still reads fine" is not a sufficient test.
    The good run of the four echoed the same title line as PLAIN PROSE and then got everything
    right, which is what identified the title line as the trigger rather than the template's shape.
    Three repairs, all anchored on labels the template itself declares
    (`forms.spec_section_labels` — ONE definition, now shared with `audit_notes.py`, because two
    copies would let the app and the thing measuring the app disagree about what the template asked
    for):
    (a) `relabel_spec_title_heading` — a heading equal to the form's ALL-CAPS title whose body
    OPENS with a declared label is relabelled to that label. Anchored twice, so it can only rename
    a section the template named. When the body reveals no label it is left alone: a miss is
    recoverable, a wrong relabel files clinical content under the wrong heading.
    (b) `split_shifted_section_bodies` — the same shift continues down the note
    (`## Pain - At Rest 1/10` whose body is `Pain - With Movement 4/10`), so the following
    section does not exist at all. Splitting it out also leaves an empty body, which is exactly
    what `split_folded_headings` then repairs — the two chain, and that is why the order in
    `apply()` matters. Guarded by "that section must be ABSENT": a Plan body opening
    "Short-Term Goals will be reassessed…" is prose, and the giveaway is that Short-Term Goals
    already exists.
    (c) `split_declared_label_headings` — rule 28's fold repair cannot see
    `## Response to Treatment Good`, because "Good" is a value to a reader and nothing to a regex.
    The declared label makes it tractable. Guarded against a label CONTINUATION, or
    "Plan of Treatment" would split into a "Plan" section whose body is "of Treatment".
    **Measured over the same 25 real notes: Follow-Up conformance 62% -> 75%, empty bodies 3 -> 2,
    `initial` and `initial_updated` unchanged at 95% and 100%.** The remaining Follow-Up gaps are
    genuine model omissions (it stops before Plan and the goals), not mislabelling — a different
    problem, and one no relabelling can fix. n=4 is still a thin sample; generate more with
    `scripts/eval_corpus.py --form followup` before concluding anything about the residual.

33. **A 41% "stated-value capture" that was mostly a harness misuse, and underneath it a real
    rule-15 template gap.** Running the 8 hand-written shoulder controls with
    `--form followup` reported that only 41% of dictated values reached the note. Alarming, and
    largely not a generation defect:
    (a) **Three of those eight records are Initial Evaluations**, and `--form followup` forced them
    through the Follow-Up template. An evaluation dictation is dense with range-of-motion and
    strength values, and the Follow-Up outline had NO section for either — so those values had
    nowhere to go by construction. Splitting the two apart: genuine follow-ups captured **57%**,
    the forced evaluations **19%**. This is rule 25's lesson recurring one level further out —
    suspect the harness INVOCATION, not just the generator or the cue table. `eval_corpus.py` now
    prints a warning naming the records whose derived form `--form` overrides, and that warning
    sits BEFORE the `--no-generate` early return, because the first version of it was placed after
    and so never fired for the very command that motivated it.
    (b) **The residue is real, and it is a TEMPLATE problem, not a prompt one.** Of the 22 values
    genuine follow-ups dropped, **15 were ROM or MMT — values the outline could not hold** — and
    only 7 had a section available. That is exactly rule 15's documented root cause ("the template
    had nowhere to put the content, so no prompt rule could have saved them. Fix the template
    first"). `templates/followup.md` gained an **Objective Measures** section (and a matching
    guided-dictation step, or the walkthrough would march the clinician straight past the thing the
    section exists to capture). On the same corpus that should take genuine-follow-up capture from
    57% to roughly 86% — **a projection, not a measurement; re-run the sweep before quoting it.**
    **BOTH CHANGES WERE THEN REVERTED — see rule 35.** The Objective Measures section shipped in
    the same sweep as the rule-32 prompt roster, the pair regressed section coverage from 93% to
    47%, and neither could be individually convicted. The rule-15 gap described here is REAL and
    still open; the fix has to be re-attempted on its own.

34. **A clock that counts while the laptop sleeps made the one performance metric useless.** On
    Windows both `perf_counter` and `monotonic` keep counting through SUSPEND, so a sweep left
    running overnight recorded a single generation as 84,715 seconds — 23 hours — and dragged the
    reported mean from **324s to 10,873s**. That is the difference between "5.4 minutes a note,
    matching the documented median" and "3 hours a note", on the exact number rule 26 uses to argue
    about whether Cadence is usable between patients. Nobody would have believed 3 hours; the
    damage is that it makes the metric ignorable, and an ignored metric cannot report a real
    regression either.
    `evals/runner._timed` now excludes an implausible wall-clock from the mean and COUNTS the
    exclusions, so a sweep can never quietly discard most of its own timings. Zero is reported
    separately from implausible, because a `--no-generate` sweep legitimately has no timing and
    calling that "the machine slept" would be the harness asserting something false about itself.
    Same defect, same session, in `scripts/validate_revise.py` — worth assuming any elapsed-time
    measurement in this repo has it until checked. **The general form: a measurement taken across
    an interval the process does not control needs a plausibility bound, and the bound belongs
    next to the metric rather than in the reader's head.**

35. **Two plausible fixes, shipped together, made it worse — and the metric that improved was the
    one that mattered less.** Rule 32 added a template-derived SECTION ROSTER to the prompt
    ("every one of these must appear, in this order… the final section is Plan; do not stop
    early") and rule 33 added an OBJECTIVE MEASURES section to the Follow-Up template. Measured on
    the same 5 real records, before and after:
    | | before | after |
    |---|---|---|
    | stated-value capture | 57% | **65%** |
    | template section coverage | **93%** | **47%** |
    Three of five notes stopped after the treatment sections — no Plan, no Goals, no Functional
    Status. **A note missing its Plan is not improved by containing more measurements**, so the
    value-capture gain is a trap, not a trade. Both changes are reverted;
    `prompt._section_roster_rule` is kept UNUSED with the result in its docstring, and
    `tests/test_section_recovery.py` asserts the revert so re-enabling it fails loudly.
    Two lessons, and the second is the expensive one:
    (a) **Change ONE thing per measurement.** Shipping both together means neither is individually
    convicted, so the honest outcome is to revert both — including the one that might have been
    fine. That is the cost of a confounded experiment, paid in work already done.
    (b) **A checklist may make a small model stop sooner, not later.** The plausible mechanism
    (untested): naming the required sections gives a 4B a short concrete list to satisfy, and it
    satisfies the front of it and stops. Telling it "do not stop early" appears to do less than
    implying there is a finite list it can finish. Same family as rule 19's finding that forceful
    completeness wording was over-read into inventing normals — directive prompt text on this
    model reliably produces a literal reading nobody intended.
    **What SURVIVED is the deterministic half.** Rule 32's three postprocess repairs are unaffected
    by any of this — they run after generation, cannot change how many sections the model writes,
    and are still measured at 62% -> 75% conformance with carry-forward restored. When a
    prompt-side idea and a code-side one address the same failure, the code-side one is the one
    that keeps working.

---

## Where things stand, and the honest next steps (as of 2026-08-24)

Written so a cold session can pick up without re-deriving any of it. **Re-verify the dates and
numbers before trusting this** — if the git log has moved well past `ef517ac`, treat this section
as history rather than status.

### What is BUILT (feature inventory)

Everything below is implemented and working locally unless marked otherwise. Sections above this
one carry the reasoning; this is the flat list.

**Input — four modalities, all on-device** (`app/ui/static/app.js`)
- Free-text dictation box (the default).
- Mic dictation -> local MedASR (`setupDictation`, `/api/transcribe`).
- Audio-file upload (`setupAudioUpload`).
- Live in-session capture (`setupLiveCapture`): continuous recording, auto-chunked into ~3-min
  segments, a single serialized MedASR worker so the CPU budget holds; recording never blocks on
  transcription. v1 has NO speaker diarization and needs patient consent — both documented, not bugs.
- **Guided dictation**: walks the clinician through the selected form section by section with a
  concrete example each. Content lives in each template's `steps:` frontmatter. Invariant: `steps`
  are an input aid and NEVER enter the generation prompt (`tests/test_forms_guide.py`).

**Generation** (`app/generate/`)
- MedGemma 4B via Ollama, CPU-only, `num_ctx=8192` / `num_predict=3072` (rule 16).
- The template's outline body IS the generation spec, so editing a template changes the prompt.
- `chunked.fit_dictation` condenses an over-long dictation at sentence boundaries; a normal-length
  one is returned byte-identical with zero extra model calls.
- `prompt.clean_dictation` strips vocalized pauses deterministically at the single chokepoint.
- **Deterministic postprocess backstops** (`postprocess.apply`, in order): carry-instruction heading
  strip -> `strip_spec_instruction_headings` -> `split_folded_headings` (long headings, em-dash
  folds, AND separator-less value folds — rule 28) -> zero-minute section drop -> `enforce_carry_tags`
  -> `flag_template_echo` -> `flag_code_sections` / `flag_code_field_lines`
  -> `normalize_strength_grades` -> `strip_checklist_affirmations`.
- **Verification layer** (`traceability.add_verification_flags`), six fabrication/quality classes:
  unanchored clinical values, unsupported normals, unsupported vitals, invented assistive devices,
  cross-section paste-duplication, fabricated pain-slot scores. All FLAG, never delete.
- **Carry-forward** for Follow-Up Visits, with a body-scan fallback so it survives block-format or a
  model regression that folds a note.

**Billing** (`billing.py`, `cpt.py`, `coding_tables.py`) — the model never authors a code
- CPT suggestion from the note's own treatment HEADINGS (deterministic table).
- CPT + ICD extraction from the DICTATION, guarded four ways: clause-scoped matching, strong/weak
  cue tiers, a status enum (`performed | negated | prior_visit | planned | home_program |
  uncertain`) that excludes with a visible reason, and `confirm_required=True` on every path.
- ICD-10 from **six per-body-part closed tables** (shoulder, knee, lumbar, cervical, hip,
  ankle/foot), matched only in a diagnosis-framing clause, never a hedged one; laterality only from
  what was said; symptom codes suppressed when a definitive diagnosis exists; mutually exclusive
  variants collapsed; body part resolved from the diagnosis clause when the transcript ties.
- **8-minute rule units over TIMED codes only**, returning BOTH CMS substitution and the AMA rule of
  eights with the disagreement shown, plus `units_if_confirmed`.
- `billing.reconcile` cross-checks the note against the dictation and raises `dictation_only` gaps.
- Billing is response metadata, never a note section, and is computed even when the model returns
  an unparseable note.

**Templates** (`forms.py` + Templates tab) — runtime editable
- 3 built-ins (`initial`, `initial_updated`, `followup`); create / duplicate / edit / reset /
  delete; built-in edits stored as spec-only overrides so shipped files stay pristine.

**Storage** (`app/storage/`)
- Fernet-encrypted SQLite, decrypt-to-temp on start / re-encrypt on write.
- Cross-process PID lock + `(mtime, size)` staleness guard — two writers would otherwise be
  last-writer-wins over the WHOLE database.
- `synthetic` column on patients AND notes so demo rows are precisely removable.
- **Correction capture** (rule 22): `original_sections_json`, `revise_instructions_json`,
  `edited_section_count` (NULL = not captured, 0 = accepted as generated), plus generation
  provenance. Write-only; deliberately NOT on the HTTP read surface.

**UI** (`app/ui/`)
- Patient roster, per-section review and edit, nothing persisted until Save.
- **"Notes in progress" tray** (rule 26) — visible from every tab; queue position, live elapsed
  time, Watch / Review / Cancel, and a toast when a note finishes while the clinician is elsewhere.
- Amber gap chips (`[[NEEDS: …]]`) and blue code chips (`[[CPT: …]]`).
- **"Copy for Office Ally"** — buckets any note's sections into Subjective/Objective/Assessment/Plan
  for one-click paste.
- Templates tab; Evals tab (run sweeps, read recorded results).

**Evaluation and QA**
- `evals/synth/`: label-first seeded generator, 6 regions, short follow-ups AND ~1,000-word
  long-form intakes (`intake.py`), with a DELIBERATE paraphrase gap so recall stays honest.
- 18 hand-written control records — the only non-circular check (gold labels still unverified).
- Scored harness + timestamped results store + `eval_compare.py`; `--no-generate` records a
  billing sweep in seconds with no model call.
- `scripts/audit_notes.py`: measures generated notes against their dictations for DROPPED and
  INVENTED facts, no LLM judge — plus TEMPLATE CONFORMANCE (rule 27), which is what caught the
  Follow-Up form dropping its carry-forward sections.
- `scripts/validate_longform.py` + `evals/data/longform_intake.txt` / `_ledger.json`: a
  hand-authored 2,363-word intake with a 78-fact ledger tagged head/mid/tail, run as an A/B
  (raw vs condensed) so rule 16 is measured against the truncation it replaces rather than
  graded alone. The ledger self-checks against its own transcript before scoring anything.
- **633 tests.**

**Ops / tooling**
- `launcher.py` (desktop shortcut), `setup.ps1`, `scripts/backup.py` (now with a `restore
  --dry-run` rehearsal — an untested backup is not a backup, and testing one used to mean
  overwriting the live database), `scripts/seed_demo_data.py`, `scripts/verify_pipeline.py`,
  `scripts/verify_transcription.py`, `scripts/validate_quality.py`.
- `scripts/coding_signoff.py`: prints the ICD/CPT sign-off worksheet a coder can actually work
  from, and records a completed sign-off per region (`--sign <region> --by … --on …`). The tables
  live inside a Python module, so "please review the codes" used to mean "please read
  coding_tables.py", which is not a request you can make of a coder.
- `scripts/verify_sheets.py`: preflights the Sheets sync and names the failing setup step (API not
  enabled / Sheet not shared / wrong tab / wrong header) instead of surfacing a stack trace in a
  background poll. Read-only.
- Google Sheets roster sync — code-complete, **blocked** on Cloud project permissions.

### What is measured and green

- **682 tests, exactly one failing**, and that one fails on purpose: the billing sign-off gate.
- **Billing extraction**, 1,440 synthetic cases over 5 seeds: ICD precision **99.2%**, recall
  **97.5%**; CPT precision **100%**, auto-billed 84%, surfaced 100%. **Zero** CPT false positives,
  laterality errors, distractor leaks, fabricated minutes, or overstated units.
- **162-record corpus** (`scripts/eval_corpus.py --no-generate`, seconds, no model needed):
  synthetic ICD r92%/p100%, hand-written control ICD r93%/p100%, CPT 100%/100% on the control.
  Per rule 21(c) the synthetic set scoring BELOW the control is the intended direction. Unchanged
  by the two rule-12(d) billing fixes, which is the point — that class of leak only shows up in
  speech nobody thought to generate.
- **Note generation**, 18 real MedGemma notes via `scripts/audit_notes.py`: 61 medications named,
  **61 traceable, 0 invented, 0 dropped**; 0 folded headings; 8 invented assistive devices, all 8
  caught by the rule-20 layer.
- **Template conformance** (rules 27/32), 25 stored real generations: `initial_updated` **100%**,
  `initial` **95%**, `followup` **75%** (was 62% before the rule-32 postprocess repairs). The
  prompt-side attempt at the same problem was measured WORSE and reverted — rule 35.
- **Generation time**, corrected: mean **324s (5.4 min)** per note on the dev box. The harness had
  been reporting 10,873s because its clock counted through a machine suspend (rule 34). Across the same 25 notes / 324 sections, the rule-28 fold
  fix took empty bodies from **8 to 3**, and every remaining one is genuinely empty or holds a
  non-numeric value.
- 9 sweeps recorded in `evals/results/` and visible in the Evals tab.

**And one thing that measured RED, which is the more useful result** — see rule 16 and
`evals/results/longform/`. Rule 16's condensing path had never been run on a real long dictation.
Run as an A/B against the silent truncation it replaces, it made the note dramatically WORSE:
**18/78 facts vs the raw path's 59/78, in double the time** — and the rewritten prompt that fixed
that then FABRICATED, turning five specific dictated goals into five generic invented ones.
**Condensing is now off by default and an over-budget dictation is flagged instead.** A feature can
be correct at its stated job (73/78 facts survived the condense pass) and still be net harmful, and
only an A/B shows that — grading the condensed note alone would have read as "imperfect, as
documented".

### The three things that actually matter next

**1. Nothing here has met a real user, and that is now the binding constraint.** Every number above
is self-referential: a corpus written by the same author as the extractor, scored against gold
labels hand-read by that author. The 18-record hand-written control is the only non-circular check
and shares the same author. **One real dictation from the clinician, on the target ThinkPad, run
end to end, tests more than another 10,000 synthetic cases** — MedASR against a real voice and a
non-native accent, how a PT actually structures speech, note quality, and the UX, all at once.
Every structural defect found this session came from the hand-written control precisely because a
template generator cannot invent phrasings nobody gave it. Do this before writing more eval code.

**2. Generation time — ADDRESSED, but the fix needs confirming on the ThinkPad.** The old text
here asked for a product decision between a queued background job, a smaller `num_predict`, and
per-section generation. Rule 26 records why the last two do not survive the measurement and what
was built instead: generation now runs in a server-side queue with a "Notes in progress" tray, so
the clinician starts a note and walks away rather than waiting seven minutes. **The minutes did
not change** — that is the honest framing. What changed is that they are no longer the clinician's
minutes. Still to do: run it on the target i5-8365U, which is slower than the box every number
here came from, and confirm the tray reads well when three notes are queued behind each other.

**3. The ICD tables are unverified, which blocks billing entirely — but the ask is now a
worksheet, not a code-reading exercise.** Six regions (~70 codes) plus
all 18 control records: `TABLE_PROVENANCE.verified_by` and `gold_provenance.verified_by` are blank
everywhere. `tests/test_billing_extract.py` fails while they are, deliberately, so it cannot be
forgotten. **This is still not a code task** — it needs a certified coder or the clinician with the
ICD-10-CM tabular list. Until then every chip is one author's reading of the codebook, and rule 12
exists because a confidently-wrong code is worse than no code.

What DID change is that the ask is now deliverable. `python scripts/coding_signoff.py --out
signoff.md` prints a printable worksheet: every code with its label, its laterality variants, the
exact dictation phrases that trigger it, and three questions per row in the order they cause harm.
It also lists what is deliberately excluded and why. When a region passes,
`--sign <region> --by "<name, credential>" --on <date>` records it, per region, so the practice can
start billing shoulder and knee while the regions it rarely sees stay visibly unverified. Before
this, "please review the codes" meant "please read `app/generate/coding_tables.py`", which is not
a request you can make of a coder — the blocker was partly a tooling gap wearing a domain-expertise
costume. **Send the worksheet.**

### What to STOP doing

**The synthetic billing sweeps are saturated.** 99.2% precision, and all 12 remaining false
positives are the BY-DESIGN rule-21(a) paraphrase gap ("new hip" must keep colliding with "new hip
pain"). More seeds now measure less. Resist the pull of another harness improvement over getting a
real dictation — that is avoidance wearing the clothes of rigor. Worth remembering as a caution:
`scripts/audit_notes.py` shipped with three bugs of its own and its first "honest" reading was 15
dropped medications when the true answer was 0 (rule 24).

### Loose ends, ranked

1. **Follow-Up notes still stop early.** Rule 32 fixed the MISLABELLING half (62% -> 75%
   conformance; `Precautions` is recovered on every affected note, so carry-forward works again).
   What remains is different in kind: the model simply stops before `Plan`, `Short-Term Goals` and
   `Long-Term Goals` on some runs, and no relabelling can fix an omission. Candidates, in the order
   I would try them: the treatment sections are unbounded and may be eating the output budget
   before the tail is reached; the spec's title line may still be steering it (echoing that line
   as prose correlated with the one clean run); or the goals belong earlier in the outline.
   **n=4 is far too thin to choose** — generate more first with
   `scripts/eval_corpus.py --form followup --limit 8`, score with `scripts/audit_notes.py`.
2. **Demo roster is 3 of 18.** Re-run `scripts/seed_demo_data.py` (`--clear` first to avoid
   duplicating the 3), ~90 min, and **close the app first** — the lock in `app/storage/db.py` will
   refuse otherwise, which is the point.
3. **Google Sheets sync** is code-complete but blocked on Cloud project permissions
   (`docs/google-sheets-sync-setup.md`). `scripts/verify_sheets.py` will name the exact failing
   step the moment someone picks it up again.
4. **The backup routine has never been exercised on the TARGET machine.** It now has been on the
   dev box, against the real encrypted store: verify → backup → verify → list → `restore
   --dry-run`, all green. Run the same five commands on the ThinkPad, to a real USB drive.

**Closed since the last write-up:** rule 16 validated on a real long transcript (and the feature
turned OFF as a result — item 2 of the old list; the follow-up is the `num_ctx` experiment rule 16
now describes); `initial_updated`'s block format measured clean at
100% conformance, so the old item 3 was a worry about the wrong form; generation time addressed by
the queue (rule 26); the coding sign-off turned into a worksheet.

The single next action, if only one: **record one real session on the ThinkPad and run it through.**
It will reorder everything above it. Nothing in this session changed that — every number here is
still self-referential, produced by the same author as the thing it measures, and the defects that
mattered most were all found by the one hand-written control rather than by any amount of
generated corpus.
