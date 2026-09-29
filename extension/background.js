/* Cadence → Office Ally — background service worker.
 *
 * Two jobs:
 *  1. On toolbar-icon click, inject the panel into the ACTIVE tab (activeTab grants access on the
 *     user gesture, so the extension needs no broad host permission for the EHR page — and works on
 *     the local test-form.html too). The content script guards against double-injection.
 *  2. Proxy read-only fetches to the LOCAL Cadence app. Doing the fetch here (not in the content
 *     script) avoids the https-page → http-localhost mixed-content block, and host_permissions for
 *     127.0.0.1 means it isn't CORS-restricted. No other origin is ever contacted.
 */

const CADENCE_BASE = "http://127.0.0.1:8420";

chrome.action.onClicked.addListener(async (tab) => {
  if (!tab || !tab.id) return;
  try {
    await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      files: ["lib/mapping.js", "lib/oaroute.js", "content.js"],
    });
    // content.js toggles itself on (re-)injection; this message is a no-op safety net.
    chrome.tabs.sendMessage(tab.id, { type: "cadence-panel", action: "toggle" }, () => void chrome.runtime.lastError);
  } catch (e) {
    // Most commonly: injected into a restricted page (chrome://, the Web Store). Nothing to do.
    console.warn("Cadence: could not open panel on this page:", e && e.message);
  }
});

// Chrome only adds manifest content scripts to pages loaded AFTER install, so a Cadence tab that was
// open during setup wouldn't see the extension until refreshed. Add the bridge to those tabs now,
// so the setup pop-up's "Check again" works without a reload.
chrome.runtime.onInstalled.addListener(async () => {
  try {
    const tabs = await chrome.tabs.query({ url: ["http://127.0.0.1:8420/*", "http://localhost:8420/*"] });
    for (const t of tabs) {
      chrome.scripting.executeScript({ target: { tabId: t.id }, files: ["bridge.js"] }).catch(() => {});
    }
  } catch (_) { /* nothing open, or not permitted — a refresh still works */ }
});

async function cadenceGet(path) {
  const resp = await fetch(CADENCE_BASE + path, { method: "GET", cache: "no-store" });
  if (!resp.ok) throw new Error("Cadence returned HTTP " + resp.status);
  return resp.json();
}

const ROUTES = {
  patients: () => "/api/patients",
  officeSettings: () => "/api/office-ally/settings",
  patient: (m) => "/api/patients/" + encodeURIComponent(m.patientId),
  notes: (m) => "/api/patients/" + encodeURIComponent(m.patientId) + "/notes",
  note: (m) => "/api/patients/" + encodeURIComponent(m.patientId) + "/notes/" + encodeURIComponent(m.noteId),
};

// The note the clinician chose with Cadence's "Send to Office Ally" button: ids only, held for a
// working day so a panel opened hours later still knows, then forgotten. Session storage is
// cleared when Chrome closes.
const HANDOFF_TTL_MS = 12 * 60 * 60 * 1000;
const handoffStore = chrome.storage.session || chrome.storage.local;

// Which Office Ally encounter each Cadence note went to: ids only, never note text. Office Ally
// creates an encounter the moment an Add Note page opens, so without this every repeated "Create"
// leaves another blank encounter in the chart. Kept 30 days, then forgotten.
const NOTE_ENCOUNTER_TTL_MS = 30 * 24 * 60 * 60 * 1000;

function noteEncounters(cb) {
  chrome.storage.local.get("noteEncounters", (d) => {
    const all = (d && d.noteEncounters) || {};
    const now = Date.now();
    Object.keys(all).forEach((k) => { if (!all[k] || now - all[k].at > NOTE_ENCOUNTER_TTL_MS) delete all[k]; });
    cb(all);
  });
}

// A draft was just saved in this tab (Apply reloads the page). When the reload finishes, reopen
// the panel so it checks the SAVED boxes against the note. Ids only; forgotten after 2 minutes.
const VERIFY_TTL_MS = 2 * 60 * 1000;
const pendingVerify = {}; // tabId -> { patientId, noteId, eid, at }

chrome.tabs.onUpdated.addListener((tabId, info) => {
  const p = pendingVerify[tabId];
  if (!p || info.status !== "complete") return;
  if (Date.now() - p.at > VERIFY_TTL_MS) { delete pendingVerify[tabId]; return; }
  chrome.scripting.executeScript({ target: { tabId: tabId }, files: ["lib/mapping.js", "lib/oaroute.js", "content.js"] })
    .catch(() => { /* Chrome may not allow it after a reload; the clinician clicks the icon instead */ });
});

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  const tabId = sender && sender.tab && sender.tab.id;
  if (msg && msg.type === "cadence" && msg.action === "noteEncounterGet") {
    noteEncounters((all) => sendResponse({ ok: true, data: all[String(msg.noteId)] || null }));
    return true;
  }
  if (msg && msg.type === "cadence" && msg.action === "noteEncounterSet") {
    noteEncounters((all) => {
      const prev = all[String(msg.noteId)];
      all[String(msg.noteId)] = { eid: String(msg.eid || ""), pid: String(msg.pid || ""),
        filled: msg.filled === false ? !!(prev && prev.eid === String(msg.eid) && prev.filled) : true, at: Date.now() };
      chrome.storage.local.set({ noteEncounters: all }, () => sendResponse({ ok: true }));
    });
    return true;
  }
  if (msg && msg.type === "cadence" && msg.action === "verifyAfterSave") {
    if (tabId) pendingVerify[tabId] = { patientId: msg.patientId, noteId: msg.noteId, eid: msg.eid, at: Date.now() };
    sendResponse({ ok: true });
    return false;
  }
  if (msg && msg.type === "cadence" && msg.action === "verifyPending") {
    const p = tabId && pendingVerify[tabId];
    if (tabId) delete pendingVerify[tabId];
    sendResponse({ ok: true, data: p && Date.now() - p.at < VERIFY_TTL_MS ? p : null });
    return false;
  }
  if (msg && msg.type === "cadence-handoff") {
    // Only the bridge on the local Cadence page may set it.
    const from = (sender && sender.url) || "";
    if (!/^http:\/\/(127\.0\.0\.1|localhost):8420\//.test(from)) { sendResponse({ ok: false }); return false; }
    handoffStore.set({ handoff: { patientId: msg.patientId, noteId: msg.noteId, at: Date.now() } }, () => sendResponse({ ok: true }));
    return true;
  }
  if (msg && msg.type === "cadence" && msg.action === "handoff") {
    handoffStore.get("handoff", (d) => {
      const h = d && d.handoff;
      sendResponse({ ok: true, data: h && Date.now() - h.at < HANDOFF_TTL_MS ? h : null });
    });
    return true;
  }
  if (!msg || msg.type !== "cadence") return false;
  const route = ROUTES[msg.action];
  if (!route) {
    sendResponse({ ok: false, error: "unknown action: " + msg.action });
    return false;
  }
  cadenceGet(route(msg))
    .then((data) => sendResponse({ ok: true, data }))
    .catch((e) =>
      sendResponse({
        ok: false,
        error:
          (e && e.message) ||
          "Could not reach Cadence. Is the app running at " + CADENCE_BASE + "?",
      })
    );
  return true; // async sendResponse
});
