"""Python port of cadence-prototype.html's parsePlain() (lines 474-483)."""

import re

_MISSING_HEADER_RE = re.compile(r"^-{2,}\s*MISSING", re.IGNORECASE | re.MULTILINE)
_MISSING_STRIP_RE = re.compile(r"^-{2,}\s*MISSING-*\s*", re.IGNORECASE)
_BULLET_RE = re.compile(r"^[-•*]\s*")
_NONE_RE = re.compile(r"^none$", re.IGNORECASE)
# The prompt asks for "## <heading>", but a 4B model occasionally emits a different heading
# level (`#` or `###`). Tolerate 1-6 hashes so a stray level doesn't discard the whole note to
# the raw-text fallback (which also loses the verification flags and the missing-info panel).
_HEADING_RE = re.compile(r"^#{1,6}\s+(.*)$", re.MULTILINE)
_CARRIED_RE = re.compile(r"\[\[\s*CARRIED FORWARD\s*\]\]", re.IGNORECASE)


def parse_plain(text: str) -> dict | None:
    """Returns {"sections": [{"heading", "body", "carried_forward"}], "missing_info": [str]}
    or None if the model didn't follow the `## heading` output contract — callers
    should fall back to rendering the raw text, same as the prototype's line-421 path.
    """
    if not text or not _HEADING_RE.search(text):
        return None

    missing_info: list[str] = []
    body = text
    m = _MISSING_HEADER_RE.search(text)
    if m:
        body = text[: m.start()]
        block = _MISSING_STRIP_RE.sub("", text[m.start():], count=1)
        for line in block.splitlines():
            item = _BULLET_RE.sub("", line).strip()
            if item and not _NONE_RE.match(item):
                missing_info.append(item)

    marks = [
        {"head": hm.group(1), "start": hm.start(), "body_start": hm.end()}
        for hm in _HEADING_RE.finditer(body)
    ]

    sections = []
    for i, mk in enumerate(marks):
        end = marks[i + 1]["start"] if i + 1 < len(marks) else len(body)
        heading = mk["head"].strip()
        carried = bool(_CARRIED_RE.search(heading))
        heading = _CARRIED_RE.sub("", heading).strip()
        sec_body = body[mk["body_start"]:end].strip()
        if heading:
            sections.append({"heading": heading, "body": sec_body, "carried_forward": carried})

    return {"sections": sections, "missing_info": missing_info} if sections else None
