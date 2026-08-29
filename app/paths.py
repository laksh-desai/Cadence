"""Where the clinician's data lives, as distinct from where the program lives.

Until updates existed there was no reason to separate them: Cadence was one folder, and the
encrypted database sat inside it next to the code. That breaks the moment a new version is
installed alongside the old one, because "the folder the code is in" is now version-specific and
the patient database would be stranded in the previous version — or, worse, a fresh empty one
would appear in the new version and the clinician would open Cadence to an empty roster.

So an installed Cadence sets `CADENCE_DATA_DIR` and everything the CLINICIAN owns lives there,
outside any version folder:

    C:\\Cadence\\
      versions\\1.0.0\\      the program — replaced wholesale by an update
      versions\\1.1.0\\      the previous one, kept so a rollback is a pointer flip
      current  ->           junction to the active version
      data\\                CADENCE_DATA_DIR — never touched by an update
        storage\\           cadence.db.enc, .keyfile
        templates\\         the clinician's own templates and their edits to the built-ins
        config\\            hf_config.yaml, sheets_config.yaml, .sheets_credentials.json

**Unset, every path is exactly what it was**, which is why a development checkout and the whole
test suite are unaffected: this module returns the same locations the constants used to hardcode.
That is deliberate — a data-location change that silently moved a patient database would be the
worst possible bug in this file.

Built-in templates are NOT user data. They ship with the release and an update SHOULD replace
them; only the clinician's overrides and their own custom templates are preserved.
"""

from __future__ import annotations

import os
from pathlib import Path

#: The installed program root (the folder holding app/, templates/, scripts/).
INSTALL_DIR = Path(__file__).resolve().parent.parent


def data_dir() -> Path | None:
    """The clinician's data root, or None when Cadence is running from a plain checkout.

    Resolved in two ways, and the second one matters more than it looks. An explicit
    `CADENCE_DATA_DIR` wins; failing that, the INSTALL LAYOUT ITSELF is the answer — running from
    `<root>/versions/<version>/` means the data is at `<root>/data`, because that is what the
    layout means.

    Deriving it rather than requiring the variable is deliberate. If the location depended on an
    environment variable that a setup script had to remember to set, then a shortcut created by
    hand, a `python launcher.py` run from a terminal, or a script invoked directly would each
    quietly get a DIFFERENT, empty database — and the failure would look like "all my patients
    disappeared" rather than like a missing setting. The layout cannot be forgotten; a variable
    can.
    """
    raw = os.environ.get("CADENCE_DATA_DIR", "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    if INSTALL_DIR.parent.name.lower() == "versions":
        return (INSTALL_DIR.parent.parent / "data").resolve()
    return None


def _resolve(subdir: str, legacy: Path) -> Path:
    """`$CADENCE_DATA_DIR/<subdir>` when installed, else exactly where it has always been."""
    root = data_dir()
    if root is None:
        return legacy
    path = root / subdir
    path.mkdir(parents=True, exist_ok=True)
    return path


def storage_dir() -> Path:
    """Holds cadence.db.enc and .keyfile — the only irreplaceable thing Cadence has."""
    return _resolve("storage", INSTALL_DIR / "app" / "storage")


def templates_data_dir() -> Path:
    """Parent of overrides/ and custom/. NOT the built-in templates, which ship with the code."""
    return _resolve("templates", INSTALL_DIR / "templates")


def config_dir(legacy: Path) -> Path:
    """Third-party credentials and config. `legacy` differs per consumer (the HF token has always
    lived beside the transcribe package, the Sheets config beside the integrations one), so each
    caller passes its own historical location rather than this module guessing."""
    return _resolve("config", legacy)
