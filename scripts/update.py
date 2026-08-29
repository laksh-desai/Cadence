"""Check for, apply, and roll back a Cadence update.

Updating a clinical tool is not the same problem as updating an app. Three things make it
different, and every design choice below follows from one of them:

  1. **An update changes what notes SAY.** A prompt rule, a postprocess backstop, a template edit —
     these are the product. So the clinician is told what changed in clinical terms before
     anything happens, and an update NEVER applies itself. There is no auto-update. A note that
     silently starts reading differently mid-clinic is worse than an old version.

  2. **The data must outlive the program.** The database, the keyfile, the clinician's own
     templates and their edits to the built-ins all live in CADENCE_DATA_DIR, outside every
     version folder (see app/paths.py). An update replaces the program and cannot reach them.

  3. **It has to be reversible, immediately.** If a new version breaks generation at 9am on a
     Tuesday, "restore from backup" is not an answer. The previous version stays on disk and
     rollback is a pointer flip.

Layout:

    C:\\Cadence\\
      versions\\1.0.0\\    previous, kept for rollback
      versions\\1.1.0\\    new
      current  ->         junction to the active version (a DIRECTORY junction, which Windows
                          allows without administrator rights, unlike a symlink)
      data\\              CADENCE_DATA_DIR

Safety properties, in the order they matter:
  * The DATABASE LOCK is the "is Cadence running?" check. Refusing to update while the app is open
    reuses the guard that already exists rather than inventing a second one that could disagree.
  * A backup is taken before anything is written, via scripts/backup.py.
  * The download is verified against the SHA-256 in the manifest BEFORE it is extracted.
  * `current` is repointed LAST, after the new version is fully extracted — so an interrupted
    update leaves a half-written folder nobody is pointing at, not a half-broken install.
  * Migrations are additive-only (`db._migrate`), so upgrading is safe. DOWNGRADING after a
    migration is not, and `rollback` says so out loud.

    python scripts/update.py --check       # is there a new version? what changed? writes nothing
    python scripts/update.py --apply       # download, verify, install, repoint
    python scripts/update.py --rollback    # back to the previous version
    python scripts/update.py --status      # what is installed, what it would roll back to
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import __version__  # noqa: E402
from app import paths  # noqa: E402

#: Where releases are published. A single static JSON file, so hosting is GitHub Pages or any
#: static host — there is no update server to run or secure. Overridable for testing and so the
#: practice could self-host if it ever wanted to.
MANIFEST_URL = os.environ.get(
    "CADENCE_UPDATE_URL",
    "https://laksh-desai.github.io/Cadence/latest.json",
)

#: The only outbound request Cadence ever makes on its own behalf. It is a GET of a static file
#: and carries no query string, no identifier, and no patient data of any kind — the version is
#: compared locally, after download. Set CADENCE_UPDATE_URL="" to disable checking entirely.
USER_AGENT = f"Cadence/{__version__}"


def install_root() -> Path | None:
    """The `C:\\Cadence` above `versions/<v>/`, or None when running from a plain checkout."""
    if ROOT.parent.name.lower() == "versions":
        return ROOT.parent.parent
    return None


def _version_key(name: str) -> tuple:
    try:
        return tuple(int(p) for p in name.split("."))
    except ValueError:
        return (0,)


def installed_versions(root: Path) -> list[str]:
    vdir = root / "versions"
    if not vdir.is_dir():
        return []
    return sorted((p.name for p in vdir.iterdir() if p.is_dir()), key=_version_key)


def fetch_manifest(url: str = MANIFEST_URL) -> dict | None:
    if not url:
        return None
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=15) as resp:  # noqa: S310 - fixed https URL
        return json.loads(resp.read().decode("utf-8"))


def is_newer(candidate: str, current: str = __version__) -> bool:
    return _version_key(candidate) > _version_key(current)


def app_is_running() -> bool:
    """True if a Cadence process holds the database.

    Reuses the store's own cross-process lock rather than scanning for processes: it is the same
    guard that stops two writers corrupting the database, so it cannot disagree with it.
    """
    lock = paths.storage_dir() / ".dblock"
    if not lock.exists():
        return False
    try:
        pid = int(lock.read_text(encoding="utf-8").strip())
    except (ValueError, OSError):
        return False
    from app.storage.db import _pid_alive
    return _pid_alive(pid)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _print_changes(manifest: dict) -> None:
    print(f"\n  Cadence {manifest['version']} is available (you have {__version__}).")
    if manifest.get("released"):
        print(f"  Released {manifest['released']}.")
    changes = manifest.get("changes") or []
    if changes:
        print("\n  What changes in your notes:")
        for line in changes:
            print(f"    - {line}")
    if manifest.get("action_required"):
        print(f"\n  ! {manifest['action_required']}")


def cmd_status() -> int:
    root = install_root()
    print(f"Cadence {__version__}")
    print(f"  program : {ROOT}")
    print(f"  data    : {paths.data_dir() or '(checkout — data sits inside the project folder)'}")
    if root is None:
        print("\n  Running from a development checkout, not an installed copy. Updates are a\n"
              "  git pull here; scripts/update.py manages installed copies only.")
        return 0
    versions = installed_versions(root)
    print(f"  installed versions: {', '.join(versions) or 'none'}")
    others = [v for v in versions if v != __version__]
    print(f"  rollback target   : {others[-1] if others else 'none — nothing to roll back to'}")
    print(f"  app running       : {'yes (updates blocked)' if app_is_running() else 'no'}")
    return 0


def cmd_check() -> int:
    try:
        manifest = fetch_manifest()
    except Exception as e:  # noqa: BLE001 - offline is normal and must not look like a crash
        print(f"Could not reach the update server ({e}).")
        print("This is harmless — Cadence works entirely offline. Try again when convenient.")
        return 0
    if manifest is None:
        print("Update checking is switched off (CADENCE_UPDATE_URL is empty).")
        return 0
    if not is_newer(manifest["version"]):
        print(f"Cadence {__version__} is up to date.")
        return 0
    _print_changes(manifest)
    print("\n  To install:  python scripts/update.py --apply")
    print("  Nothing has been downloaded or changed.")
    return 0


def cmd_apply(assume_yes: bool = False) -> int:
    root = install_root()
    if root is None:
        print("This looks like a development checkout, not an installed Cadence.")
        print("Update it with `git pull` instead — scripts/update.py manages installed copies.")
        return 1
    if app_is_running():
        print("Cadence is open. Close it first — updating the program underneath a running copy\n"
              "is how a half-updated install happens.")
        return 1

    manifest = fetch_manifest()
    if manifest is None or not is_newer(manifest["version"]):
        print(f"Cadence {__version__} is up to date.")
        return 0
    _print_changes(manifest)
    if not assume_yes:
        if input("\n  Install this update? [y/N] ").strip().lower() not in ("y", "yes"):
            print("  Nothing changed.")
            return 0

    # 1. Back up first, using the tool that already knows how to verify a backup is restorable.
    print("\n  [1/4] backing up your notes ...")
    backups = (paths.data_dir() or root) / "backups"
    rc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "backup.py"), "backup", "--dest", str(backups)],
        capture_output=True, text=True)
    if rc.returncode != 0:
        print("  Backup FAILED — refusing to update:\n" + (rc.stdout + rc.stderr))
        return 1
    print("        ok")

    # 2. Download and verify BEFORE anything is written into the install.
    print("  [2/4] downloading ...")
    with tempfile.TemporaryDirectory() as td:
        zip_path = Path(td) / "cadence.zip"
        req = urllib.request.Request(manifest["url"], headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=300) as resp, zip_path.open("wb") as fh:  # noqa: S310
            shutil.copyfileobj(resp, fh)
        got = sha256(zip_path)
        if got != manifest["sha256"]:
            print(f"  Checksum MISMATCH — refusing to install.\n    expected {manifest['sha256']}\n"
                  f"    got      {got}")
            return 1
        print("        ok, checksum verified")

        # 3. Extract beside the current version. `current` still points at the old one.
        print("  [3/4] installing ...")
        target = root / "versions" / manifest["version"]
        if target.exists():
            shutil.rmtree(target)
        staging = Path(td) / "x"
        with zipfile.ZipFile(zip_path) as z:
            z.extractall(staging)
        inner = next(p for p in staging.iterdir() if p.is_dir())
        shutil.move(str(inner), str(target))
        print(f"        ok -> {target}")

    # 4. Dependencies, into the SHARED venv at the install root. Usually a no-op in seconds —
    # requirements rarely change — but skipping it entirely would mean a version that adds a
    # package starts up broken, and "it worked until I updated" is the worst failure to debug on
    # someone else's laptop.
    venv_py = root / ".venv" / "Scripts" / "python.exe"
    reqs = root / "versions" / manifest["version"] / "requirements.txt"
    if venv_py.exists() and reqs.exists():
        print("  [4/5] checking dependencies ...")
        rc = subprocess.run([str(venv_py), "-m", "pip", "install", "-q", "-r", str(reqs)],
                            capture_output=True, text=True)
        if rc.returncode != 0:
            print("  Dependency install FAILED — the new version is on disk but NOT active.\n"
                  "  Nothing has changed; you are still on " + __version__ + ".\n"
                  + (rc.stdout + rc.stderr)[-800:])
            return 1
        print("        ok")

    # 5. Repoint LAST. Until this line, an interruption leaves an unused folder, not a broken app.
    print("  [5/5] switching over ...")
    _repoint(root, manifest["version"])
    print(f"        ok\n\n  Cadence {manifest['version']} installed. "
          f"{__version__} is kept for rollback.")
    print("  Open Cadence and generate one note before your first patient, to confirm all is well.")
    return 0


def _repoint(root: Path, version: str) -> None:
    """Point `current` at a version. A directory JUNCTION, not a symlink: Windows creates
    junctions without administrator rights, and requiring admin to update would mean the clinician
    cannot."""
    link = root / "current"
    if link.exists() or link.is_symlink():
        # rmdir removes the junction itself, never what it points at.
        subprocess.run(["cmd", "/c", "rmdir", str(link)], check=False, capture_output=True)
    subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(root / "versions" / version)],
                   check=True, capture_output=True)


def cmd_rollback(assume_yes: bool = False) -> int:
    root = install_root()
    if root is None:
        print("Not an installed copy — nothing to roll back.")
        return 1
    if app_is_running():
        print("Cadence is open. Close it first.")
        return 1
    others = [v for v in installed_versions(root) if v != __version__]
    if not others:
        print("No previous version on disk to roll back to.")
        return 1
    target = others[-1]
    print(f"Roll back {__version__} -> {target}.")
    print("\n  Your notes are NOT affected — they live outside the version folder.")
    print("  One caveat worth reading: database migrations only ever ADD columns, so going")
    print("  forward is always safe, but an older version does not know about a column a newer")
    print("  one added. Rolling back is supported and tested; rolling back and then saving new")
    print("  notes, then rolling forward again, is not a path anyone has exercised.")
    if not assume_yes:
        if input(f"\n  Roll back to {target}? [y/N] ").strip().lower() not in ("y", "yes"):
            print("  Nothing changed.")
            return 0
    _repoint(root, target)
    print(f"  Done — Cadence {target} is active again.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--check", action="store_true", help="is there a new version? writes nothing")
    g.add_argument("--apply", action="store_true", help="download, verify, install, switch over")
    g.add_argument("--rollback", action="store_true", help="return to the previous version")
    g.add_argument("--status", action="store_true", help="what is installed right now")
    ap.add_argument("--yes", action="store_true", help="skip the confirmation prompt")
    args = ap.parse_args()

    if args.apply:
        return cmd_apply(assume_yes=args.yes)
    if args.rollback:
        return cmd_rollback(assume_yes=args.yes)
    if args.check:
        return cmd_check()
    return cmd_status()


if __name__ == "__main__":
    raise SystemExit(main())
