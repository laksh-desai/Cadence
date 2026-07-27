# Device-level safeguards checklist

CLAUDE.md's roadmap (item 7) treats these as a separate, required layer on top of
everything the app itself does — the app's encryption protects the data *file*;
these settings protect the *device* it lives on. Per `docs/hipaa-local.md`, this is
the actual backstop for "laptop is lost, stolen, or left unlocked" — the app-level
encryption alone does not cover that scenario.

This is a checklist for the laptop itself (Settings app), not code — nothing here
needed a code change. Current state checked on 2026-06-29 (this machine: Windows 10
Pro, not domain-joined):

## 1. Full-disk encryption (BitLocker)

**Status: could not verify automatically** — checking or enabling BitLocker
requires administrator rights, which this session doesn't have (and enabling
full-disk encryption is the kind of action that should be a deliberate, in-person
decision anyway — it can take hours to complete and produces a recovery key that
must be stored safely, so it isn't something to script unattended).

**To check/enable it yourself:**
1. Settings → Privacy & security → Device encryption (or search "BitLocker" in the
   Start menu → "Manage BitLocker").
2. If it shows **On** for the C: drive, you're done — skip to step 2 below.
3. If it's **Off**, click **Turn on BitLocker** for the C: drive and follow the
   wizard.
4. **The recovery key matters as much as turning it on.** The wizard will ask
   where to save the recovery key — for a HIPAA-conscious setup, save it to a
   Microsoft account (if you're comfortable with that) or print it and store it
   somewhere physically secure (a locked drawer, not taped to the laptop). Losing
   both the laptop's login *and* the recovery key means the data is permanently
   unrecoverable — that's the trade-off full-disk encryption makes.
5. Note: BitLocker needs Windows 10/11 **Pro** (this machine has it) — Home
   editions only get the lighter "Device encryption," which has narrower hardware
   requirements (TPM + Modern Standby) and may not be available depending on the
   hardware.

## 2. Lock-screen auto-lock

**Status: checked, partially configured.** This machine currently:
- Turns off the display after **5 minutes** (300s, both plugged in and on battery).
- Goes to sleep after **10 minutes** (600s).

Display-off and sleep are not the same as *requiring a password to get back in* —
that's a separate toggle this session couldn't verify programmatically. **Confirm
it yourself:**

1. Settings → Accounts → Sign-in options.
2. Find **"If you've been away, when should Windows require you to sign in
   again?"** (wording varies slightly by Windows version) and set it to **When PC
   wakes up from sleep** (the strictest option available without third-party
   tools).
3. Optionally tighten the timeouts in step 1 above (Settings → System → Power &
   sleep) — 5/10 minutes is reasonable for a clinic setting where the laptop might
   be left mid-session, but shorten it if the laptop is ever in a more open area.

## 3. Local-only backups

Already a documented constraint in `docs/hipaa-local.md`, restated here as a
checklist item rather than just narrative: **never** let `app/storage/cadence.db.enc`
or `app/storage/.keyfile` (or, now, `app/integrations/.sheets_credentials.json`)
get swept into a cloud backup/sync tool (OneDrive, Google Drive desktop sync, etc.)
without re-evaluating the threat model first. Worth specifically checking:

- This machine's OneDrive is already in use (the desktop shortcut setup found
  `OneDrive\Desktop` as the actual Desktop path) — **confirm the project folder
  itself isn't inside a OneDrive-synced directory.** If
  `c:\Users\kusha.DESKTOP-PGUPO2J\Modality_Project` is ever moved under
  `OneDrive\...`, the encrypted database and keyfile would start syncing to
  Microsoft's cloud automatically, which is a different third party with no BAA in
  place at all (separate from the Google Workspace exception, and not covered by
  it). It's currently outside OneDrive (`C:\Users\...\Modality_Project`, not under
  `OneDrive\`) — keep it that way.
- If/when backups are wanted, local-only (a second internal drive, a USB drive kept
  on-site, or an encrypted external drive) is the safe option — never a
  cloud-sync folder.

## Not covered here

One roadmap item from CLAUDE.md is explicitly **not** a device setting and isn't
addressed by this checklist:
- Validating model output against the clinician's actual judgment (needs real
  usage, not a setting).

(Local transcription replacing the browser's Web Speech API — previously listed
here as in-progress — is now implemented via local MedASR; see
`docs/medasr-setup.md`.)
