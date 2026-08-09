CREATE TABLE IF NOT EXISTS patients (
  id                TEXT PRIMARY KEY,
  name              TEXT NOT NULL,
  dob               TEXT,
  mrn               TEXT,
  condition         TEXT,
  created_at        TEXT NOT NULL,
  scheduling_notes  TEXT,
  updated_at        TEXT NOT NULL DEFAULT '1970-01-01T00:00:00+00:00',
  sheet_synced_at   TEXT
);

CREATE TABLE IF NOT EXISTS notes (
  id            TEXT PRIMARY KEY,
  patient_id    TEXT NOT NULL REFERENCES patients(id),
  form_id       TEXT NOT NULL,
  form_name     TEXT NOT NULL,
  created_at    TEXT NOT NULL,
  sections_json TEXT NOT NULL,
  missing_json  TEXT NOT NULL,
  dictation_raw TEXT NOT NULL,
  used_prior    INTEGER NOT NULL DEFAULT 0,

  -- Correction capture. The model's own output BEFORE the clinician touched it, plus the
  -- provenance needed to interpret it later. Until these existed, every correction was destroyed
  -- on edit and a blindly-accepted note was indistinguishable from a rewritten one.
  --
  -- This is real patient content and stays in this encrypted row: it is deliberately NOT on the
  -- HTTP read surface (NoteOut/NoteListItem are unchanged), and app/integrations/sheets_sync.py
  -- reads the `patients` roster ONLY, so the Google Workspace BAA carve-out does not extend here.
  -- There must never be a notes -> file export; if one is ever built it must filter
  -- `WHERE synthetic = 1` at the SQL level. tests/test_correction_capture.py enforces that.
  --
  -- NULL vs 0 is the whole point of the feature: NULL means "not captured" (a pre-migration
  -- note), 0 means "the clinician accepted it as generated". A NOT NULL DEFAULT 0 here would
  -- make every old note look blindly-accepted and destroy the signal being built.
  original_sections_json   TEXT,     -- post-pipeline sections AS SHOWN to the clinician
  revise_instructions_json TEXT,     -- [{text, applied, at}] — the plain-language change requests
  edited_section_count     INTEGER,  -- NULL = not captured; 0 = accepted as generated
  model_id                 TEXT,     -- ollama_client.model_for(fast) at generation time
  fast_tier                INTEGER,  -- NULL = unknown (legacy rows)
  template_spec_sha        TEXT,     -- forms.spec_sha() at generation time
  template_customized      INTEGER,
  -- The one NOT NULL DEFAULT, because "unknown" must never read as "safe to export".
  synthetic                INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_notes_patient ON notes(patient_id, created_at);

CREATE TABLE IF NOT EXISTS carry_snapshots (
  patient_id         TEXT PRIMARY KEY REFERENCES patients(id),
  source_note_id     TEXT NOT NULL REFERENCES notes(id),
  updated_at         TEXT NOT NULL,
  precautions        TEXT,
  functional_status  TEXT,
  short_term_goals   TEXT,
  long_term_goals    TEXT
);
