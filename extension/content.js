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
  if (!M) { console.error("Cadence: mapping lib not loaded"); return; }

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
  };

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
  </style>`;

  const PANEL_HTML = `<div class="co" id="coPanel">
    <div class="co-head" id="coHead">
      <span class="co-title">Cadence<span class="dot">.</span> → Office Ally</span>
      <button class="co-x" id="coClose" title="Close">×</button>
    </div>
    <div class="co-body">
      <p class="co-note">Local only — reads Cadence on this machine, fills this page. No data leaves the device.</p>
      <div class="co-status" id="coStatus">…</div>
      <div class="co-row"><label>Patient</label><select id="coPatient"></select></div>
      <div class="co-row"><label>Saved note</label><select id="coNote"></select></div>
      <div id="coSources"></div>
      <div class="co-fillbar"><button class="co-btn primary" id="coFill">Fill Office Ally</button></div>
      <div class="co-hint" id="coHint"></div>
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
    const sel = $("#coPatient");
    sel.innerHTML = '<option value="">— choose —</option>' +
      state.patients.map((p) => `<option value="${p.id}">${esc(p.name)}</option>`).join("");
    sel.addEventListener("change", onPatientChange);
    $("#coNote").addEventListener("change", onNoteChange);
    $("#coFill").addEventListener("click", fill);
    setStatus(state.patients.length ? "Pick a patient and a saved note." : "No patients in Cadence yet.");
  }

  async function onPatientChange() {
    const pid = $("#coPatient").value;
    const noteSel = $("#coNote");
    state.note = null; state.sources = []; renderSources();
    if (!pid) { noteSel.innerHTML = ""; return; }
    setStatus("Loading notes…");
    const r = await bg("notes", { patientId: pid });
    if (!r.ok) { setStatus("Couldn't load notes: " + r.error, true); return; }
    const notes = r.data || [];
    noteSel.innerHTML = '<option value="">— choose —</option>' +
      notes.map((n) => `<option value="${n.id}">${esc(n.form_name)} · ${esc(fmtDate(n.created_at))}</option>`).join("");
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
    renderSources();
    setStatus('Loaded "' + (state.note.form_name || "note") + '". Map each field once, then Fill.');
  }

  function renderSources() {
    const mount = $("#coSources");
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
  function fill() {
    if (!state.note) { setStatus("Load a note first."); return; }
    const rules = (state.mapping && state.mapping.rules) || [];
    if (!rules.length) { setStatus("Nothing mapped yet — click Map on a field, then click it on the page."); return; }
    let filled = 0, skipped = 0, notFound = 0;
    rules.forEach((rule) => {
      const text = M.resolveSource(rule.sourceId, state.note, state.patient);
      if (text == null) { skipped++; return; }
      let el = null;
      try { el = document.querySelector(rule.selector); } catch (_) { el = null; }
      if (!el) { notFound++; return; }
      try { setFieldValue(el, text); filled++; } catch (_) { notFound++; }
    });
    setStatus("Filled " + filled +
      (skipped ? " · " + skipped + " not in this note" : "") +
      (notFound ? " · " + notFound + " field(s) not found on page" : "") + ".", notFound > 0);
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
      const proto = tag === "textarea" ? window.HTMLTextAreaElement.prototype : window.HTMLInputElement.prototype;
      const setter = Object.getOwnPropertyDescriptor(proto, "value").set; // native setter so React registers it
      setter.call(el, text);
      el.dispatchEvent(new Event("input", { bubbles: true }));
      el.dispatchEvent(new Event("change", { bubbles: true }));
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
  function fmtDate(d) { const x = d ? new Date(d) : null; return x && !isNaN(x) ? x.toLocaleDateString() : ""; }

  init();
})();
