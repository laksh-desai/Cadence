"""
Generation rule text, originally ported from cadence-prototype.html's buildPrompt()
(lines 433-470) and modeRule branches (lines 433-439). The WRITING_RULES_LEAD
transcript-handling bullet has since been revised for spoken input — the prototype
was typed FAKE data, whereas the real app's dictation is a raw MedASR speech-to-text
transcript with spoken fillers/disfluencies. Wording must not drift from
docs/note-rules.md / CLAUDE.md without updating all three in the same change.
"""

MODE_RULE_REQUIRE = """COMPLETENESS (require mode):
  - Every clinical fact the therapist stated MUST appear somewhere in the note: every medication with its dose, every diagnosis/PMH item, prior therapy, living environment, code status, every goal, every measurement, and every plan-of-treatment value. Dropping a stated fact is as serious an error as inventing one. If a stated fact does not fit a named section, put it in the closest relevant section rather than omitting it. Do NOT summarize a long list (medications, diagnoses, goals) down to a few items — list them all.
  - Completeness means every STATED fact appears — it does NOT mean every section must be filled. If the therapist said nothing about a section's findings (commonly the exam sections: range of motion, skin/integumentary, neuromuscular, cognition, cardiopulmonary/O2, coordination, sensation, edema), do NOT assert a normal or negative result you were not told — never write "intact", "unremarkable", "within normal limits", "grossly normal", "no edema", "O2 normal", or the like unless the therapist actually said it. Asserting an unstated exam finding is fabrication, exactly as serious as dropping a stated one. For such a section, either omit it or write only [[NEEDS: not documented]] — never a fabricated normal to fill the space.
  - Only the sections and fields explicitly listed in the NOTE STRUCTURE above are REQUIRED (their absence is what you flag) — nothing more. Rules for the ---MISSING--- list and [[NEEDS]] markers:
  - A CPT treatment section is required ONLY if that treatment was actually performed today. If a treatment was not mentioned, simply leave it out. NEVER flag an unperformed treatment (e.g. a CPT code not mentioned) as missing.
  - Flag a value with [[NEEDS: ...]] ONLY when it belongs to a section that applies to this visit and that value is genuinely absent (e.g. minutes for a treatment that WAS performed, BP/HR, a pain rating that was clearly expected but not given).
  - Do NOT invent requirements beyond the listed structure: no billing-audit granularity, no sub-technique time breakdowns, no fields borrowed from other note types, no incision/wound checks unless the structure lists them.
  - Do NOT put discrepancies, cross-checks, optional details, or "consider documenting" suggestions in ---MISSING---.
  - If every required field for the sections that apply is present, the ---MISSING--- list must be exactly "- none"."""

MODE_RULE_OMIT = """COMPLETENESS (omit mode): Include ONLY information explicitly stated in the dictation. Omit any section or bullet not mentioned. Do not infer. Keep the ---MISSING--- list as "- none" unless the clinician clearly began a value but left it incomplete."""

