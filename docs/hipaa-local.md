# Local/offline compliance posture

Cadence's privacy stance comes almost entirely from staying on-device. The one
exception is Google Workspace: the practice has a signed Business Associate
Agreement with Google under its Workspace business account, and that's the only
third party PHI may ever reach. This file documents the concrete safeguards and,
just as importantly, what they do **not** cover.

## What runs where

- Transcription, note generation (MedGemma 4B via Ollama), and storage all run as
  local processes on the clinician's laptop.
- The FastAPI backend binds to `127.0.0.1` only — it is never reachable from the
  network, even on the same LAN.
- No PHI is ever sent to any cloud service **except Google Workspace**, under the
  practice's signed BAA with Google for its Workspace business account (e.g. a
  patient/notes view synced to Google Sheets). This is a narrow, named exception —
  see CLAUDE.md's non-negotiable constraints — not a general allowance. A
  personal/consumer Google account is not covered by that BAA and must never receive
  PHI. The only other cloud call that ever existed (in `cadence-prototype.html`) is
  fake-data-only, unrelated to the Google Workspace exception, and not part of the
  production path.

## At-rest encryption: what it is

Patient and note data lives in `app/storage/cadence.db.enc`, a SQLite database
encrypted with Fernet (AES-128-CBC + HMAC, via the `cryptography` package). The
encryption key is a single 32-byte value stored in `app/storage/.keyfile`, generated
on first run.

On startup, the backend decrypts `cadence.db.enc` into a plaintext working copy
outside the repo and operates on that copy. Every save re-encrypts the working copy
back to `cadence.db.enc` (atomic write: temp file + replace, so a crash mid-write
can't corrupt the on-disk ciphertext). On clean shutdown, the backend does a final
re-encrypt and deletes the plaintext working copy.

## What at-rest encryption protects — and what it doesn't

This protects:
- `cadence.db.enc` while the app is **not running** (e.g. the laptop is off or
  asleep with the app closed).
- Copies of `cadence.db.enc` taken off the machine (a USB backup, a misdirected
  cloud-sync folder, etc.) — without the keyfile, the file is unreadable.

This does **not** protect:
- The plaintext working copy while the app is actively running. Any process with
  access to the OS account could in principle read it, the same way any local app's
  in-memory or temp-file state is exposed to its own user account. There is no app
  built on a single local process that can fully close this gap without a hardware
  security module, which is out of scope for this app.
- The encryption key itself, if someone has filesystem access to `.keyfile`. There
  is no passphrase gate — by design (see below).

**The actual backstop for "laptop is lost or stolen while the app or OS is
running/unlocked" is the device-level safeguard, not the app-level encryption:**
Windows full-disk encryption (BitLocker) and a lock-screen password with auto-lock.
Per the CLAUDE.md roadmap, these are a separate, later checklist item — turn them on
on the production laptop regardless of what the app does.

## Key management

A bare keyfile, no passphrase, because:
- This is a single clinician on her own laptop — no multi-user access control is
  needed.
- A typed passphrase on every launch is friction with no real benefit here: the
  actual access boundary this app relies on is the Windows account login + BitLocker,
  not an app-level password. Adding one would mostly just be a place to type a
  password that doesn't change the real threat model.

**Future option, not built now:** if the threat model ever changes (e.g. deploying
to a less-trusted environment), derive the Fernet key from a typed passphrase via
PBKDF2/Argon2, with the keyfile holding only a salt. Key rotation is also out of
scope for this phase.

## Still on the roadmap (CLAUDE.md item 7)

- Full-disk encryption (BitLocker) on the production laptop.
- OS login + auto-lock.
- Local-only backups (no cloud backup of `cadence.db.enc` or the keyfile without
  re-evaluating this threat model).
