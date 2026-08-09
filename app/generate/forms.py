import hashlib
import logging
import re
from dataclasses import dataclass
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

TEMPLATES_DIR = Path(__file__).resolve().parent.parent.parent / "templates"
# User edits to a SHIPPED template land here as an override (spec body only), keeping the
# original templates/*.md pristine so any built-in can be reset to default. User-CREATED
# templates are full files in custom/ (their own frontmatter + body). Both dirs are created
# lazily on first write; neither ships with the repo.
OVERRIDES_DIR = TEMPLATES_DIR / "overrides"
CUSTOM_DIR = TEMPLATES_DIR / "custom"

# Display order matches the prototype's FORM_ORDER (cadence-prototype.html:315) —
# not alphabetical, so the UI dropdown order doesn't silently change. This is the
# fixed set of BUILT-IN forms; user-created templates are appended after these
# (see ordered_form_ids), and this list stays the definition of "built-in".
FORM_ORDER = ["initial", "initial_updated", "followup"]

VALID_MODES = ("require", "omit")

CARRY_FORWARD_FORM_IDS = {"followup"}

# The exact section labels each carry-enabled form's spec marks [carry forward]. Injected
# verbatim into the prompt so the model has a concrete, closed list instead of an abstract
# rule — a 4B local model follows "only these N named sections" far more reliably than
# "sections explicitly marked [carry forward] in the structure".
CARRY_SECTION_LABELS: dict[str, list[str]] = {
    "followup": ["Precautions", "Functional Status", "Short-Term Goals", "Long-Term Goals"],
}

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n(.*)$", re.DOTALL)


@dataclass(frozen=True)
class GuidedStep:
    """One section of a form's guided-dictation walkthrough.

    `label` names the section, `example` is a concrete sample of what to say, and
    `optional` marks sections the clinician can freely skip (always true in omit-mode
    forms and for genuinely-conditional require-mode sections). Purely a dictation aid
    surfaced in the UI -- NEVER part of the generation prompt (which uses `spec` only),
    so it cannot affect note content.
    """

    label: str
    example: str
    optional: bool = False


@dataclass(frozen=True)
class FormSpec:
    id: str
    name: str
    mode: str  # "require" | "omit"
    carry: bool
    spec: str
    # Ordered section-by-section walkthrough for the UI's guided dictation mode.
    # A dictation aid only -- see GuidedStep. Defaults to () so a form missing the
    # key simply has no guided mode rather than raising.
    steps: tuple[GuidedStep, ...] = ()


def _parse_steps(raw) -> tuple[GuidedStep, ...]:
    steps = []
    for item in raw or ():
        steps.append(
            GuidedStep(
                label=str(item["label"]).strip(),
                example=str(item["example"]).strip(),
                optional=bool(item.get("optional", False)),
            )
        )
    return tuple(steps)


def _parse_file(text: str) -> tuple[dict, str]:
    m = _FRONTMATTER_RE.match(text)
    if not m:
        raise ValueError("missing YAML frontmatter")
    return yaml.safe_load(m.group(1)) or {}, m.group(2)


# ---- paths & predicates -----------------------------------------------------

def _override_path(form_id: str) -> Path:
    return OVERRIDES_DIR / f"{form_id}.md"


def _custom_path(form_id: str) -> Path:
    return CUSTOM_DIR / f"{form_id}.md"


def is_builtin(form_id: str) -> bool:
    return form_id in FORM_ORDER


def is_custom(form_id: str) -> bool:
    return _custom_path(form_id).exists()


def is_customized(form_id: str) -> bool:
    """A built-in whose shipped outline has been overridden by the user."""
    return is_builtin(form_id) and _override_path(form_id).exists()


def spec_sha(form_id: str) -> str | None:
    """Short hash of the outline that was actually fed to the model.

    Stamped onto a saved note so a captured correction stays interpretable: templates are
    runtime-editable, so without this there is no way to tell later whether a note was generated
    against the outline the template currently holds. The spec IS the generation prompt, so a
    changed spec means a differently-instructed model.
    """
    form = FORMS.get(form_id)
    if form is None:
        return None
    return hashlib.sha256(form.spec.encode("utf-8")).hexdigest()[:16]


def _read_override(form_id: str) -> str | None:
    p = _override_path(form_id)
    if not p.exists():
        return None
    try:
        content = p.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return content or None


# ---- loading ----------------------------------------------------------------

def _load_builtin(form_id: str) -> FormSpec:
    meta, body = _parse_file((TEMPLATES_DIR / f"{form_id}.md").read_text(encoding="utf-8"))
    override = _read_override(form_id)
    return FormSpec(
        id=form_id,
        name=meta["name"],
        mode=meta["mode"],
        carry=bool(meta["carry"]),
        spec=override if override is not None else body.strip(),
        steps=_parse_steps(meta.get("steps")),
    )


def _load_custom(path: Path) -> FormSpec:
    meta, body = _parse_file(path.read_text(encoding="utf-8"))
    # A custom template never participates in carry-forward (v1): carry-forward needs
    # per-form section-label + snapshot-field wiring that only the built-ins have, so
    # custom templates are always non-carry regardless of what their file says.
    return FormSpec(
        id=meta["id"],
        name=meta["name"],
        mode=meta["mode"] if meta.get("mode") in VALID_MODES else "require",
        carry=False,
        spec=body.strip(),
        steps=_parse_steps(meta.get("steps")),
    )


