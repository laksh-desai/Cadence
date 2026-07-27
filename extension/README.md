# Cadence → Office Ally (Chrome extension)

Fill an Office Ally note form from a saved **Cadence** note, using a field mapping you set **once**
and the extension **remembers**. It automates the manual copy-paste from Cadence into the EHR.

## Privacy

- **Local only.** The extension talks to exactly two places: the Cadence app on this machine
  (`http://127.0.0.1:8420`) and the Office Ally page open in your tab. It makes **no other network
  calls** — no analytics, no servers. It's the same data movement the clinician does by hand; it
  introduces no new disclosure (Office Ally is the EHR the note goes to regardless).
- It stores **only the field mapping** (which page field maps to which Cadence source) in the
  browser's local storage. Patient data is read only at Fill time and is never saved by the extension.
- Loaded **unpacked** for the practice's own Chrome — not published to the Chrome Web Store.

## Install (one time)

1. Chrome → `chrome://extensions` → turn on **Developer mode** (top right).
2. **Load unpacked** → select this `extension/` folder.
3. Pin the extension so its icon is visible.

No Office Ally domain configuration is needed — the panel injects into whatever tab you're on when
you click the icon (via `activeTab`, only on your click), so it works on Office Ally and on the
local test page below without editing the manifest.

## Try it locally first (no real Office Ally)

Before touching a real chart, validate the mechanics against the included mock form:

1. Make sure **Cadence is running** and has at least one **saved** note (fake data is fine).
2. Serve the test page over http so the panel can inject:
   `cd extension && python -m http.server 8080` → open `http://localhost:8080/test-form.html`.
   (Or open `test-form.html` as a file and enable "Allow access to file URLs" for the extension.)
3. Click the extension icon → a panel appears.
4. Pick a **patient** and a **saved note**. The note's fields appear as a list of *sources*
   (each section, plus patient name/DOB/MRN, plus optional SOAP blocks).
5. For a source, click **Map**, then click the matching field on the page. The extension records a
   selector for that field. Repeat for the fields you care about.
6. Click **Fill Office Ally** — the mapped fields populate. Reload the page and Fill again to confirm
   the mapping persisted.

## Everyday use with Office Ally

1. In Cadence: generate a note, review, and **Save** it to the patient's file.
2. In Office Ally: open the patient's note form.
3. Click the extension icon → pick the patient + the saved note → **Fill Office Ally**.
   - First time on a given form, do the **Map** step once (click each field). After that it's
     just pick-note → Fill.
4. **Review every field in Office Ally before signing** — the clinician is always the final check.

Mappings are saved **per form** (by the page's URL path), so each note type / form can have its own
remembered layout.

## What it maps

Office Ally has many discrete fields, so you map **individual Cadence sections** (Chief Complaint,
Functional Status, Gait Training, …) to individual Office Ally fields. Patient name/DOB/MRN and the
four coarse SOAP blocks are also offered as sources if a field wants them. Sources not present in a
given note are skipped at Fill (a mapped field is never overwritten with blank).

## Limits (v1)

- Pulls **saved** notes via Cadence's local API (save first). Pushing an unsaved review note isn't in v1.
- **Field mapping is manual** (click-to-pick). There's no auto-detection of Office Ally's fields —
  deliberately, since it keeps the extension EHR-agnostic and needs no knowledge of Office Ally's DOM.
- If Chrome's **Private Network Access** ever blocks the extension from reaching `127.0.0.1`, the fix
  is a small CORS/PNA header on Cadence's API (`app/ui/server.py`); not needed unless you see a
  connection error while Cadence is clearly running.

## Tests

Pure helper logic (selector building, marker rendering, source resolution, mapping records):

```
node --test extension/tests/mapping.test.js
```

The DOM parts (click-to-pick, fill) are validated on `test-form.html` and, finally, on a **blank**
Office Ally form — never first on a real patient.

## Files

- `manifest.json` — MV3; permissions `storage`, `activeTab`, `scripting`; host `http://127.0.0.1:8420/*`.
- `background.js` — injects the panel on icon click; proxies read-only fetches to Cadence.
- `content.js` — the in-page panel (shadow-DOM isolated), patient/note picker, click-to-pick, fill.
- `lib/mapping.js` — pure, testable helpers shared by the content script and the node tests.
- `test-form.html` — local mock EHR form for validating without Office Ally.
- `tests/mapping.test.js` — node tests for the pure helpers.
