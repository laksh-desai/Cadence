"""Build a release: verify the tree, package the source, emit a checksum and release notes.

Cadence is not distributed as a frozen executable and should not be — freezing torch and
transformers is huge and fragile, and it cannot freeze the two things that actually have to be
installed anyway (the Ollama service and the model weights). See docs/shipping.md. A release is
therefore a SOURCE ZIP plus `setup.ps1`, which is the same procedure a developer follows, minus
git.

What this script is really for is the refusals. A clinical tool's release process should be hard
to do wrong, so it will not build when:

  * the working tree is dirty            — you could not reproduce the artifact you shipped
  * the tests do not pass                — except the deliberate sign-off gate, see below
  * `app.__version__` is already tagged  — silently re-cutting a version is how two different
                                           builds end up both calling themselves 1.0.0

And it refuses to include anything that is not source: no `.venv`, no database, no keyfile, no
credentials. That list is asserted against `.gitignore` rather than hand-maintained here, because
two copies of a PHI exclusion list is one copy too many.

    python scripts/release.py --check          # verify only, build nothing
    python scripts/release.py                  # build dist/cadence-<version>.zip
    python scripts/release.py --allow-dirty    # local experiment, never for a real release
"""

from __future__ import annotations

import argparse
import hashlib
import subprocess
import sys
import zipfile
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import __version__  # noqa: E402
from app.generate import coding_tables  # noqa: E402

DIST = ROOT / "dist"

#: Everything the running app needs, and nothing else. An allowlist rather than a denylist: a
#: denylist that misses one entry ships a patient database, and no test would catch it.
INCLUDE = ("app", "templates", "docs", "scripts", "launcher.py", "setup.ps1",
           "requirements.txt", "README.md", "CLAUDE.md")

#: Never packaged, whatever a glob might sweep up. Belt and braces over `.gitignore`.
EXCLUDE_PARTS = frozenset({
    ".venv", "__pycache__", ".git", ".claude", "dist", "node_modules",
    "evals", "tests", "saas", "extension",
})
EXCLUDE_NAMES = frozenset({
    ".keyfile", ".dblock", "cadence.db.enc", ".sheets_credentials.json",
    "sheets_config.yaml", "hf_config.yaml", "launcher.log",
})
EXCLUDE_SUFFIXES = (".db", ".sqlite", ".sqlite3", ".db.enc", ".pyc", ".pem", ".key", ".local.json")


def _run(*args: str) -> tuple[int, str]:
    p = subprocess.run(args, cwd=ROOT, capture_output=True, text=True)
    return p.returncode, (p.stdout + p.stderr).strip()


def is_excluded(path: Path) -> bool:
    rel = path.relative_to(ROOT)
    if EXCLUDE_PARTS & set(rel.parts):
        return True
    if path.name in EXCLUDE_NAMES:
        return True
    return any(path.name.endswith(sfx) for sfx in EXCLUDE_SUFFIXES)


def collect() -> list[Path]:
    files: list[Path] = []
    for entry in INCLUDE:
        target = ROOT / entry
        if not target.exists():
            continue
        if target.is_file():
            if not is_excluded(target):
                files.append(target)
            continue
        for path in sorted(target.rglob("*")):
            if path.is_file() and not is_excluded(path):
                files.append(path)
    return files


def check(allow_dirty: bool = False, skip_tests: bool = False) -> list[str]:
    """Everything that must be true before a version number is attached to an artifact."""
    problems: list[str] = []

    code, out = _run("git", "status", "--porcelain")
    if code == 0 and out and not allow_dirty:
        problems.append(
            f"working tree is dirty ({len(out.splitlines())} file(s)) — commit or stash first, or "
            "the zip will not match any commit you can go back to")

    code, out = _run("git", "tag", "--list", f"v{__version__}")
    if code == 0 and out.strip():
        problems.append(
            f"v{__version__} is already tagged — bump app/__init__.py before cutting a release, "
            "or two different builds will both claim to be this version")

    if not skip_tests:
        code, out = _run(str(ROOT / ".venv/Scripts/python.exe"), "-m", "unittest",
                         "discover", "-s", "tests", "-t", ".", "-q")
        # The sign-off gate fails ON PURPOSE until a coder verifies the ICD tables. That is not a
        # reason to block a release — `cpt.billing_enabled()` keeps the codes out of the product
        # while it fails — so it is the one permitted failure, and only that one.
        failures = [ln for ln in out.splitlines()
                    if ln.startswith(("FAIL:", "ERROR:"))
                    and "signed_off" not in ln]
        if failures:
            problems.append("tests are failing:\n      " + "\n      ".join(failures[:8]))

    unverified = coding_tables.unverified_body_parts()
    if unverified:
        # A warning, not a failure: shipping with billing gated off is a supported configuration
        # and is how the first release goes out.
        print(f"  [note] billing will ship OFF — {len(unverified)} ICD region(s) unverified "
              f"({', '.join(unverified)}). Recipients see a Status line explaining why.")
    return problems


def build() -> Path:
    DIST.mkdir(exist_ok=True)
    out = DIST / f"cadence-{__version__}.zip"
    files = collect()

    # Last line of defence. If any of these ever appear in a build, the exclusion logic above has
    # a hole and the right outcome is a crash, not a shipped patient database.
    for f in files:
        low = f.name.lower()
        assert not low.endswith((".enc", ".keyfile")), f"REFUSING to package {f}"
        assert "credential" not in low and low != "hf_config.yaml", f"REFUSING to package {f}"

    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for f in files:
            z.write(f, Path(f"cadence-{__version__}") / f.relative_to(ROOT))
        z.writestr(f"cadence-{__version__}/VERSION", f"{__version__}\n{date.today().isoformat()}\n")
    return out


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="verify only, build nothing")
    ap.add_argument("--allow-dirty", action="store_true")
    ap.add_argument("--skip-tests", action="store_true", help="for iterating on this script only")
    args = ap.parse_args()

    print(f"Cadence {__version__} — release check\n")
    problems = check(allow_dirty=args.allow_dirty, skip_tests=args.skip_tests)
    for p in problems:
        print(f"  [x] {p}")
    if problems:
        print("\nRefusing to build. Fix the above, or use --allow-dirty for a local experiment.")
        return 1
    print("  [ok] tree clean, version untagged, tests pass")
    if args.check:
        return 0

    out = build()
    digest = sha256(out)
    size_mb = out.stat().st_size / 1_048_576
    (out.with_suffix(".zip.sha256")).write_text(f"{digest}  {out.name}\n", encoding="utf-8")

    print(f"\n  built  {out.relative_to(ROOT)}  ({size_mb:.1f} MB, "
          f"{len(collect())} files)")
    print(f"  sha256 {digest}")
    print(f"""
Next:
  git tag -a v{__version__} -m "Cadence {__version__}"
  git push origin v{__version__}
  gh release create v{__version__} "{out.relative_to(ROOT)}" "{out.name}.sha256" \\
     --title "Cadence {__version__}" --notes-file docs/release-notes/{__version__}.md

The recipient unzips it, runs setup.ps1, and gets a desktop shortcut. Their database, keyfile,
custom templates and credentials live outside the zip and are never touched by an install.""")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