def load_forms() -> dict[str, FormSpec]:
    forms: dict[str, FormSpec] = {}
    for form_id in FORM_ORDER:
        forms[form_id] = _load_builtin(form_id)
    if CUSTOM_DIR.exists():
        for path in CUSTOM_DIR.glob("*.md"):
            try:
                f = _load_custom(path)
            except Exception:
                logger.exception("skipping malformed custom template %s", path.name)
                continue
            forms[f.id] = f
    return forms


FORMS: dict[str, FormSpec] = load_forms()


def reload_forms() -> None:
    """Rebuild FORMS in place after a template create/edit/delete, so every module that
    imported the FORMS dict by reference (e.g. app.ui.server) sees the change without a
    process restart. Mutates the existing dict rather than rebinding the name."""
    fresh = load_forms()
    FORMS.clear()
    FORMS.update(fresh)


def ordered_form_ids() -> list[str]:
    """Built-ins first (fixed FORM_ORDER), then user-created templates alphabetically —
    the order the API/UI present forms in."""
    builtins = [fid for fid in FORM_ORDER if fid in FORMS]
    customs = sorted(
        (fid for fid in FORMS if fid not in FORM_ORDER),
        key=lambda i: FORMS[i].name.lower(),
    )
    return builtins + customs


# ---- id / name helpers ------------------------------------------------------

def _slugify(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")
    return s or "template"


def _new_custom_id(name: str) -> str:
    base = "custom-" + _slugify(name)[:40]
    taken = set(FORM_ORDER)
    if CUSTOM_DIR.exists():
        taken |= {p.stem for p in CUSTOM_DIR.glob("*.md")}
    fid = base
    n = 2
    while fid in taken:
        fid = f"{base}-{n}"
        n += 1
    return fid


def _copy_name(name: str) -> str:
    existing = {f.name for f in FORMS.values()}
    candidate = f"{name} (copy)"
    if candidate not in existing:
        return candidate
    n = 2
    while f"{name} (copy {n})" in existing:
        n += 1
    return f"{name} (copy {n})"


def _template_markdown(*, id: str, name: str, mode: str, carry: bool, spec: str, steps=()) -> str:
    meta: dict = {"id": id, "name": name, "mode": mode, "carry": bool(carry)}
    if steps:
        meta["steps"] = [{"label": s.label, "example": s.example, "optional": s.optional} for s in steps]
    front = yaml.safe_dump(meta, sort_keys=False, allow_unicode=True)
    return f"---\n{front}---\n{spec.strip()}\n"


# ---- mutations --------------------------------------------------------------

def create_custom_template(name: str, mode: str, spec: str, *, steps=()) -> FormSpec:
    """Create a brand-new user template (always non-carry). Returns the loaded FormSpec."""
    name = (name or "").strip() or "Untitled template"
    mode = mode if mode in VALID_MODES else "require"
    fid = _new_custom_id(name)
    CUSTOM_DIR.mkdir(parents=True, exist_ok=True)
    _custom_path(fid).write_text(
        _template_markdown(id=fid, name=name, mode=mode, carry=False, spec=(spec or "").strip(), steps=steps),
        encoding="utf-8",
    )
    reload_forms()
    return FORMS[fid]


def duplicate_template(source_id: str) -> FormSpec | None:
    """Copy any template (built-in or custom) into a new user template. The copy keeps the
    source's outline, mode, and guided steps, but is always a non-carry custom template."""
    src = FORMS.get(source_id)
    if src is None:
        return None
    return create_custom_template(_copy_name(src.name), src.mode, src.spec, steps=src.steps)


def edit_template(form_id: str, *, spec: str, name: str | None = None, mode: str | None = None) -> FormSpec | None:
    """Save an edited outline. For a built-in this writes a spec-only override (leaving the
    shipped file pristine and its identity fixed — name/mode are ignored). For a custom
    template it rewrites the file, optionally renaming or changing its mode. Returns the
    reloaded FormSpec, or None if the id is unknown."""
    spec = (spec or "").strip()
    if is_custom(form_id):
        meta, _ = _parse_file(_custom_path(form_id).read_text(encoding="utf-8"))
        new_name = (name or meta["name"]).strip() or meta["name"]
        new_mode = mode if mode in VALID_MODES else meta.get("mode", "require")
        _custom_path(form_id).write_text(
            _template_markdown(
                id=form_id, name=new_name, mode=new_mode, carry=False, spec=spec,
                steps=_parse_steps(meta.get("steps")),
            ),
            encoding="utf-8",
        )
        reload_forms()
        return FORMS[form_id]
    if is_builtin(form_id):
        OVERRIDES_DIR.mkdir(parents=True, exist_ok=True)
        _override_path(form_id).write_text(spec + "\n", encoding="utf-8")
        reload_forms()
        return FORMS[form_id]
    return None


def reset_template(form_id: str) -> FormSpec | None:
    """Discard a built-in's override, restoring its shipped outline. No-op for a built-in
    that was never edited; returns None for a custom template (which has no default)."""
    if not is_builtin(form_id):
        return None
    p = _override_path(form_id)
    if p.exists():
        try:
            p.unlink()
        except OSError:
            pass
    reload_forms()
    return FORMS[form_id]


def delete_custom_template(form_id: str) -> bool:
    """Permanently remove a user-created template. Built-ins can never be deleted."""
    if not is_custom(form_id):
        return False
    try:
        _custom_path(form_id).unlink()
    except OSError:
        pass
    reload_forms()
    return True
