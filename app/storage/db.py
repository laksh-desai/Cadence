"""Encryption lifecycle for the local SQLite store.

No PHI-capable file is ever written to disk unencrypted except the runtime working
copy used while the process is alive (see docs/hipaa-local.md for the threat model
this is and isn't covering). On startup: decrypt cadence.db.enc into a temp working
copy. On every write: re-encrypt that working copy back to cadence.db.enc via an
atomic replace. On clean shutdown: final re-encrypt, then delete the working copy.
"""

import os
import sqlite3
import tempfile
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

STORAGE_DIR = Path(__file__).resolve().parent
KEYFILE = STORAGE_DIR / ".keyfile"
ENC_PATH = STORAGE_DIR / "cadence.db.enc"
SCHEMA_PATH = STORAGE_DIR / "schema.sql"

_runtime_dir: Path | None = None
_runtime_db_path: Path | None = None


def _load_or_create_key() -> bytes:
    if KEYFILE.exists():
        return KEYFILE.read_bytes().strip()
    key = Fernet.generate_key()
    KEYFILE.write_bytes(key)
    return key


def _fernet() -> Fernet:
    return Fernet(_load_or_create_key())


def init() -> Path:
    """Decrypt (or create) the working DB copy and apply the schema. Returns the
    runtime DB path. Safe to call once at process startup."""
    global _runtime_dir, _runtime_db_path
    _runtime_dir = Path(tempfile.mkdtemp(prefix="cadence_"))
    _runtime_db_path = _runtime_dir / "cadence.db"

    if ENC_PATH.exists():
        try:
            plaintext = _fernet().decrypt(ENC_PATH.read_bytes())
        except InvalidToken as e:
            raise RuntimeError(
                f"Could not decrypt {ENC_PATH} with the current keyfile. "
                "If the keyfile was lost or replaced, the database is unrecoverable."
            ) from e
        _runtime_db_path.write_bytes(plaintext)

    conn = sqlite3.connect(_runtime_db_path)
    try:
        conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        _migrate(conn)
        conn.commit()
    finally:
        conn.close()

    return _runtime_db_path


def _migrate(conn: sqlite3.Connection) -> None:
    """CREATE TABLE IF NOT EXISTS won't add columns to a table that already existed
    before this column was introduced. Check what's there and patch it up."""
    existing = {row[1] for row in conn.execute("PRAGMA table_info(patients)")}
    if "scheduling_notes" not in existing:
        conn.execute("ALTER TABLE patients ADD COLUMN scheduling_notes TEXT")
    if "updated_at" not in existing:
        conn.execute(
            "ALTER TABLE patients ADD COLUMN updated_at TEXT NOT NULL "
            "DEFAULT '1970-01-01T00:00:00+00:00'"
        )
    if "sheet_synced_at" not in existing:
        conn.execute("ALTER TABLE patients ADD COLUMN sheet_synced_at TEXT")

    # Correction capture (see the column comments in schema.sql). Both halves are required:
    # executescript's CREATE TABLE IF NOT EXISTS is a no-op on an existing table, and this block
    # is a no-op on a fresh one. Every column is nullable except `synthetic`, so a pre-migration
    # note reads as "not captured" rather than "accepted as generated".
    note_cols = {row[1] for row in conn.execute("PRAGMA table_info(notes)")}
    for column, ddl in (
        ("original_sections_json", "TEXT"),
        ("revise_instructions_json", "TEXT"),
        ("edited_section_count", "INTEGER"),
        ("model_id", "TEXT"),
        ("fast_tier", "INTEGER"),
        ("template_spec_sha", "TEXT"),
        ("template_customized", "INTEGER"),
        ("synthetic", "INTEGER NOT NULL DEFAULT 0"),
    ):
        if column not in note_cols:
            conn.execute(f"ALTER TABLE notes ADD COLUMN {column} {ddl}")


def get_connection() -> sqlite3.Connection:
    if _runtime_db_path is None:
        raise RuntimeError("db.init() must be called before get_connection()")
    conn = sqlite3.connect(_runtime_db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def persist() -> None:
    """Re-encrypt the current working DB back to disk. Call after every write."""
    if _runtime_db_path is None:
        raise RuntimeError("db.init() must be called before persist()")
    plaintext = _runtime_db_path.read_bytes()
    ciphertext = _fernet().encrypt(plaintext)
    tmp_path = ENC_PATH.with_suffix(".enc.tmp")
    tmp_path.write_bytes(ciphertext)
    os.replace(tmp_path, ENC_PATH)


def shutdown() -> None:
    """Final persist + remove the plaintext working copy."""
    global _runtime_dir, _runtime_db_path
    if _runtime_db_path is not None and _runtime_db_path.exists():
        persist()
        try:
            _runtime_db_path.unlink()
        except OSError:
            pass
    if _runtime_dir is not None and _runtime_dir.exists():
        try:
            _runtime_dir.rmdir()
        except OSError:
            pass
    _runtime_dir = None
    _runtime_db_path = None