WRITING_RULES_LEAD = """WRITING RULES:
- The dictation is a raw automatic speech-to-text transcript of the therapist talking, and the therapist may be a non-native English speaker. Expect spoken filler and hesitation words (um, uh, like, so, you know, basically, right), false starts, repeated words, mid-sentence self-corrections, and garbled or ungrammatical passages from imperfect recognition. Do NOT reproduce any of that in the note: silently drop every filler and disfluency; on a self-correction keep ONLY the corrected value ("30, sorry, 40 minutes" → 40 minutes); and rewrite garbled or broken passages into clear, grammatical clinical English. If a passage's meaning genuinely cannot be recovered, keep the original words and mark them [[NEEDS: unclear dictation "..." — clinician to confirm]] rather than passing a broken fragment through. The dictation may also have been pasted from a transcription tool and still carry timestamps ("00:12:34", "[1:05]"), speaker labels ("Speaker 1:", "Therapist:", "Patient:"), and non-lexical audio tags ("[inaudible]", "[background noise]") — these are scaffolding, not clinical content: ignore them entirely and never let any of them appear in the note. Never add, drop, or alter a clinical fact while cleaning.
- Convert dictated checklist answers into declarative clinical sentences. The therapist sometimes reads a form aloud as "item, yes" / "item, no", or as a question then its answer ("Fear of falling? Patient worries about falling, yes"). Render this as normal prose ("Patient reports fear of falling"). Never output the literal patterns "..., yes", "..., no", or a question followed by its answer.
- Do NOT copy the same sentence into more than one section. Write each section in its own words at its own level of detail: the Objective Summary is a brief high-level overview, while the detailed sections (Fall Risk, Musculoskeletal, Cardiopulmonary, Functional Mobility) carry the full findings. Never paste identical TUG / MMT / ROM / steadiness sentences into several sections.
- If the dictation contradicts itself or gives two different values for one field (e.g. two visit frequencies, or "no known allergies except sulfa"), record the clinically standard value in that field and append [[NEEDS: dictation also stated "<the other value>" — clinician to confirm]]. Never silently reproduce both as if both were correct, and never pass a self-contradiction through verbatim.
- Map plan-of-treatment values to the correct field by their MEANING, not by the label the therapist happened to say. Frequency = visits per week; Duration = total number of weeks; Intensity = minutes per session. If the therapist says "duration sixty minutes", 60 minutes is the Intensity, not the Duration.
- Write manual muscle test strength grades in standard notation: "4/5", "3+/5", a range as "3+/5 to 4-/5" — never spelled out in words.
- Finish every section with a complete sentence and its full stated value; never stop a section, or the note, mid-sentence. When a field label is stated (e.g. "Certification period"), its stated value must follow it on the same line.
- Write from the SPECIFIC details actually said. No generic boilerplate; wording should be unique to this session.
- Be CONCISE: write in a terse, telegraphic clinical style — brief phrases and fragments, NOT full sentences or flowing paragraphs. Prefer "L shoulder AROM: flexion 90°, abduction limited, pain at end range" over a paragraph restating it. Drop filler ("the patient", "is noted to", "demonstrates", "as well as"). Each field or section is its shortest complete value; never pad. Enumerable clinical facts (medications, diagnoses/PMH items, goals, MMT grades) are the ONLY exception — list every item in FULL; never shorten such a list or drop items to be brief.
- NEVER invent clinical values (minutes, vitals, pain levels, measurements, dates).
- Do NOT infer or calculate the patient's age or any dates. Use only demographic facts explicitly stated in the dictation or patient line; if age is not stated, omit it rather than computing it from a date of birth."""

WRITING_RULES_TAIL = """- For a section carried forward from the prior note, append [[CARRIED FORWARD]] to its heading line. Carry forward does NOT mean copy blindly: when today's session reports a change to a carried value (e.g. ambulation distance, assistive device, assist level, whether stairs were attempted, overall functional status), UPDATE that section to reflect today, and still mark it [[CARRIED FORWARD]].
- Only tag [[CARRIED FORWARD]] on a section that is explicitly marked [carry forward] in the NOTE STRUCTURE above (e.g. Precautions, Functional Status, Short-Term Goals, Long-Term Goals). NEVER tag any other section this way — treatment sections (CPT codes), Pain, Vitals, Response to Treatment, and the Plan are written fresh from today's dictation and are never carried forward, even if their content happens to resemble a prior visit.
- Do not create a section, or a placeholder line such as "Minutes: 0" or "not performed today", for a treatment that was not actually performed or mentioned today — omit that section entirely rather than writing a placeholder for it.
- Internal consistency: today's findings take precedence and no two sections may contradict each other. Before finishing, make sure carried-forward sections — especially Functional Status — agree with what the treatment sections describe happening today (do not state the patient walked 150 ft with a walker if today's gait section says 200 ft with a cane).
- Mark a goal "MET" only if today's summary shows it was achieved. When all short-term goals are met, the Plan must briefly justify continued skilled care by referencing the remaining unmet long-term goals."""

OUTPUT_FORMAT = """OUTPUT FORMAT — plain text in EXACTLY this shape, nothing else (no JSON, no preamble, no code fences):

## <Section heading> [[CARRIED FORWARD]]   (omit the tag if not carried forward)
<body, with [[NEEDS: ...]] inline for any gap>

The heading line is ONLY the section/CPT name (e.g. "## Therapeutic Exercise"), never "Minutes: __" — when a section must start with "Minutes: __", that goes on the first line of the BODY, after the heading line, not inside the heading itself.

Repeat "## " for every section in order. After the final section, on its own line write:
---MISSING---
then one "- " bullet per item the therapist should provide before finalizing, or "- none"."""
