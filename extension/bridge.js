/* Cadence → Office Ally — bridge on the LOCAL Cadence page (http://127.0.0.1:8420) only.
 *
 * Two jobs, both so the clinician never has to set anything up inside the extension:
 *  1. Announce that the extension is installed, so Cadence's "Send to Office Ally" button can
 *     show setup steps when it isn't (data-cadence-extension="<version>" on <html>).
 *  2. Pass the note the clinician chose in Cadence to the extension. When they then open the
 *     panel in Office Ally, that patient and note are already selected.
 *
 * Only Cadence's internal patient and note ids cross this bridge — no note text and no patient
 * details. The note itself is read later, from the local Cadence API, as before.
 */
(function () {
  "use strict";
  if (window.__cadenceBridge) return; // added by both the manifest and the install-time injection
  window.__cadenceBridge = true;
  const version = chrome.runtime.getManifest().version;
  document.documentElement.setAttribute("data-cadence-extension", version);

  // After the extension is reloaded, a copy of this script left in an already-open Cadence tab is cut
  // off ("Extension context invalidated"). It must stay silent then: the new copy answers instead.
  const alive = () => { try { return !!(chrome.runtime && chrome.runtime.id); } catch (_) { return false; } };

  window.addEventListener("message", (e) => {
    if (e.source !== window || e.origin !== location.origin) return;
    if (!alive()) return;
    const d = e.data;
    // Has this note already got an Office Ally encounter? (Office Ally creates one every time an
    // Add Note page opens, so Cadence asks before opening another.) Ids only, both ways.
    if (d && d.type === "cadence-note-encounter-query" && d.noteId) {
      chrome.runtime.sendMessage({ type: "cadence", action: "noteEncounterGet", noteId: String(d.noteId) }, (r) => {
        const rec = !chrome.runtime.lastError && r && r.ok ? r.data : null;
        window.postMessage({ type: "cadence-note-encounter", noteId: d.noteId, eid: rec ? rec.eid : "", filled: !!(rec && rec.filled) }, location.origin);
      });
      return;
    }
    if (!d || d.type !== "cadence-handoff" || !d.patientId || !d.noteId) return;
    chrome.runtime.sendMessage(
      { type: "cadence-handoff", patientId: String(d.patientId), noteId: String(d.noteId) },
      (r) => {
        const ok = !chrome.runtime.lastError && r && r.ok;
        window.postMessage({ type: "cadence-handoff-ack", ok: !!ok, noteId: d.noteId }, location.origin);
      }
    );
  });
})();
