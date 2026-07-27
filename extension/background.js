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
      files: ["lib/mapping.js", "content.js"],
    });
    // content.js toggles itself on (re-)injection; this message is a no-op safety net.
    chrome.tabs.sendMessage(tab.id, { type: "cadence-panel", action: "toggle" }, () => void chrome.runtime.lastError);
  } catch (e) {
    // Most commonly: injected into a restricted page (chrome://, the Web Store). Nothing to do.
    console.warn("Cadence: could not open panel on this page:", e && e.message);
  }
});

async function cadenceGet(path) {
  const resp = await fetch(CADENCE_BASE + path, { method: "GET", cache: "no-store" });
  if (!resp.ok) throw new Error("Cadence returned HTTP " + resp.status);
  return resp.json();
}

const ROUTES = {
  patients: () => "/api/patients",
  patient: (m) => "/api/patients/" + encodeURIComponent(m.patientId),
  notes: (m) => "/api/patients/" + encodeURIComponent(m.patientId) + "/notes",
  note: (m) => "/api/patients/" + encodeURIComponent(m.patientId) + "/notes/" + encodeURIComponent(m.noteId),
};

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
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
