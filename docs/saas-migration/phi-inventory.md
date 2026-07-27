# PHI data-flow inventory (SRA seed)

A Security Risk Analysis starts from *"where is PHI, at rest and in motion, and what could
leak it."* This is that inventory — the current (local) state on the left, the SaaS target on
the right. Derived from a code audit of `app/` on 2026-07-15. Keep it current as the migration
proceeds; it is a required, living HIPAA artifact.

## PHI fields in the data model

| Field | Source | Sensitivity |
|---|---|---|
| `patients.name`, `dob`, `mrn` | `app/storage/schema.sql` | Direct identifiers |
| `patients.condition`, `scheduling_notes` | schema.sql | Clinical / demographic |
| `notes.dictation_raw` | schema.sql | Raw clinical narrative (transcript) |
| `notes.sections_json`, `missing_json` | schema.sql | Generated clinical note bodies |
| `carry_snapshots.precautions`, `functional_status`, `short_term_goals`, `long_term_goals` | schema.sql | Clinical text carried between visits |
| Dictation **audio** (in-flight only) | browser → `POST /api/transcribe` | Voice = identifier; never written to disk today |

## PHI at rest

| Location | Today (local) | Risk today | SaaS target |
|---|---|---|---|
| Primary store | `app/storage/cadence.db.enc` (Fernet AES-128) | Key `.keyfile` sits **in the same dir, plaintext, no passphrase** (`db.py`) | **Aptible-managed PostgreSQL**, platform-encrypted; no app-managed keyfile |
| Running copy | **Whole DB decrypted to OS temp** for the process lifetime (`tempfile.mkdtemp`) | Left behind on crash/kill; readable by any process in the OS account | Eliminated — Postgres, no decrypt-to-temp |
| Backups | none in-app (device-level only) | — | Aptible-managed, encrypted, **tested restore**, retention policy |

## PHI in motion

| Flow | Today | SaaS target |
|---|---|---|
| Browser ↔ backend | `http://127.0.0.1:8420`, **plain HTTP**, loopback only | **TLS only**, public endpoint, authenticated |
| Dictation audio → transcription | in-memory to local MedASR (never leaves device) | Over TLS to **AWS Transcribe Medical** (BAA) |
| Dictation/context → generation | localhost Ollama/MedGemma (never leaves device) | Over TLS to **AWS Bedrock / Claude** (BAA) |
| Roster → Google Sheets | bidirectional; name/DOB/MRN/condition/scheduling_notes; service-account; under the practice's own Google Workspace BAA | Per-practice + optional; each practice's own Workspace/BAA; still on **your** subprocessor list |

## Leakage surfaces to watch (found in audit)

- **Sync error strings** (`sheets_sync.py`) are built as `f"patient {id}: {e}"`, logged and
  returned in `/api/status` + `/api/sync/now`. Carry only UUIDs today, but `{e}` is a raw
  exception string — scrub before it can ever echo a field value.
- **uvicorn access logs** would log request URLs containing patient **UUIDs** (paths like
  `/api/patients/{id}/notes`). UUIDs aren't PHI, but confirm no body logging is ever enabled.
- **Committed secrets:** `hf_config.yaml` (gitignored, not in history), `.sheets_credentials.json`,
  `.keyfile` — all plaintext on disk. In SaaS → secrets manager; none on the app filesystem.
- **The good news to preserve:** the app has **no `print`**, logs IDs not names, and **never
  writes dictation audio or note bodies outside the encrypted store**. Carry these properties into the SaaS.

## New PHI surfaces the SaaS *adds* (must be inventoried)

- Authentication records / session tokens (IdP).
- **Audit log** of who read/changed which patient/note (itself references PHI subjects — protect + retain).
- AI vendor request/response payloads (contain PHI — confirm the vendor's BAA + zero-retention / no-training terms).
- Multi-tenant DB: every PHI row now carries a `practice_id`; a missing tenant filter = cross-practice breach (why Postgres RLS is the backstop).
