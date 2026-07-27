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
  used_prior    INTEGER NOT NULL DEFAULT 0
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
