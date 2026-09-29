"""Repetition-loop guard for the local model.

MedGemma 4B sometimes falls into a loop: it writes the same Objective sentences (or a whole section)
again and again until the output ceiling (NUM_PREDICT = 3072 tokens) stops it. That costs minutes of
CPU time and fills the note with copies. Two deterministic defences, no prompt wording involved:

1. `is_looping` — checked while the note streams; when a substantial sentence has already been
   written LOOP_REPEATS times, generation is stopped early.
2. `collapse_repeats` — after parsing, removes EXACT repeats (a later copy of a sentence already
   written in the same section, or a later section identical to an earlier one). Only exact
   duplicates are removed, so no wording is changed and no fact disappears: the first copy stays.

Short sentences are ignored (MIN_WORDS), because a real note legitimately repeats short phrases
("Tolerated well.", "Minutes: 15.") across sections.
"""

from __future__ import annotations

import re

MIN_WORDS = 6          # shorter sentences may legitimately repeat
LOOP_REPEATS = 4       # a 6+-word sentence written 4 times is a loop, not a note

_SPLIT = re.compile(r"(?<=[.!?])\s+|\n+")


def _norm(unit: str) -> str:
    return re.sub(r"\s+", " ", unit.strip().lower()).strip(" -*•")


def _substantial(unit: str) -> bool:
    return len(unit.split()) >= MIN_WORDS


def is_looping(text: str) -> bool:
    """True when any substantial sentence/line already appears LOOP_REPEATS times."""
    counts: dict[str, int] = {}
    for raw in _SPLIT.split(text or ""):
        u = _norm(raw)
        if not u or u.startswith("#") or not _substantial(u):
            continue
        counts[u] = counts.get(u, 0) + 1
        if counts[u] >= LOOP_REPEATS:
            return True
    return False


def _dedupe_body(body: str) -> str:
    seen: set[str] = set()
    out_lines = []
    for line in (body or "").split("\n"):
        parts = re.split(r"(?<=[.!?])\s+", line)
        kept = []
        for part in parts:
            u = _norm(part)
            if u and _substantial(u):
                if u in seen:
                    continue
                seen.add(u)
            kept.append(part)
        new_line = " ".join(p for p in kept if p is not None).rstrip()
        # A line that consisted only of repeats disappears; blank lines the model wrote are kept.
        if line.strip() and not new_line.strip():
            continue
        out_lines.append(new_line)
    # Collapse the runs of blank lines left behind by dropped lines.
    text = "\n".join(out_lines)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def collapse_repeats(sections: list[dict]) -> list[dict]:
    """Drop later exact copies: repeated sentences inside a section, and repeated whole sections."""
    out: list[dict] = []
    seen_sections: set[tuple[str, str]] = set()
    for s in sections:
        body = _dedupe_body(s.get("body", ""))
        key = (_norm(s.get("heading", "")), _norm(body))
        if body and key in seen_sections:
            continue
        seen_sections.add(key)
        out.append({**s, "body": body})
    return out
