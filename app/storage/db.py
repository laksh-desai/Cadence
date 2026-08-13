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

#: Derived from ENC_PATH at call time, never a fixed constant: the lock guards a SPECIFIC
#: database file, so redirecting ENC_PATH (as every temp-DB test does) must redirect the lock with
#: it. A module-level constant made the suite collide with the real app server's lock the moment
#: the server was running — the tests were locking a database they weren't using.
LOCKFILE = STORAGE_DIR / ".dblock"


def _lock_path() -> Path:
    return ENC_PATH.parent / ".dblock"

_runtime_dir: Path | None = None
_runtime_db_path: Path | None = None
#: (mtime_ns, size) of cadence.db.enc as we loaded it, so persist() can tell whether someone
#: else wrote the file while we held a decrypted copy.
_loaded_stamp: tuple[int, int] | None = None


class DatabaseInUseError(RuntimeError):
    """Another process already has the database open for writing."""


class StaleDatabaseError(RuntimeError):
    """The encrypted file changed underneath us; writing would destroy the other writer's data."""


def _pid_alive(pid: int) -> bool:
    """Best-effort liveness check, so a lock left behind by a crash is reclaimable."""
    try:
        import ctypes
        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED
        if handle:
            ctypes.windll.kernel32.CloseHandle(handle)
            return True
        return False
    except Exception:
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False
        except Exception:
            return True   # unknown -> assume alive; refusing is the safe direction


def _acquire_lock() -> None:
    """Refuse to open the DB for writing if another PROCESS already has it.

    This is a data-loss guard, not tidiness. Every process decrypts `cadence.db.enc` into its OWN
    temp working copy and `persist()` writes that whole copy back — so two writers are
    last-writer-wins over the entire database, not a merge. Concretely: with the app server open,
    running a script that adds patients and then saving one note in the browser re-encrypts the
    server's STALE copy over the file and silently destroys everything the script wrote.

    Re-entry from the same PID is allowed, because the test suite legitimately calls init() again
    after shutdown() within one process.
    """
    lock = _lock_path()
    if lock.exists():
        try:
            holder = int(lock.read_text(encoding="utf-8").strip() or 0)
        except ValueError:
            holder = 0
        if holder and holder != os.getpid() and _pid_alive(holder):
            raise DatabaseInUseError(
                f"The Cadence database is already open by process {holder} (most likely the "
                f"app server). Two processes writing it would overwrite each other's changes: "
                f"the whole file is re-encrypted on every save, so the loser's data is gone. "
                f"Close the app (or stop the other script) and try again."
            )
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text(str(os.getpid()), encoding="utf-8")


def _stamp() -> tuple[int, int] | None:
    try:
        st = ENC_PATH.stat()
        return (st.st_mtime_ns, st.st_size)
    except FileNotFoundError:
        return None


def _release_lock() -> None:
    try:
        lock = _lock_path()
        if lock.exists() and lock.read_text(encoding="utf-8").strip() == str(os.getpid()):
            lock.unlink()
    except OSError:
        pass


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
    _acquire_lock()
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

    global _loaded_stamp
    _loaded_stamp = _stamp()

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
    if "synthetic" not in existing:
        conn.execute("ALTER TABLE patients ADD COLUMN synthetic INTEGER NOT NULL DEFAULT 0")

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
    """Re-encrypt the current working DB back to disk. Call after every write.

    Refuses if `cadence.db.enc` changed on disk since we decrypted it. persist() writes our WHOLE
    working copy, so overwriting a file another process has since updated silently destroys
    everything they wrote — there is no merge. The near-miss this was written for: the app server
    sat open while a script seeded 12 patients, and the server's ordinary shutdown-persist would
    have rolled the database back to its own hours-old snapshot with no error shown.

    Recovery is to reopen the app (which re-decrypts the current file); the in-memory changes of
    the losing process are forfeit, which is the correct trade against destroying the winner's.
    """
    global _loaded_stamp
    if _runtime_db_path is None:
        raise RuntimeError("db.init() must be called before persist()")
    current = _stamp()
    if _loaded_stamp is not None and current is not None and current != _loaded_stamp:
        raise StaleDatabaseError(
            "cadence.db.enc changed on disk after this process opened it, so saving now would "
            "overwrite whatever wrote it. Nothing has been written. Close and reopen the app to "
            "pick up the current database."
        )
    plaintext = _runtime_db_path.read_bytes()
    ciphertext = _fernet().encrypt(plaintext)
    tmp_path = ENC_PATH.with_suffix(".enc.tmp")
    tmp_path.write_bytes(ciphertext)
    os.replace(tmp_path, ENC_PATH)
    _loaded_stamp = _stamp()   # our own write is now the baseline


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
    _release_lock()
