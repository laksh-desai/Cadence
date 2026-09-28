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
    plan: null,
    gapsAcknowledged: false,
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
    return { pid: pid, layoutName: opt ? opt.textContent.trim() : "", layoutId: opt ? opt.value : "" };
  }

  // Every Office Ally SOAP text box on the page: its key, the label the practice gave it, and its
  // character limit (read from Office Ally's own CheckMaxLength handler, default 2,000).
  function discoverFields() {
    const out = [];
    document.querySelectorAll('textarea[id^="' + R.FIELD_PREFIX + '"]').forEach((el) => {
      const key = R.keyFromId(el.id);
      if (!key || el.disabled || el.readOnly) return;
      const m = /CheckMaxLength\(this,\s*(\d+)/.exec(el.getAttribute("onkeyup") || "");
      out.push({ key: key, label: fieldLabel(el, key), maxLen: m ? parseInt(m[1], 10) : 0, el: el });
    });
    return out;
  }
  function fieldLabel(el, key) {
    const hidden = document.getElementById(R.FIELD_PREFIX + key + "_Label");
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
      <div class="co-row"><label>Patient</label><select id="coPatient"></select></div>
      <div class="co-row"><label>Saved note</label><select id="coNote"></select></div>
      <div class="co-h">Automatic fill — where each section will go</div>
      <div class="co-plan" id="coPlan"></div>
      <div class="co-fillbar"><button class="co-btn primary" id="coFill">Fill Office Ally</button></div>
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
    const sel = $("#coPatient");
    sel.innerHTML = '<option value="">— choose —</option>' +
      state.patients.map((p) => `<option value="${p.id}">${esc(p.name)}</option>`).join("");
    sel.addEventListener("change", onPatientChange);
    $("#coNote").addEventListener("change", onNoteChange);
    $("#coFill").addEventListener("click", fill);
    renderPage();
    // On an Office Ally chart, pick the Cadence patient linked to this chart's Patient ID for them.
    const linked = state.page.pid && state.patients.find((p) => digitsOnly(p.mrn) && digitsOnly(p.mrn) === digitsOnly(state.page.pid));
    if (linked) { sel.value = linked.id; await onPatientChange(); return; }
    setStatus(state.patients.length ? "Pick a patient and a saved note." : "No patients in Cadence yet.");
  }

  function renderPage() {
    const p = state.page;
    $("#coPage").textContent = p.pid
      ? "Office Ally Patient ID " + p.pid + (p.layoutName ? " · layout \"" + p.layoutName + "\"" : "")
      : "Not an Office Ally chart page — the patient-ID check is skipped.";
  }

  async function onPatientChange() {
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
    renderSources();
    const check = R.checkPatient(state.page.pid, state.patient);
    if (!check.ok) setStatus(check.reason, true);
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
    if (!plan.fieldCount) {
      mount.innerHTML = '<div class="co-empty">No Office Ally note boxes found on this page. Open the patient\'s note form (Add Note / Encounter), then reopen this panel.</div>';
      return;
    }
    const warn = R.layoutWarning(state.note.form_id, state.page.layoutName);
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
  // Fills text boxes only. It never clicks Update, Apply, or anything that saves or signs — the
  // clinician reviews every box in Office Ally and saves and signs it themselves.
  function fill() {
    if (!state.note) { setStatus("Load a note first."); return; }

    // 1. Right chart? Refuse outright on a mismatch — a note in the wrong chart is the worst outcome.
    const check = R.checkPatient(state.page.pid, state.patient);
    if (!check.ok) { setStatus(check.reason, true); return; }

    // 2. Unresolved gaps would go into the chart as "[! …]". Make that a deliberate second click.
    const gaps = R.countGaps(state.note.sections);
    if (gaps && !state.gapsAcknowledged) {
      state.gapsAcknowledged = true;
      setStatus("This note still has " + gaps + " unresolved gap" + (gaps > 1 ? "s" : "") +
        " marked [! …]. Resolve them in Cadence, or click Fill again to fill with them visible.", true);
      return;
    }

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
    discoverFields().forEach((f) => { byKey[f.key] = f; });
    ((plan && plan.boxes) || []).forEach((b) => {
      const f = byKey[b.key];
      if (!f) { notFound++; return; }
      const current = (f.el.value || "").trim();
      if (current && current !== b.text.trim()) { occupied.push(b.label); return; }
      setFieldValue(f.el, b.text); filled++; touched.push(f.el);
    });

    revealFilled(touched);
    const unplaced = (plan && plan.unplaced) || [];
    const problems = unplaced.length + occupied.length + notFound;
    setStatus("Filled " + filled + " Office Ally box" + (filled === 1 ? "" : "es") + "." +
      (occupied.length ? " Not overwritten (already has text — clear it first): " + occupied.join(", ") + "." : "") +
      (unplaced.length ? " Copy in by hand: " + unplaced.map((u) => u.heading).join(", ") + "." : "") +
      (notFound ? " " + notFound + " field(s) not found on page." : "") +
      (skipped ? " " + skipped + " manual mapping(s) not in this note." : "") +
      " Review every box before saving and signing.", problems > 0);
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
      const proto = tag === "textarea" ? window.HTMLTextAreaElement.prototype : window.HTMLInputElement.prototype;
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
  function digitsOnly(s) { return String(s || "").replace(/\D/g, ""); }
  function fmtDate(d) { const x = d ? new Date(d) : null; return x && !isNaN(x) ? x.toLocaleDateString() : ""; }

  init();
})();
