/* Cadence → Office Ally — in-page panel (injected on toolbar-icon click).
 *
 * A draggable panel (isolated in a shadow root so Office Ally's CSS can't touch it) that: connects
 * to the local Cadence app (via the background proxy), lets the clinician pick a patient + saved
 * note, click-to-map each Cadence source onto an Office Ally field, remembers that mapping per form,
 * and fills the fields on demand. No PHI is stored — only field selectors.
 */
(function () {
  "use strict";
  const M = window.CadenceMap;
  const R = window.CadenceRoute;
  if (!M || !R) { console.error("Cadence: extension libs not loaded"); return; }

  // Re-injection (icon clicked again) → just toggle the existing panel.
  if (window.__cadenceOA) { window.__cadenceOA.toggle(); return; }

  const state = {
    formKey: M.formKeyFromUrl(location.href),
    mappings: {},
    mapping: null,
    patients: [],
    patient: null,
    note: null,
    sources: [],
    picking: null,
    page: readPage(),
    layoutRules: null, // from Cadence's Manage Office settings; null → built-in defaults
    plan: null,
    gapsAcknowledged: false,
    dupAcknowledged: false,
  };

  // ---------- what Office Ally page is this? ----------
  // Patient ID and layout come from the page itself, so the fill can refuse the wrong chart.
  function readPage() {
    let pid = "";
    try { pid = new URL(location.href).searchParams.get("PID") || ""; } catch (_) { /* not a URL we can parse */ }
    const lbl = document.getElementById("ctl00_phFolderContent_myPatientHeader_lblPatientID");
    if (!pid && lbl) pid = lbl.textContent.trim();
    const layoutSel = document.getElementById(R.FIELD_PREFIX + "ddlSoapLayout");
    const opt = layoutSel && layoutSel.options[layoutSel.selectedIndex];
    // The encounter being edited: its id (hidden field, else the page title) and its date (the
    // Encounter Date month/day/year boxes, read live so a date the clinician just changed counts).
    const eidField = document.getElementById(R.FIELD_PREFIX + "EncounterID");
    let eid = eidField ? String(eidField.value || "").trim() : "";
    if (!eid) {
      const t = document.getElementById(R.FIELD_PREFIX + "lblTitle");
      const m = t && /Encounter ID\s+(\d+)/i.exec(t.textContent);
      if (m) eid = m[1];
    }
    const part = (p) => { const el = document.getElementById(R.FIELD_PREFIX + "EncounterDate_" + p); return el ? el.value : ""; };
    const encDate = part("Month") ? { month: part("Month"), day: part("Day"), year: part("Year") } : "";
    let urlLayout = "";
    try { urlLayout = new URL(location.href).searchParams.get("SoapLayoutID") || ""; } catch (_) { /* ignore */ }
    const titleEl = document.getElementById(R.FIELD_PREFIX + "lblTitle");
    return { pid: pid, layoutName: opt ? opt.textContent.trim() : "", layoutId: opt ? opt.value : urlLayout,
      isNew: R.isNewEncounter(location.href, titleEl ? titleEl.textContent : ""),
      encounterId: eid, encounterDate: encDate };
  }

  // This patient's encounter list, read from Office Ally's own Encounters page in the clinician's
  // logged-in session (same site, nothing leaves the browser). null = could not be read.
  // Returns { loggedOut: true } when Office Ally answers with its sign-in page (the session has
  // timed out), the parsed list otherwise, or null when it could not be read at all.
  async function loadEncounters(pid) {
    if (!pid || !/officeally\.com$/i.test(location.hostname)) return null;
    // The patient's Progress Notes list (where encounters are deleted) first, then the chart's
    // Encounters panel. The first one that yields encounter rows wins.
    const sources = [
      R.officeAllyUrls(pid, "").progressNotes.replace(/^https:\/\/[^/]+/, ""),
      "/emr/PatientCharts/Patient_Encounters.aspx?PID=" + encodeURIComponent(pid) + "&From=SOAPNote",
    ];
    let readAny = false;
    for (const src of sources) {
      try {
        // redirect: "manual" — a timed-out session is REDIRECTED to Office Ally's login server on a
        // different address. Followed, that redirect is blocked by the browser and looks like a
        // network error ("couldn't read"), hiding the one thing that matters: you're logged out.
        // These pages never redirect for a logged-in user, so a redirect IS the logged-out signal.
        const resp = await fetch(src, { credentials: "same-origin", cache: "no-store", redirect: "manual" });
        if (resp.type === "opaqueredirect" || (resp.status >= 300 && resp.status < 400)) return { loggedOut: true };
        const html = await resp.text();
        if (R.looksLoggedOut(resp.url, html)) return { loggedOut: true };
        if (!resp.ok || !/<table/i.test(html)) continue;
        readAny = true;
        const list = R.parseEncounters(html);
        if (list.length) return list;
      } catch (_) { /* try the next source */ }
    }
    return readAny ? [] : null;
  }

  const LOGIN_MESSAGE = "Office Ally is not logged in (or the session timed out). Nothing was filled. Log in to Office Ally " +
    "in this tab, then in Cadence's \"Send to Office Ally\" window click the button for the step you were on, " +
    "and click the Cadence icon again.";

  // Every practice rule, in the order a failure matters. Each: { name, ok, block, reason }.
  // opts.applyDate: on a NEW encounter, set its Encounter Date to the visit date (done at Fill
  // time only — opening the panel never changes the page).
  async function runChecks(opts) {
    state.page = readPage();
    let p = state.page;
    const n = state.note;
    const out = [];
    const pc = R.checkPatient(p.pid, state.patient);
    out.push({ name: "Patient ID matches MRN", ok: pc.ok, block: !pc.ok, reason: pc.reason });
    const lc = R.checkLayout(n.form_id, p.layoutId, p.layoutName, state.layoutRules);
    out.push({ name: "Layout matches note type", ok: lc.ok, block: !lc.ok, reason: lc.reason });
    const day = R.visitDateOf(n);
    // A brand-new encounter carries Office Ally's default date (today). For a visit on another
    // day, set it to the visit date — it's a new record, not a re-dated one. An EXISTING
    // encounter's date is never changed; a mismatch there blocks (rule 3.2).
    if (p.isNew && p.encounterDate && day && R.mdy(p.encounterDate) !== day) {
      if (opts && opts.applyDate && setEncounterDate(day)) {
        state.page = readPage();
        p = state.page;
      } else {
        out.push({ name: "Encounter date will be set to " + day + " (new encounter)", ok: true, block: false, reason: "" });
        return loginFirst(out.concat(await sameDayCheck(p, day)));
      }
    }
    const dc = R.checkEncounterDate(day, p.encounterDate);
    out.push({ name: "Encounter date = visit date (" + (day || "no date") + ")", ok: dc.ok, block: !dc.ok, reason: dc.reason });
    return loginFirst(out.concat(await sameDayCheck(p, day)));
  }

  // A timed-out session explains every other failure, so it is reported first.
  function loginFirst(checks) {
    return checks.filter((c) => c.name === "Logged in to Office Ally").concat(checks.filter((c) => c.name !== "Logged in to Office Ally"));
  }

  // Office Ally's Encounter Date boxes (month / day / year) on a new encounter.
  function setEncounterDate(mmddyyyy) {
    const m = /^(\d{2})\/(\d{2})\/(\d{4})$/.exec(mmddyyyy);
    if (!m) return false;
    const parts = { Month: String(parseInt(m[1], 10)), Day: String(parseInt(m[2], 10)), Year: m[3] };
    let ok = true;
    Object.keys(parts).forEach((k) => {
      const el = document.getElementById(R.FIELD_PREFIX + "EncounterDate_" + k);
      if (!el) { ok = false; return; }
      setFieldValue(el, parts[k]);
    });
    return ok;
  }

  // One Office Ally encounter per Cadence note. Office Ally creates an encounter the moment an Add
  // Note page OPENS (its id is on the page before anything is saved), so every extra Add Note is an
  // extra, blank encounter in the chart. Cadence remembers which encounter each note went to.
  async function noteEncounterCheck(p) {
    if (!p.encounterId || !state.note) return [];
    const r = await bg("noteEncounterGet", { noteId: state.note.id });
    const rec = r && r.ok && r.data;
    if (!rec || !rec.eid || rec.eid === p.encounterId) return [];
    const earlier = rec.filled
      ? "This Cadence note was already filled into Office Ally encounter " + rec.eid + "."
      : "An Add Note page was already opened for this Cadence note: encounter " + rec.eid + " (probably still blank).";
    return [{ name: "One Office Ally encounter for this note", ok: false, block: false,
      reason: earlier + " This page is a different encounter, " + p.encounterId + ". Office Ally makes a new encounter every time " +
        "an Add Note page opens. Click Fill again to use THIS encounter, then remove the other one in Office Ally so the " +
        "chart has one encounter for the visit." }];
  }

  async function sameDayCheck(p, day) {
    const out = [];
    if (p.pid && p.encounterDate) {
      // Reading the encounter list doubles as the session check: an Office Ally session that has
      // timed out answers with its sign-in page, and a fill into a timed-out page cannot be saved.
      const encs = await loadEncounters(p.pid);
      if (encs && encs.loggedOut) {
        // On a note form the page itself proves the session (Office Ally just served it), so a
        // background read that bounced is a "couldn't check", not a block.
        if (discoverFields().length) return out;
        out.unshift({ name: "Logged in to Office Ally", ok: false, block: true, reason: LOGIN_MESSAGE });
        return out;
      }
      // Relaxed (practice, 2026-09-28): another encounter the same day is a NOTE for the clinician,
      // never a stop, and an unreadable list says nothing at all.
      const sc = R.checkSameDayEncounters(encs, day, p.encounterId);
      if (sc.block) out.push({ name: "Another encounter on " + day, ok: false, block: false, note: true, reason: sc.reason });
    }
    return out;
  }

  function renderChecks(checks) {
    const mount = $("#coChecks");
    if (!checks || !checks.length) { mount.innerHTML = ""; return; }
    mount.innerHTML = checks.map((c) => `<div class="co-check ${c.ok ? "ok" : c.block ? "bad" : "ask"}">
      <span>${c.ok ? "✓" : c.block ? "✕" : "?"} ${esc(c.name)}</span>
      ${c.ok || !c.reason ? "" : `<div class="co-box-s">${esc(c.reason)}</div>`}
    </div>`).join("");
  }

  // Every Office Ally SOAP text box on the page: its key, the label the practice gave it, and its
  // character limit (read from Office Ally's own CheckMaxLength handler, default 2,000).
  // The page and every same-origin frame inside it — a custom layout may render its note form in
  // an embedded frame rather than in the page itself.
  function allDocs() {
    const docs = [];
    const walk = (doc, depth) => {
      if (!doc || depth > 3) return;
      docs.push(doc);
      doc.querySelectorAll("iframe, frame").forEach((f) => {
        try { walk(f.contentDocument, depth + 1); } catch (_) { /* other-origin frame: not ours to read */ }
      });
    };
    walk(document, 0);
    return docs;
  }

  function discoverFields() {
    const out = [], seen = {};
    allDocs().forEach((doc) => doc.querySelectorAll('textarea[id*="ucSOAPNote_"]').forEach((el) => {
      const key = R.keyFromId(el.id);
      if (!key || seen[key] || el.disabled || el.readOnly) return;
      seen[key] = true;
      const m = /CheckMaxLength\(this,\s*(\d+)/.exec(el.getAttribute("onkeyup") || "");
      out.push({ key: key, label: fieldLabel(el, key), maxLen: m ? parseInt(m[1], 10) : 0, el: el });
    }));
    return out;
  }

  // What every SOAP box on the page holds right now, by key.
  function currentBoxValues() {
    const out = {};
    discoverFields().forEach((f) => { out[f.key] = f.el.value || ""; });
    return out;
  }

  // Does the Office Ally page already hold this note? Compared box by box against the routing plan.
  // null when none of the planned boxes has any text yet (a fresh encounter — nothing to compare).
  function savedCheck() {
    const plan = computePlan();
    const boxes = (plan && plan.boxes) || [];
    const cur = currentBoxValues();
    if (!boxes.length || !boxes.some((b) => (cur[b.key] || "").trim())) return null;
    const v = R.verifyBoxes(boxes, cur);
    if (v.ok) return { name: "Saved in Office Ally: all " + v.matched.length + " boxes match this Cadence note", ok: true, block: false, reason: "", verify: v };
    return { name: "Office Ally does not match this Cadence note in " + (v.differ.length + v.empty.length) + " of " + boxes.length + " boxes",
      ok: false, block: false, verify: v,
      reason: (v.empty.length ? "Empty in Office Ally: " + v.empty.join(", ") + ". " : "") +
        (v.differ.length ? "Different text in Office Ally: " + v.differ.join(", ") + ". " : "") +
        "Matching: " + (v.matched.join(", ") || "none") + "." };
  }

  // A support snapshot of the page's STRUCTURE — every text box, dropdown and editable area, with
  // its id, name and nearby label — and never its contents. Safe to paste to the developer:
  // no values, no patient details. Used when a layout's boxes aren't recognised.
  function fieldInventory() {
    const lines = ["Cadence field inventory — " + location.pathname + " (layout " + (state.page.layoutName || state.page.layoutId || "?") + ")",
      "frame | tag | id | name | label (nearby text) | visible | limit"];
    allDocs().forEach((doc, di) => {
      if (di > 0) lines.push("-- frame" + di + ": " + ((doc.location && doc.location.pathname) || "about:blank"));
      doc.querySelectorAll('textarea, input[type="text"], input:not([type]), select, [contenteditable="true"], body[contenteditable], iframe').forEach((el) => {
        const tag = el.tagName.toLowerCase() + (el.isContentEditable && el.tagName !== "TEXTAREA" ? "[contenteditable]" : "");
        const lab = (el.id && doc.querySelector('label[for="' + el.id + '"]')) || null;
        let labText = lab ? lab.textContent.trim() : "";
        if (!labText && el.tagName === "TEXTAREA") { try { labText = fieldLabel(el, el.id); } catch (_) { labText = ""; } }
        const lim = /CheckMaxLength\(this,\s*(\d+)/.exec(el.getAttribute("onkeyup") || "");
        const visible = !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length);
        lines.push(["frame" + di, tag, el.id || "-", el.getAttribute("name") || "-",
          String(labText).replace(/\s+/g, " ").slice(0, 60), visible ? "yes" : "no",
          lim ? lim[1] : (el.getAttribute("maxlength") || "-")].join(" | "));
      });
    });
    return lines.join("\n");
  }

  function fieldLabel(el, key) {
    const doc = el.ownerDocument || document;
    const hidden = doc.getElementById(el.id + "_Label");
    if (hidden && hidden.value && hidden.value.trim()) return hidden.value.trim();
    // A built-in box means what its key says (on the real page the Functional Status box's own
    // header just reads "Comments"), so the known name beats the nearest header text.
    if (R.DEFAULT_LABELS[key]) return R.DEFAULT_LABELS[key];
    // Otherwise the nearest header label above the box (Office Ally puts it in a table just before).
    let node = el;
    for (let depth = 0; node && depth < 5; depth++, node = node.parentElement) {
      for (let sib = node.previousElementSibling, n = 0; sib && n < 4; sib = sib.previousElementSibling, n++) {
        const lab = sib.matches(".soapTextAreaHeaderLabel") ? sib : sib.querySelector(".soapTextAreaHeaderLabel");
        if (lab) {
          const first = Array.prototype.find.call(lab.childNodes, (c) => c.nodeType === 3 && c.textContent.trim()) ;
          return (first ? first.textContent : lab.textContent).replace(/:\s*$/, "").trim();
        }
      }
    }
    return key;
  }

  // ---------- background messaging + storage ----------
  function bg(action, payload) {
    return new Promise((resolve) => {
      chrome.runtime.sendMessage(Object.assign({ type: "cadence", action: action }, payload || {}), (r) => {
        if (chrome.runtime.lastError) return resolve({ ok: false, error: chrome.runtime.lastError.message });
        resolve(r || { ok: false, error: "no response" });
      });
    });
  }
  function loadMappings() {
    return new Promise((res) => chrome.storage.local.get("mappings", (d) => res((d && d.mappings) || {})));
  }
  function persistMapping() {
    state.mappings[state.formKey] = state.mapping;
    return new Promise((res) => chrome.storage.local.set({ mappings: state.mappings }, () => res()));
  }

  // ---------- panel (shadow DOM) ----------
  const STYLE = `<style>
    :host { all: initial; }
    .co { position: fixed; top: 16px; right: 16px; width: 340px; max-height: 84vh; display: flex;
      flex-direction: column; background: #fff; color: #17211e; border: 1px solid #d7e0dc;
      border-radius: 12px; box-shadow: 0 10px 40px rgba(23,33,30,.28); z-index: 2147483647;
      font-family: "Segoe UI", system-ui, sans-serif; font-size: 13px; overflow: hidden; }
    .co-head { display: flex; align-items: center; gap: 8px; padding: 10px 12px; background: #15514e;
      color: #fff; cursor: move; user-select: none; }
    .co-title { font-weight: 700; font-size: 13px; flex: 1; }
    .co-title .dot { color: #e9b872; }
    .co-x { background: transparent; border: none; color: #cfe0dc; font-size: 18px; line-height: 1;
      cursor: pointer; padding: 0 4px; }
    .co-x:hover { color: #fff; }
    .co-body { padding: 12px; overflow: auto; }
    .co-note { font-size: 11px; color: #5d6f69; margin: 0 0 10px; }
    .co-row { display: flex; flex-direction: column; gap: 4px; margin-bottom: 10px; }
    .co-row label { font-size: 10.5px; font-weight: 700; letter-spacing: .05em; text-transform: uppercase; color: #5d6f69; }
    .co select { font: inherit; padding: 7px 8px; border: 1px solid #d7e0dc; border-radius: 8px; background: #fcfdfd; }
    .co-status { font-size: 12px; color: #1f3835; background: #f0f6f4; border: 1px solid #e0ece8;
      border-radius: 8px; padding: 8px 10px; margin-bottom: 10px; min-height: 18px; }
    .co-status.warn { color: #7a2a1e; background: #fdecea; border-color: #f0c8c1; }
    .co-src { display: grid; grid-template-columns: 1fr auto; gap: 4px 8px; align-items: center;
      padding: 8px 0; border-bottom: 1px solid #eef2f0; }
    .co-src:last-child { border-bottom: none; }
    .co-label { font-weight: 600; }
    .co-kind { font-size: 9.5px; font-weight: 700; letter-spacing: .04em; text-transform: uppercase;
      color: #15514e; background: #e7f0ee; padding: 1px 6px; border-radius: 999px; margin-left: 6px; }
    .co-kind.patient { color: #1a56b3; background: #e9f1fe; }
    .co-kind.soap { color: #8a5a12; background: #fbf1e3; }
    .co-map { grid-column: 1 / -1; font-size: 11px; }
    .co-sel { font-family: "Consolas", monospace; color: #15514e; background: #f0f6f4; padding: 1px 6px; border-radius: 5px; }
    .co-unmapped { color: #9aa8a3; font-style: italic; }
    .co-actions { display: flex; gap: 6px; }
    .co-btn { font: inherit; font-size: 12px; font-weight: 600; border: 1px solid #d7e0dc; background: #fff;
      color: #17211e; border-radius: 7px; padding: 5px 10px; cursor: pointer; }
    .co-btn:hover { border-color: #15514e; color: #15514e; }
    .co-btn.mini { padding: 4px 8px; font-size: 11px; }
    .co-btn.primary { background: #15514e; color: #fff; border-color: #15514e; }
    .co-btn.primary:hover { background: #0f413f; color: #fff; }
    .co-btn.danger:hover { border-color: #cf4631; color: #cf4631; }
    .co-fillbar { display: flex; gap: 8px; margin-top: 12px; }
    .co-fillbar .co-btn { flex: 1; text-align: center; }
    .co-hint { font-size: 11.5px; color: #8a5a12; background: #fbf1e3; border: 1px solid #eccfa3;
      border-radius: 8px; padding: 7px 9px; margin-top: 10px; }
    .co-hint:empty { display: none; }
    .co-empty { color: #9aa8a3; font-size: 12px; padding: 8px 0; }
    .co-page { font-size: 11.5px; color: #1f3835; margin: -4px 0 10px; }
    .co-h { font-size: 10.5px; font-weight: 700; letter-spacing: .05em; text-transform: uppercase;
      color: #5d6f69; margin: 14px 0 6px; }
    .co-plan { border: 1px solid #e0ece8; border-radius: 8px; padding: 4px 10px; background: #fcfdfd; }
    .co-plan:empty { display: none; }
    .co-box { padding: 6px 0; border-bottom: 1px solid #eef2f0; }
    .co-box:last-child { border-bottom: none; }
    .co-box-h { display: flex; justify-content: space-between; gap: 8px; font-weight: 600; }
    .co-box-n { font-weight: 400; color: #5d6f69; font-size: 11px; white-space: nowrap; }
    .co-box-s { font-size: 11px; color: #5d6f69; }
    .co-box.bad .co-box-h { color: #7a2a1e; }
    .co-check { font-size: 12px; font-weight: 600; padding: 4px 8px; border-radius: 6px; margin-bottom: 4px; }
    .co-check.ok { color: #15514e; background: #f0f6f4; }
    .co-check.bad { color: #7a2a1e; background: #fdecea; }
    .co-check.ask { color: #8a5a12; background: #fbf1e3; }
    .co-check .co-box-s { font-weight: 400; margin-top: 2px; color: inherit; }
    .co-warn { font-size: 11.5px; color: #7a2a1e; background: #fdecea; border: 1px solid #f0c8c1;
      border-radius: 8px; padding: 7px 9px; margin-top: 8px; }
  </style>`;

  const PANEL_HTML = `<div class="co" id="coPanel">
    <div class="co-head" id="coHead">
      <span class="co-title">Cadence<span class="dot">.</span> → Office Ally</span>
      <button class="co-x" id="coClose" title="Close">×</button>
    </div>
    <div class="co-body">
      <p class="co-note">Local only — reads Cadence on this machine, fills this page. No data leaves the device.</p>
      <div class="co-status" id="coStatus">…</div>
      <div class="co-page" id="coPage"></div>
      <div id="coChecks"></div>
      <div class="co-row"><label>Patient</label><select id="coPatient"></select></div>
      <div class="co-row"><label>Saved note</label><select id="coNote"></select></div>
      <div class="co-h">Automatic fill — where each section will go</div>
      <div class="co-plan" id="coPlan"></div>
      <div class="co-fillbar"><button class="co-btn primary" id="coFill">Fill &amp; save draft</button></div>
      <div class="co-hint" id="coHint"></div>
      <div class="co-h">Manual overrides (optional)</div>
      <div id="coSources"></div>
    </div>
  </div>`;

  const host = document.createElement("div");
  host.id = "cadence-oa-host";
  const shadow = host.attachShadow({ mode: "open" });
  shadow.innerHTML = STYLE + PANEL_HTML;
  document.documentElement.appendChild(host);
  const $ = (sel) => shadow.querySelector(sel);

  let visible = true;
  function toggle() { visible = !visible; host.style.display = visible ? "block" : "none"; }
  function destroy() { cleanupPick(); if (highlight) highlight.remove(); host.remove(); window.__cadenceOA = null; }
  window.__cadenceOA = { toggle: toggle, close: destroy };

  function setStatus(msg, warn) { const s = $("#coStatus"); s.textContent = msg; s.classList.toggle("warn", !!warn); }
  function setHint(msg) { $("#coHint").textContent = msg || ""; }
  function labelOf(sourceId) { const s = state.sources.find((x) => x.id === sourceId); return s ? s.label : sourceId; }

  // ---------- drag ----------
  (function makeDraggable() {
    const head = $("#coHead"), panel = $("#coPanel");
    let sx, sy, ox, oy, dragging = false;
    head.addEventListener("mousedown", (e) => {
      if (e.target.id === "coClose") return;
      dragging = true; const r = panel.getBoundingClientRect();
      ox = r.left; oy = r.top; sx = e.clientX; sy = e.clientY;
      panel.style.right = "auto"; panel.style.left = ox + "px"; panel.style.top = oy + "px";
      e.preventDefault();
    });
    document.addEventListener("mousemove", (e) => {
      if (!dragging) return;
      panel.style.left = (ox + e.clientX - sx) + "px";
      panel.style.top = Math.max(0, oy + e.clientY - sy) + "px";
    });
    document.addEventListener("mouseup", () => { dragging = false; });
  })();

  $("#coClose").addEventListener("click", destroy);

  // ---------- data flow ----------
  async function init() {
    state.mappings = await loadMappings();
    state.mapping = state.mappings[state.formKey] || M.emptyMapping(document.title || "Office Ally form");
    setStatus("Connecting to Cadence…");
    const r = await bg("patients");
    if (!r.ok) { setStatus("Couldn't reach Cadence — is the app running? (" + r.error + ")", true); return; }
    state.patients = r.data || [];
    // Which Office Ally layout each note type goes into, as set in Cadence → Manage Office.
    const os = await bg("officeSettings");
    state.layoutRules = os.ok && os.data ? R.layoutRulesFrom(os.data.layouts) : null;
    const sel = $("#coPatient");
    sel.innerHTML = '<option value="">— choose —</option>' +
      state.patients.map((p) => `<option value="${p.id}">${esc(p.name)}</option>`).join("");
    sel.addEventListener("change", onPatientChange);
    $("#coNote").addEventListener("change", onNoteChange);
    $("#coFill").addEventListener("click", fill);
    renderPage();

    // Where is the panel open? Only Office Ally (logged in) or the local practice page is filled.
    const kind = R.pageKind(location.hostname, location.pathname, !!document.querySelector('input[type="password"]'));
    if (kind === "login") { setStatus(LOGIN_MESSAGE, true); $("#coFill").disabled = true; return; }
    // Opened on Cadence itself (the icon works on whichever tab is in front) — easy to do by mistake.
    if (location.port === "8420" && !discoverFields().length) {
      setStatus("This is the Cadence tab. Switch to the Office Ally tab with the patient's note open, then click the Cadence icon there.", true);
      $("#coFill").disabled = true;
      return;
    }
    // A page can still be on screen after the session behind it has expired. Ask Office Ally now,
    // before anything is selected, rather than discovering it at Fill.
    // A note form on screen was just served by Office Ally, so the session is live — skip the probe.
    if (kind === "officeally" && state.page.pid && !discoverFields().length) {
      setStatus("Checking you're logged in to Office Ally…");
      const probe = await loadEncounters(state.page.pid);
      if (probe && probe.loggedOut) { setStatus(LOGIN_MESSAGE, true); $("#coFill").disabled = true; return; }
    }
    if (kind === "other") {
      setStatus("This page isn't Office Ally. Open Office Ally, log in, open the patient's note, then click the Cadence icon.", true);
      $("#coFill").disabled = true;
      return;
    }

    const byMrn = (p) => digitsOnly(p.mrn) && digitsOnly(p.mrn) === digitsOnly(state.page.pid);
    // Just saved a draft in this tab? Then this is the reloaded page: reopen on the same note and
    // check the SAVED boxes against it — proof the text is in Office Ally, not just typed in.
    const vr = await bg("verifyPending");
    const pending = vr.ok && vr.data;
    if (pending) {
      const vp = state.patients.find((p) => p.id === pending.patientId);
      if (vp && (!state.page.pid || byMrn(vp))) {
        state.verifyAfterSave = true;
        sel.value = vp.id;
        await onPatientChange(pending.noteId);
        return;
      }
    }

    // The note the clinician sent with Cadence's "Send to Office Ally" button comes first — as
    // long as it belongs to this chart. A handoff for a different patient is never applied.
    const hr = await bg("handoff");
    const handoff = hr.ok && hr.data;
    if (handoff) {
      const hp = state.patients.find((p) => p.id === handoff.patientId);
      if (hp && (!state.page.pid || byMrn(hp))) {
        sel.value = hp.id;
        await onPatientChange(handoff.noteId);
        return;
      }
      if (hp && state.page.pid) {
        // The note sent from Cadence is for someone else. Say so — never fill it here.
        const wrong = R.checkPatient(state.page.pid, hp);
        state.blockedReason = wrong.reason.replace(/^Wrong chart:\s*this/, "Wrong chart: the note sent from Cadence is for " + hp.name + ". This");
        setStatus(state.blockedReason, true);
        return;
      }
    }
    // Otherwise, on an Office Ally chart, pick the Cadence patient linked to this chart's Patient ID.
    const linked = state.page.pid && state.patients.find(byMrn);
    if (linked) { sel.value = linked.id; await onPatientChange(); return; }
    setStatus(state.patients.length ? "Pick a patient and a saved note." : "No patients in Cadence yet.");
  }

  function renderPage() {
    const p = state.page;
    $("#coPage").textContent = p.pid
      ? "Office Ally Patient ID " + p.pid + (p.layoutName ? " · layout \"" + p.layoutName + "\"" : "") +
        (p.encounterId ? " · encounter " + p.encounterId : "") +
        (p.encounterDate ? " dated " + R.mdy(p.encounterDate) : "")
      : "Not an Office Ally chart page — the patient-ID check is skipped.";
  }

  async function onPatientChange(preselectNoteId) {
    if (typeof preselectNoteId !== "string") preselectNoteId = ""; // called as an event listener too
    const pid = $("#coPatient").value;
    const noteSel = $("#coNote");
    state.note = null; state.sources = []; state.plan = null; renderSources();
    if (!pid) { noteSel.innerHTML = ""; return; }
    setStatus("Loading notes…");
    const r = await bg("notes", { patientId: pid });
    if (!r.ok) { setStatus("Couldn't load notes: " + r.error, true); return; }
    const notes = r.data || [];
    noteSel.innerHTML = '<option value="">— choose —</option>' +
      notes.map((n) => `<option value="${n.id}">${esc(n.form_name)} · ${esc(fmtDate(n.created_at))}</option>`).join("");
    // Choose the note for them: the one sent from Cadence, or else the only note dated the same
    // day as this Office Ally encounter. Anything ambiguous is left for the clinician to pick.
    let pick = notes.find((n) => n.id === preselectNoteId);
    if (!pick && state.page.encounterDate) {
      const day = R.mdy(state.page.encounterDate);
      const sameDay = notes.filter((n) => R.visitDateOf(n) === day);
      if (sameDay.length === 1) pick = sameDay[0];
    }
    if (pick) { noteSel.value = pick.id; await onNoteChange(); return; }
    setStatus(notes.length ? "Pick a saved note." : "This patient has no saved notes yet.");
  }

  async function onNoteChange() {
    const pid = $("#coPatient").value, nid = $("#coNote").value;
    if (!pid || !nid) return;
    setStatus("Loading note…");
    const [nr, pr] = await Promise.all([bg("note", { patientId: pid, noteId: nid }), bg("patient", { patientId: pid })]);
    if (!nr.ok) { setStatus("Couldn't load note: " + nr.error, true); return; }
    state.note = nr.data;
    state.patient = pr.ok ? pr.data : null;
    state.sources = M.noteSources(state.note, state.patient);
    state.gapsAcknowledged = false;
    state.dupAcknowledged = false;
    renderSources();
    setStatus("Checking the Office Ally page…");
    const checks = await runChecks();
    // An Add Note page has ALREADY created its encounter. Remember it for this note (unless the note
    // has one), so a second "Create" for the same note opens nothing new.
    const pg = state.page;
    if (pg.isNew && pg.encounterId) {
      const known = await bg("noteEncounterGet", { noteId: state.note.id });
      if (!(known.ok && known.data)) await bg("noteEncounterSet", { noteId: state.note.id, eid: pg.encounterId, pid: pg.pid, filled: false });
    }
    // Does the page already hold this note (e.g. just saved)? Compare box by box.
    const saved = savedCheck();
    renderChecks(saved ? checks.concat([saved]) : checks);
    const blocked = checks.find((c) => c.block);
    const justSaved = state.verifyAfterSave;
    state.verifyAfterSave = false;
    if (blocked) setStatus(blocked.reason, true);
    else if (justSaved && saved && saved.ok) setStatus("Saved and checked: Office Ally now holds this note — all " + saved.verify.matched.length +
      " boxes match Cadence. Review every box, then sign in Office Ally.");
    else if (justSaved) setStatus("Saved-note check FAILED: " + (saved ? saved.reason : "the Office Ally boxes are empty after saving.") +
      " Office Ally may not have saved the draft — look for an Office Ally message on the page, then click Fill again.", true);
    else if (saved && saved.ok) setStatus("This Office Ally note already holds this Cadence note (all boxes match). Nothing to fill — review and sign.");
    else setStatus('Loaded "' + (state.note.form_name || "note") + '". Check where each section will go below, then Fill.');
  }

  // ---------- automatic routing ----------
  // Sections the clinician mapped by hand, and the boxes those mappings occupy, are left out.
  function manualExclusions() {
    const rules = (state.mapping && state.mapping.rules) || [];
    const skip = [], reserved = [];
    const soapMapped = rules.filter((r) => r.sourceId.indexOf("soap:") === 0).map((r) => r.sourceId.slice(5));
    rules.forEach((r) => {
      if (r.sourceId.indexOf("section:") === 0) skip.push(r.sourceId.slice(8));
      const idm = /^#(.+)$/.exec(r.selector || "");
      const key = idm && R.keyFromId(idm[1]);
      if (key) reserved.push(key);
    });
    ((state.note && state.note.sections) || []).forEach((s) => {
      if (soapMapped.indexOf(M.soapBlockFor(s.heading)) !== -1) skip.push(M.normalizeHeading(s.heading));
    });
    return { skipHeadings: skip, reservedKeys: reserved };
  }

  function computePlan() {
    if (!state.note) return null;
    const sections = (state.note.sections || []).map((s) => ({ heading: s.heading, text: M.markerToText(s.body).trim() }));
    const fields = discoverFields();
    const plan = R.planRouting(sections, fields.map((f) => ({ key: f.key, label: f.label, maxLen: f.maxLen })), manualExclusions());
    plan.fieldCount = fields.length;
    return plan;
  }

  function renderPlan() {
    const mount = $("#coPlan");
    state.plan = computePlan();
    const plan = state.plan;
    if (!plan) { mount.innerHTML = ""; return; }
    // On a note form (layout / encounter date present) but no recognisable boxes: this layout is
    // built differently. Say so plainly instead of listing every section as "copy by hand", and
    // offer the structure snapshot so it can be fixed.
    if (!plan.fieldCount && (state.page.layoutId || state.page.encounterDate)) {
      mount.innerHTML = '<div class="co-warn">The Office Ally layout "' + esc(state.page.layoutName || state.page.layoutId) +
        '" isn\'t set up in Cadence yet, so nothing was filled. For now, use Cadence\'s <b>Copy</b> buttons under the note. ' +
        'To get it set up, click <b>Copy page structure</b> and send it to whoever looks after Cadence — it lists box names only, never what is typed in them.</div>' +
        '<div class="co-fillbar"><button class="co-btn" id="coInventory">Copy page structure</button></div>';
      $("#coInventory").addEventListener("click", async () => {
        try { await navigator.clipboard.writeText(fieldInventory()); setStatus("Page structure copied. Paste it into a message to your Cadence support person."); }
        catch (_) { setStatus("Couldn't copy automatically. Please tell your Cadence support person the layout name: " + (state.page.layoutName || state.page.layoutId), true); }
      });
      return;
    }
    if (!plan.fieldCount) {
      // Not on a note form yet: offer to open ONE Add Note page on the layout this note type needs.
      // Office Ally creates the encounter as soon as that page opens, so this refuses to open a
      // second one for the same note, and for a day that already has an encounter.
      const rule = layoutRules()[state.note.form_id];
      const day = R.visitDateOf(state.note);
      const urls = R.officeAllyUrls(state.page.pid, state.note.form_id, state.layoutRules);
      const here = R.parseEncounters(document.documentElement.outerHTML).filter((e) => e.date === day);
      const onList = /PatientChart_ProgressNotes\.aspx/i.test(location.pathname);
      let h = '<div class="co-empty">This note is dated <b>' + esc(day) + '</b>.';
      if (onList && here.length) {
        h += ' <b style="color:#7a2a1e">Office Ally already has ' + (here.length > 1 ? "encounters" : "an encounter") + ' dated ' + esc(day) + ': ' +
          here.map((e) => esc(e.eid)).join(", ") + '</b>. Open ' + (here.length > 1 ? "one of them" : "it") + ' from this list and click the Cadence icon there — only one encounter per day.';
      } else if (onList) {
        h += ' No encounter dated ' + esc(day) + ' on this list.';
      }
      h += '</div>';
      if (urls.addNote && state.page.pid) {
        h += '<div class="co-fillbar"><button class="co-btn" id="coAddNote">Create the ' + esc(rule.label) + ' note</button></div>';
      } else {
        h += '<div class="co-empty">Open the note form for ' + esc(day) + ', then click the Cadence icon again.</div>';
      }
      mount.innerHTML = h;
      const add = $("#coAddNote");
      if (add) add.addEventListener("click", async () => {
        if (onList && here.length) { setStatus("Office Ally already has an encounter dated " + day + " — open it instead of creating another. Only one encounter per day.", true); return; }
        const known = await bg("noteEncounterGet", { noteId: state.note.id });
        const rec = known.ok && known.data;
        if (rec && rec.eid && !state.createAgain) {
          state.createAgain = true;
          setStatus("This note already has Office Ally encounter " + rec.eid + (rec.filled ? " (filled from Cadence)" : " (opened, probably blank)") +
            ". Open that encounter from the Progress Notes list instead — every Add Note makes another encounter. " +
            "If you removed it in Office Ally, click Create again.", true);
          return;
        }
        state.createAgain = false;
        window.location.href = urls.addNote;
      });
      return;
    }
    const warn = layoutRules()[state.note.form_id] ? "" : R.layoutWarning(state.note.form_id, state.page.layoutName);
    mount.innerHTML =
      plan.boxes.map((b) => `<div class="co-box">
        <div class="co-box-h"><span>${esc(b.label)}</span><span class="co-box-n">${b.length.toLocaleString()} / ${b.maxLen.toLocaleString()}</span></div>
        <div class="co-box-s">${b.sections.map(esc).join(" · ")}</div>
      </div>`).join("") +
      plan.unplaced.map((u) => `<div class="co-box bad">
        <div class="co-box-h"><span>Not placed: ${esc(u.heading)}</span></div>
        <div class="co-box-s">${esc(u.reason)} — copy it in by hand.</div>
      </div>`).join("") +
      (warn ? `<div class="co-warn">${esc(warn)}</div>` : "");
  }

  function renderSources() {
    const mount = $("#coSources");
    renderPlan(); // a manual mapping changes what is left to route automatically
    if (!state.sources.length) { mount.innerHTML = '<div class="co-empty">Choose a note to see its fields.</div>'; return; }
    mount.innerHTML = state.sources.map((s) => {
      const rule = M.ruleFor(state.mapping, s.id);
      const mapHtml = rule
        ? `<span class="co-sel" title="${esc(rule.selector)}">${esc(truncate(rule.selector, 40))}</span>`
        : `<span class="co-unmapped">not mapped</span>`;
      return `<div class="co-src">
        <div><span class="co-label">${esc(s.label)}</span><span class="co-kind ${s.kind}">${s.kind}</span></div>
        <div class="co-actions">
          <button class="co-btn mini" data-pick="${esc(s.id)}">${rule ? "Remap" : "Map"}</button>
          ${rule ? `<button class="co-btn mini danger" data-unmap="${esc(s.id)}" title="Remove">✕</button>` : ""}
        </div>
        <div class="co-map">${mapHtml}</div>
      </div>`;
    }).join("");
    Array.prototype.forEach.call(mount.querySelectorAll("[data-pick]"), (b) =>
      b.addEventListener("click", () => startPick(b.getAttribute("data-pick"))));
    Array.prototype.forEach.call(mount.querySelectorAll("[data-unmap]"), (b) =>
      b.addEventListener("click", async () => {
        state.mapping = M.removeRule(state.mapping, b.getAttribute("data-unmap"));
        await persistMapping(); renderSources();
      }));
  }

  // ---------- click-to-pick ----------
  let highlight = null;
  function ensureHighlight() {
    if (highlight) return highlight;
    highlight = document.createElement("div");
    Object.assign(highlight.style, {
      position: "fixed", zIndex: 2147483646, pointerEvents: "none", display: "none",
      border: "2px solid #15514e", background: "rgba(21,81,78,.12)", borderRadius: "3px",
    });
    document.documentElement.appendChild(highlight);
    return highlight;
  }
  const inPanel = (el) => el === host || (el && host.contains && host.contains(el)) || (el && el.getRootNode && el.getRootNode() === shadow);
  function onMove(e) {
    const el = e.target;
    const h = ensureHighlight();
    if (!el || inPanel(el)) { h.style.display = "none"; return; }
    const r = el.getBoundingClientRect();
    Object.assign(h.style, { display: "block", left: r.left + "px", top: r.top + "px", width: r.width + "px", height: r.height + "px" });
  }
  function onPickClick(e) {
    if (inPanel(e.target)) return; // let panel buttons work
    e.preventDefault(); e.stopPropagation(); if (e.stopImmediatePropagation) e.stopImmediatePropagation();
    const el = e.target;
    const selector = M.buildSelector(computeDescriptor(el));
    const sourceId = state.picking;
    state.mapping = M.upsertRule(state.mapping || M.emptyMapping(document.title), sourceId, selector, fieldType(el));
    persistMapping().then(() => {
      cleanupPick(); state.picking = null; renderSources();
      setStatus('Mapped "' + labelOf(sourceId) + '" → ' + selector);
    });
  }
  function onPickKey(e) { if (e.key === "Escape") { e.preventDefault(); cleanupPick(); state.picking = null; setStatus("Mapping cancelled."); } }
  function startPick(sourceId) {
    cleanupPick(); state.picking = sourceId;
    document.addEventListener("mousemove", onMove, true);
    document.addEventListener("click", onPickClick, true);
    document.addEventListener("keydown", onPickKey, true);
    setHint('Click the Office Ally field for "' + labelOf(sourceId) + '" … (Esc to cancel)');
  }
  function cleanupPick() {
    document.removeEventListener("mousemove", onMove, true);
    document.removeEventListener("click", onPickClick, true);
    document.removeEventListener("keydown", onPickKey, true);
    if (highlight) highlight.style.display = "none";
    setHint("");
  }

  // ---------- fill ----------
  // Fills the text boxes, reads each one back, and — only when everything landed — clicks Office
  // Ally's Apply to save a DRAFT. It never clicks Update, and never anything that signs: the
  // clinician reviews every box in Office Ally and signs it themselves.
  async function fill() {
    if (!state.note) { setStatus(state.blockedReason || "Choose a patient and a saved note first.", !!state.blockedReason); return; }

    // 1. The practice rules, re-checked at click time (the clinician may have changed the date or
    //    layout since the panel opened): right patient, right layout for the note type, encounter
    //    date = note date, one encounter per day. Any failure fills NOTHING — never overridden.
    // 0. No recognisable boxes at all → stop before touching anything on the page.
    if (!discoverFields().length) {
      setStatus("Nothing was filled: this Office Ally layout isn't set up in Cadence yet. See below.", true);
      renderPlan();
      return;
    }

    setStatus("Checking the Office Ally page…");
    const checks = await runChecks({ applyDate: true });
    renderChecks(checks);
    const blocked = checks.find((c) => c.block);
    if (blocked) { setStatus(blocked.reason, true); return; }
    // 2. Unresolved gaps would go into the chart as "[! …]". Make that a deliberate second click.
    // Relaxed (practice, 2026-09-28): no extra click. Flagged items go in visibly as "[! …]" and the
    // status line counts them, so the clinician sees them while reviewing before signing.
    const gaps = R.countGaps(state.note.sections);

    let filled = 0, skipped = 0, notFound = 0, occupied = [];
    const touched = [];

    // 3. Manual overrides first (the clinician's explicit choice).
    ((state.mapping && state.mapping.rules) || []).forEach((rule) => {
      const text = M.resolveSource(rule.sourceId, state.note, state.patient);
      if (text == null) { skipped++; return; }
      let el = null;
      try { el = document.querySelector(rule.selector); } catch (_) { el = null; }
      if (!el) { notFound++; return; }
      try { setFieldValue(el, text); filled++; touched.push(el); } catch (_) { notFound++; }
    });

    // 4. Automatic routing for everything else. A box that already holds different text is left
    //    alone — overwriting what the clinician typed in Office Ally is never a silent side effect.
    const plan = computePlan();
    const byKey = {};
    const filledBoxes = [];
    discoverFields().forEach((f) => { byKey[f.key] = f; });
    ((plan && plan.boxes) || []).forEach((b) => {
      const f = byKey[b.key];
      if (!f) { notFound++; return; }
      const current = (f.el.value || "").trim();
      if (current && !R.sameText(current, b.text)) { occupied.push(b.label); return; }
      setFieldValue(f.el, b.text); filled++; touched.push(f.el); filledBoxes.push(b);
    });

    revealFilled(touched);
    // 5. Read every filled box back from the page. What is saved is what the boxes hold, so a box
    //    Office Ally emptied, cut or changed is caught here, before anything is saved.
    const readBack = R.verifyBoxes(filledBoxes, currentBoxValues());
    const notKept = readBack.differ.concat(readBack.empty);
    const unplaced = (plan && plan.unplaced) || [];
    const problems = unplaced.length + occupied.length + notFound + notKept.length;
    const summary = "Filled " + filled + " Office Ally box" + (filled === 1 ? "" : "es") +
      (filledBoxes.length && !notKept.length ? " and read each one back: all match the Cadence note." : ".") +
      (notKept.length ? " Office Ally did NOT keep the text in: " + notKept.join(", ") + "." : "") +
      (occupied.length ? " Not overwritten (already has text — clear it first): " + occupied.join(", ") + "." : "") +
      (unplaced.length ? " Copy in by hand: " + unplaced.map((u) => u.heading).join(", ") + "." : "") +
      (notFound ? " " + notFound + " field(s) not found on page." : "") +
      (skipped ? " " + skipped + " manual mapping(s) not in this note." : "") +
      (gaps ? " " + gaps + " flagged item" + (gaps > 1 ? "s are" : " is") + " marked [! …] in the boxes — check " + (gaps > 1 ? "them" : "it") + " before signing." : "");

    // 6. Remember that this note now lives in this encounter, so a second "Create" for the same
    //    note does not open another Add Note page (each one makes a new, blank encounter).
    if (filled && state.page.encounterId) {
      await bg("noteEncounterSet", { noteId: state.note.id, eid: state.page.encounterId, pid: state.page.pid });
    }

    // 7. Save as a DRAFT (the practice's request, 2026-09-28) — only when the fill was clean and
    //    every box read back correctly. Office Ally's own Apply button saves and keeps the note
    //    open; it never signs. With anything left to fix, nothing is saved and the clinician decides.
    const apply = filled && !problems ? findApplyButton() : null;
    if (apply) {
      state.savedDraft = true;
      // After the reload, the panel reopens on this encounter and checks the SAVED boxes against the
      // note — the proof that the text is in Office Ally, not just typed into the page.
      await bg("verifyAfterSave", { patientId: $("#coPatient").value, noteId: state.note.id, eid: state.page.encounterId });
      setStatus(summary + " Saving as a draft in Office Ally… The page will reload, then Cadence checks the saved note box by box" +
        " (if this panel doesn't come back by itself, click the Cadence icon). Then review every box and sign.");
      setTimeout(() => apply.click(), 1200); // long enough to read what happened before the reload
    } else {
      setStatus(summary + (filled && !problems
        ? " Click Apply in Office Ally to save it as a draft, then review every box and sign."
        : " Not saved — fix the items above, then save and sign in Office Ally."), problems > 0 || !filled);
    }
  }

  // Office Ally's "Apply" button (saves the note and stays on it). Never Update-and-close, never
  // anything that signs. Matched by its label, since layouts render it with different ids.
  function findApplyButton() {
    for (const doc of allDocs()) {
      const b = Array.prototype.find.call(doc.querySelectorAll('input[type="button"], input[type="submit"], button'),
        (el) => /^\s*apply\s*$/i.test(el.value || el.textContent || "") && !el.disabled);
      if (b) return b;
    }
    return null;
  }

  // Office Ally keeps some boxes (e.g. Physical Examination) in collapsed sections. A filled box
  // the clinician cannot see is a box they will not review, so open anything that hides one.
  function revealFilled(elements) {
    elements.forEach((el) => {
      for (let n = el.parentElement; n && n !== document.body; n = n.parentElement) {
        if (n.style && n.style.display === "none") n.style.display = "";
      }
    });
  }

  function setFieldValue(el, text) {
    const tag = el.tagName.toLowerCase();
    if (el.isContentEditable) {
      el.focus(); el.textContent = text;
      el.dispatchEvent(new InputEvent("input", { bubbles: true })); el.blur(); return;
    }
    if (tag === "select") {
      let matched = false;
      Array.prototype.forEach.call(el.options, (o) => {
        if (!matched && (o.value === text || o.textContent.trim() === String(text).trim())) { el.value = o.value; matched = true; }
      });
      el.dispatchEvent(new Event("change", { bubbles: true })); return;
    }
    if (tag === "input" || tag === "textarea") {
      const win = (el.ownerDocument && el.ownerDocument.defaultView) || window; // box may be in a frame
      const proto = tag === "textarea" ? win.HTMLTextAreaElement.prototype : win.HTMLInputElement.prototype;
      const setter = Object.getOwnPropertyDescriptor(proto, "value").set; // native setter so React registers it
      setter.call(el, text);
      el.dispatchEvent(new Event("input", { bubbles: true }));
      el.dispatchEvent(new Event("change", { bubbles: true })); // Office Ally marks the note unsaved
      // Office Ally resizes the box and updates its "chars left" counter on keyup. Its keyup also
      // truncates at the limit, which is why routing never produces a box over the limit.
      if (tag === "textarea") el.dispatchEvent(new KeyboardEvent("keyup", { bubbles: true }));
      return;
    }
    el.textContent = text;
  }

  // ---------- element → descriptor ----------
  function nthOfType(el) { let i = 1, s = el; while ((s = s.previousElementSibling)) { if (s.tagName === el.tagName) i++; } return i; }
  function computeDescriptor(el) {
    const path = []; let node = el;
    while (node && node.nodeType === 1 && node.tagName !== "BODY" && node.tagName !== "HTML") {
      path.unshift({ tag: node.tagName.toLowerCase(), index: nthOfType(node) });
      node = node.parentElement;
      if (path.length > 10) break;
    }
    return { id: el.id || "", name: el.getAttribute && el.getAttribute("name") || "", tag: el.tagName.toLowerCase(), path: path };
  }
  function fieldType(el) {
    if (el.isContentEditable) return "contenteditable";
    const t = el.tagName.toLowerCase();
    return t === "textarea" || t === "select" ? t : "input";
  }

  // ---------- small utils ----------
  function esc(s) { return String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;"); }
  function truncate(s, n) { s = String(s || ""); return s.length > n ? s.slice(0, n - 1) + "…" : s; }
  function layoutRules() { return state.layoutRules || {}; }
  function digitsOnly(s) { return String(s || "").replace(/\D/g, ""); }
  function fmtDate(d) { const x = d ? new Date(d) : null; return x && !isNaN(x) ? x.toLocaleDateString() : ""; }

  init();
})();
