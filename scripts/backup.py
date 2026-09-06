"""Backup / restore the local encrypted patient store.

Cadence keeps patient notes ONLY in app/storage/cadence.db.enc, encrypted with the key in
app/storage/.keyfile. There is no cross-device note sync, so this pair *is* the practice's
record: a lost or dead laptop loses everything unless it is backed up. This tool copies BOTH
files TOGETHER (one is useless without the other), verifies the copied pair actually decrypts,
and can restore them.

NEVER back up to a cloud-synced folder (OneDrive / Google Drive / Dropbox). The Google
Workspace BAA covers only the roster Sheet, not a copy of the database. Use a local encrypted
external / USB drive kept on-site (see docs/device-safeguards-checklist.md).

Usage:
  python scripts/backup.py backup  --dest "E:\\CadenceBackups"
  python scripts/backup.py list    --dest "E:\\CadenceBackups"
  python scripts/backup.py restore "E:\\CadenceBackups\\cadence-backup-..." --dry-run
      Rehearse a restore: verifies the backup's keyfile+DB decrypt as a pair and prints exactly
      what would change. Writes NOTHING. Do this periodically — an untested backup is not a
      backup, and before --dry-run existed the only way to test one was to overwrite the live
      patient database with it.
  python scripts/backup.py restore "E:\\CadenceBackups\\cadence-backup-20260727-101500"
      Add --force to overwrite existing storage files; the current files are first copied
      aside to a *.pre-restore-<timestamp> backup. Only restore while Cadence is CLOSED.
  python scripts/backup.py verify  (checks the live keyfile + DB decrypt as a pair)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cryptography.fernet import Fernet, InvalidToken

from app.storage import db as _db  # reuse the canonical paths so this never drifts

DEFAULT_STORAGE = _db.STORAGE_DIR
KEYFILE_NAME = ".keyfile"
ENC_NAME = "cadence.db.enc"


def _paths(storage_dir: Path) -> tuple[Path, Path]:
    sd = Path(storage_dir)
    return sd / KEYFILE_NAME, sd / ENC_NAME


def _sha256(p: Path) -> str:
    h = hashlib.sha256()
    h.update(p.read_bytes())
    return h.hexdigest()


def verify_pair(keyfile: Path, enc: Path) -> tuple[bool, str]:
    """Confirm the keyfile decrypts the encrypted DB — the only real proof a backup is
    restorable. Returns (ok, message). A missing/empty DB (fresh install, no data yet) is
    treated as valid: there is simply nothing to decrypt."""
    if not keyfile.exists():
        return False, f"keyfile missing: {keyfile}"
    if not enc.exists() or enc.stat().st_size == 0:
        return True, "no database yet (keyfile only) — nothing to decrypt"
    try:
        Fernet(keyfile.read_bytes().strip()).decrypt(enc.read_bytes())
    except InvalidToken:
        return False, "keyfile does NOT match the database — the pair is mismatched/corrupt"
    except Exception as e:  # noqa: BLE001
        return False, f"could not verify pair: {e}"
    return True, "keyfile + database decrypt correctly as a pair"


def do_backup(dest: Path, storage_dir: Path = DEFAULT_STORAGE) -> Path:
    keyfile, enc = _paths(storage_dir)
    if not keyfile.exists():
        raise SystemExit(f"nothing to back up: no keyfile at {keyfile} (has the app ever run?)")
    ok, msg = verify_pair(keyfile, enc)
    if not ok:
        raise SystemExit(f"refusing to back up an unverifiable store: {msg}")
    print(f"source: {msg}")

    dest = Path(dest)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out = dest / f"cadence-backup-{stamp}"
    out.mkdir(parents=True, exist_ok=False)

    shutil.copy2(keyfile, out / KEYFILE_NAME)
    files = {KEYFILE_NAME: _sha256(out / KEYFILE_NAME)}
    if enc.exists():
        shutil.copy2(enc, out / ENC_NAME)
        files[ENC_NAME] = _sha256(out / ENC_NAME)

    # Re-verify the COPIES, not the source — proves the backup itself is restorable.
    ok, msg = verify_pair(out / KEYFILE_NAME, out / ENC_NAME)
    if not ok:
        raise SystemExit(f"backup copy failed verification: {msg}")

    (out / "manifest.json").write_text(json.dumps({
        "created_at": datetime.now().astimezone().isoformat(),
        "source_storage": str(storage_dir),
        "files": files,
    }, indent=2), encoding="utf-8")

    print(f"backup OK -> {out}")
    print(f"verified: {msg}")
    print("REMINDER: keep this on a local encrypted drive — never a cloud-synced folder.")
    return out


def do_restore(backup_dir: Path, storage_dir: Path = DEFAULT_STORAGE, force: bool = False,
               dry_run: bool = False) -> None:
    """Restore a backup into the live store, or (with dry_run) rehearse it without writing.

    The dry run exists because a backup you have never restored is not a backup. Before it, the
    only way to find out whether a backup was good was to overwrite the live patient database with
    it — so the honest advice was "don't test your backups", which is the opposite of the advice a
    backup tool should give. The rehearsal does everything the real restore does except copy:
    it decrypts the backup's keyfile+database AS A PAIR (the failure that actually happens — a
    keyfile from one machine beside a database from another) and prints exactly what would be
    overwritten and where the safety copies would land.
    """
    backup_dir = Path(backup_dir)
    src_key, src_enc = _paths(backup_dir)
    if not src_key.exists():
        raise SystemExit(f"not a backup: no {KEYFILE_NAME} in {backup_dir}")
    ok, msg = verify_pair(src_key, src_enc)
    if not ok:
        raise SystemExit(f"refusing to restore a broken backup: {msg}")
    print(f"backup verified: {msg}")

    keyfile, enc = _paths(storage_dir)
    if dry_run:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        print(f"DRY RUN — nothing was written. Restoring {backup_dir} would:")
        for src, dst in ((src_key, keyfile), (src_enc, enc)):
            if not src.exists():
                continue
            if dst.exists():
                print(f"  copy {dst.name} -> {dst.name}.pre-restore-{stamp}  (safety copy)")
                print(f"  overwrite {dst}  ({dst.stat().st_size:,} bytes -> {src.stat().st_size:,})")
            else:
                print(f"  create {dst}  ({src.stat().st_size:,} bytes)")
        if (keyfile.exists() or enc.exists()):
            print("  ...and would REQUIRE --force, because the target already holds data.")
        print("This backup is restorable. Close Cadence first when you do it for real.")
        return
    Path(storage_dir).mkdir(parents=True, exist_ok=True)
    targets_exist = keyfile.exists() or enc.exists()
    if targets_exist and not force:
        raise SystemExit(
            "target storage already has data. Close Cadence, then re-run with --force to "
            "overwrite (the current files are saved aside to *.pre-restore first)."
        )
    if targets_exist and force:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        for p in (keyfile, enc):
            if p.exists():
                aside = p.with_name(p.name + f".pre-restore-{stamp}")
                shutil.copy2(p, aside)
                print(f"saved current {p.name} -> {aside.name}")

    shutil.copy2(src_key, keyfile)
    if src_enc.exists():
        shutil.copy2(src_enc, enc)
    ok, msg = verify_pair(keyfile, enc)
    if not ok:
        raise SystemExit(f"restore wrote files but they don't verify: {msg}")
    print(f"restore OK -> {storage_dir}")
    print("Launch Cadence and confirm the roster and a few notes appear.")


def do_list(dest: Path) -> None:
    dest = Path(dest)
    if not dest.exists():
        raise SystemExit(f"no such folder: {dest}")
    rows = sorted(p for p in dest.glob("cadence-backup-*") if p.is_dir())
    if not rows:
        print(f"no backups found in {dest}")
        return
    for p in rows:
        enc = p / ENC_NAME
        size = f"{enc.stat().st_size/1024:.0f} KB" if enc.exists() else "keyfile only"
        print(f"  {p.name}   ({size})")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Backup/restore Cadence's encrypted patient store.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("backup", help="copy keyfile + DB to a timestamped folder under --dest")
    b.add_argument("--dest", required=True)
    l = sub.add_parser("list", help="list backups under --dest")
    l.add_argument("--dest", required=True)
    r = sub.add_parser("restore", help="restore a backup folder into app/storage")
    r.add_argument("backup_dir")
    r.add_argument("--force", action="store_true")
    r.add_argument("--dry-run", action="store_true",
                   help="rehearse: verify the backup and report what WOULD change, writing nothing")
    sub.add_parser("verify", help="check the live keyfile + DB decrypt as a pair")

    args = ap.parse_args(argv)
    if args.cmd == "backup":
        do_backup(Path(args.dest))
    elif args.cmd == "list":
        do_list(Path(args.dest))
    elif args.cmd == "restore":
        do_restore(Path(args.backup_dir), force=args.force, dry_run=args.dry_run)
    elif args.cmd == "verify":
        keyfile, enc = _paths(DEFAULT_STORAGE)
        ok, msg = verify_pair(keyfile, enc)
        print(("OK: " if ok else "PROBLEM: ") + msg)
        return 0 if ok else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
