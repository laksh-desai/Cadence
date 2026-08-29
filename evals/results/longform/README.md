# Long-form condensing A/B — the run that turned rule 16's feature off

`scripts/validate_longform.py`, 2026-08-24, MedGemma 4B on the dev box.
Source: `evals/data/longform_intake.txt` (2,363 words, hand-authored, fully synthetic) scored
against `evals/data/longform_intake_ledger.json` (78 facts, tagged head / mid / tail).

| arm | facts | time | what happened |
|---|---|---|---|
| **raw** (truncate — the control) | **59/78** | 15.3 min | Ollama silently drops what does not fit. head 19/27, mid 21/23, tail 19/28. |
| condense, "just clean sentences" | 18/78 | 29.6 min | Condense kept 73/78 facts, then the writer produced 5 sections instead of 18. Structure destroyed. |
| condense, structure-preserving | — | — | Labels kept. Content **fabricated** — see the evidence file below. |

## The evidence

`EVIDENCE_structure-prompt_condensed_fabricated_goals.txt` is the condensed intermediate from the
third attempt. Its `**Short Term Goals, Four Weeks:**` block reads:

    *   Improve hand strength and dexterity
    *   Improve balance and reduce fall risk
    *   Increase independence with activities of daily living
    *   Improve gait and reduce fall risk
    *   Improve ability to ambulate safely

The therapist actually said:

    One, patient will ambulate three hundred feet with a rolling walker and supervision only, no
    rest break. Two, patient will improve Berg Balance Scale to forty five out of fifty six.
    Three, patient will don and doff socks independently using adaptive equipment. Four, patient
    will negotiate twelve steps with one rail and supervision. Five, patient will report zero
    falls over a four week period.

Every measurable value replaced with a generic phrase, in prose that reads perfectly professional.
**No layer in Cadence can catch this**: `traceability` flags values in the NOTE that are missing
from the DICTATION, and here the note ends up with FEWER values rather than invented ones.

## Conclusion

`chunked.CONDENSE_ENABLED` now defaults to False. An over-budget dictation takes the raw path and
the clinician is warned that part of it was not read. Truncation loses the tail visibly and cannot
invent; a 4B paraphrase pass upstream of every verification layer can do both.

Re-enable for an experiment with `CADENCE_CONDENSE_LONG_DICTATION=1`, and beat 59/78 before
proposing it as a default. See CLAUDE.md rule 16 for the `num_ctx` follow-up.
