# Releasing Cadence, and how an installed copy takes an update

Two audiences: whoever cuts the release (you), and whoever runs it (the practice). The mechanics
are in `scripts/release.py` and `scripts/update.py`; this is the why and the order.

## The install layout

An installed Cadence separates the **program** from the **clinician's data**, because an update
replaces the former and must never touch the latter.

```
C:\Cadence\
  versions\1.0.0\     the program — replaced wholesale by an update
  versions\1.1.0\     the previous one, kept so a rollback is a pointer flip
  current  ->         directory junction to the active version
  data\               CADENCE_DATA_DIR — an update cannot reach in here
    storage\          cadence.db.enc, .keyfile      <- irreplaceable
    templates\        the clinician's own templates and their edits to the built-ins
    config\           hf_config.yaml, sheets_config.yaml, .sheets_credentials.json
    backups\          written automatically before every update
```

`current` is a **junction**, not a symlink: Windows creates junctions without administrator
rights, and an update the clinician cannot run is not an update.

Two things deliberately travel WITH the code, not with the data:

- **Built-in templates** (`templates/*.md`) — an update should improve them. Only the clinician's
  `overrides/` and `custom/` are preserved.
- **`schema.sql`** — a version's migrations are part of that version.

A development checkout sets no `CADENCE_DATA_DIR`, so every path stays exactly where it always
was. That is why the test suite is unaffected by any of this.

## Cutting a release

1. **Bump the version** in `app/__init__.py`. It is the single source of truth, it appears on the
   Status page, and it is stamped onto every note saved by that build.
2. **Write the release notes** at `docs/release-notes/<version>.md`, in clinical language — what
   changes about *the notes*, not what changed in the code. This is the text the clinician reads
   before deciding to update.
3. **Build:**
   ```
   python scripts/release.py
   ```
   It refuses to build from a dirty tree, with failing tests (the deliberate billing sign-off gate
   is the one permitted failure), or on a version that is already tagged. It packages an
   **allowlist** of source files and asserts that no database, keyfile, or credential is inside.
4. **Tag and publish:**
   ```
   git tag -a v1.0.0 -m "Cadence 1.0.0"
   git push origin v1.0.0
   gh release create v1.0.0 dist/cadence-1.0.0.zip dist/cadence-1.0.0.zip.sha256 \
      --title "Cadence 1.0.0" --notes-file docs/release-notes/1.0.0.md
   ```
5. **Update `site/latest.json`** with the new version, URL, SHA-256 (printed by the build) and the
   changes list. This one file drives both the download page and the in-app update check, so they
   cannot drift apart.

## How an installed copy updates

```
python scripts\update.py --check      # what's new, in plain language. Downloads nothing.
python scripts\update.py --apply      # backup -> download -> verify -> install -> switch
python scripts\update.py --rollback   # back to the previous version
```

Order of operations in `--apply`, and why:

1. **Refuse if Cadence is open.** This reuses the *database lock* rather than inventing a second
   liveness check that could disagree with it.
2. **Back up first**, via `scripts/backup.py`, which verifies the backup actually decrypts.
3. **Download and verify the SHA-256 before extracting anything.**
4. **Extract beside the current version.** `current` still points at the old one.
5. **Repoint `current` last** — so an interrupted update leaves an unused folder, not a broken app.

**There is no auto-update.** An update changes what notes *say*, so it waits for a human.

Rolling forward is always safe (migrations only ever ADD columns). Rolling back is supported, but
an older build does not know about a column a newer one added — so roll back, then stay there
until the problem is fixed, rather than hopping between versions while saving notes.

## Private now, public later

`site/` is written for one practice and is safe to publish as-is — no patient data, no secrets.
Publishing it is a **product decision, not a deployment step**: a public download means strangers
run Cadence on real patients, which brings a support burden and, until the ICD tables are signed
off, a liability the billing gate only partly covers. Making it public is a one-line change
(enable Pages, share the link); nothing in the code or the page changes.

## What ships switched off

Billing code suggestions. `cpt.billing_enabled()` is **computed** from
`coding_tables.TABLE_PROVENANCE`, so it cannot be left on by forgetting a setting, and it turns
itself on the moment the last ICD region is signed off — no reinstall. The Status page states the
reason. See `scripts/coding_signoff.py`.
