/* Cadence → Office Ally — pure, DOM-free helpers.
 *
 * These are the testable core: turning a Cadence note into mappable "sources", rendering the
 * app's inline markers into clean text for an EHR field, building a robust selector from a picked
 * element, and the shape of a saved mapping. No chrome.* and no document here — the content script
 * and the node tests both load this same file (UMD-style export below).
 */
(function (root, factory) {
  const api = factory();
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.CadenceMap = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  // Render Cadence's inline markers so an EHR field gets legible text, not raw [[...]] syntax.
  // Mirrors markerToText() in app/ui/static/app.js (keep in sync).
  function markerToText(body) {
    return (body || "")
      .replace(/\[\[NEEDS:\s*([^\]]+)\]\]/g, "[! $1]")
      .replace(/\[\[CPT:\s*([^\]]+?)\s*—\s*confirm\]\]/g, "[CPT: $1]");
  }

  function normalizeHeading(h) {
    return (h || "").toLowerCase().replace(/\s+/g, " ").trim();
  }

  // SOAP classifier — ported from app/ui/static/app.js SOAP_RULES (keep in sync). Used only to
  // offer optional coarse "SOAP block" sources alongside the individual sections.
  const SOAP_LABELS = { S: "Subjective", O: "Objective", A: "Assessment", P: "Plan" };
  const SOAP_RULES = [
    ["chief complaint", "S"], ["history of present", "S"], ["summary of daily", "S"],
    ["social history", "S"], ["living environment", "S"], ["referral", "S"], ["precaution", "S"],
    ["medication", "S"], ["allerg", "S"], ["patient goal", "S"], ["subjective", "S"], ["complaint", "S"],
    ["short-term goal", "P"], ["long-term goal", "P"], ["plan", "P"], ["recommendation", "P"],
    ["home program", "P"], ["hep", "P"], ["goal", "P"],
    ["response to treatment", "A"], ["functional status", "A"],
    ["functional mobility", "O"], ["objective summary", "O"], ["musculoskeletal", "O"],
    ["range of motion", "O"], ["strength", "O"], ["mmt", "O"], ["gait", "O"], ["mobility", "O"],
    ["vitals", "O"], ["cardiopulmonary", "O"], ["pain", "O"], ["fall risk", "O"], ["other systems", "O"],
    ["coordination", "O"], ["sensation", "O"], ["edema", "O"], ["observation", "O"], ["posture", "O"],
    ["special test", "O"], ["outcome", "O"],
    ["therapeutic exercise", "O"], ["gait training", "O"], ["manual therapy", "O"], ["neuromuscular", "O"],
    ["therapeutic activit", "O"], ["ultrasound", "O"], ["e-stim", "O"], ["electrical stim", "O"],
    ["massage", "O"], ["traction", "O"], ["modalit", "O"], ["minutes", "O"], ["treatment", "O"],
    ["assessment", "A"], ["diagnos", "A"], ["impression", "A"], ["rehab potential", "A"],
    ["prognosis", "A"], ["justification", "A"], ["skilled service", "A"], ["clinical complexity", "A"],
  ];
  function soapBlockFor(heading) {
    const h = normalizeHeading(heading);
    for (let i = 0; i < SOAP_RULES.length; i++) {
      if (h.indexOf(SOAP_RULES[i][0]) !== -1) return SOAP_RULES[i][1];
    }
    return "O";
  }

  // Build the list of mappable sources from a fetched note (+ patient). Each source has a stable
  // `id` (what a mapping rule points at), a human `label`, a `kind`, and the resolved `text`.
  function noteSources(note, patient) {
    const out = [];
    if (patient) {
      if (patient.name) out.push({ id: "patient:name", label: "Patient name", kind: "patient", text: String(patient.name) });
      if (patient.dob) out.push({ id: "patient:dob", label: "Date of birth", kind: "patient", text: String(patient.dob) });
      if (patient.mrn) out.push({ id: "patient:mrn", label: "MRN", kind: "patient", text: String(patient.mrn) });
    }
    const sections = (note && note.sections) || [];
    sections.forEach(function (s) {
      out.push({
        id: "section:" + normalizeHeading(s.heading),
        label: s.heading,
        kind: "section",
        text: markerToText(s.body).trim(),
      });
    });
    // Optional coarse SOAP-block sources (handy if an OA form has a few big S/O/A/P boxes).
    const groups = { S: [], O: [], A: [], P: [] };
    sections.forEach(function (s) { groups[soapBlockFor(s.heading)].push(s); });
    ["S", "O", "A", "P"].forEach(function (k) {
      if (groups[k].length) {
        const text = groups[k]
          .map(function (s) { return s.heading + "\n" + markerToText(s.body).trim(); })
          .join("\n\n").trim();
        out.push({ id: "soap:" + k, label: "SOAP · " + SOAP_LABELS[k], kind: "soap", text: text });
      }
    });
    return out;
  }

  // What text should fill the field mapped to `sourceId`, given the current note/patient. Returns
  // null when the source isn't present in this note (caller skips — never overwrites with blank).
  function resolveSource(sourceId, note, patient) {
    const src = noteSources(note, patient).find(function (s) { return s.id === sourceId; });
    return src ? src.text : null;
  }

  function cssEscapeAttr(s) { return String(s).replace(/["\\]/g, "\\$&"); }

  // Turn a picked-element descriptor into a stable CSS selector. Prefer a real id, then name,
  // then a nth-of-type path. `descriptor` is captured in the content script (no DOM needed here).
  //   descriptor: { id, name, tag, path: [{ tag, index }] }
  function buildSelector(descriptor) {
    if (!descriptor) return null;
    if (descriptor.id && /^[A-Za-z][\w-]*$/.test(descriptor.id)) return "#" + descriptor.id;
    if (descriptor.name) return (descriptor.tag || "") + '[name="' + cssEscapeAttr(descriptor.name) + '"]';
    if (descriptor.path && descriptor.path.length) {
      return descriptor.path
        .map(function (p) { return p.tag + ":nth-of-type(" + p.index + ")"; })
        .join(" > ");
    }
    return descriptor.tag || null;
  }

  // ---- Saved-mapping record (per Office Ally form) ----
  function emptyMapping(label) {
    return { label: label || "", rules: [], updatedAt: new Date().toISOString() };
  }
  function upsertRule(mapping, sourceId, selector, targetType) {
    const rules = ((mapping && mapping.rules) || []).filter(function (r) { return r.sourceId !== sourceId; });
    rules.push({ sourceId: sourceId, selector: selector, targetType: targetType || "input" });
    return Object.assign({}, mapping, { rules: rules, updatedAt: new Date().toISOString() });
  }
  function removeRule(mapping, sourceId) {
    const rules = ((mapping && mapping.rules) || []).filter(function (r) { return r.sourceId !== sourceId; });
    return Object.assign({}, mapping, { rules: rules, updatedAt: new Date().toISOString() });
  }
  function ruleFor(mapping, sourceId) {
    return ((mapping && mapping.rules) || []).find(function (r) { return r.sourceId === sourceId; }) || null;
  }
  // Stable key for a given OA form, so a mapping set once is reused on that form.
  function formKeyFromUrl(url) {
    try { const u = new URL(url); return u.hostname + u.pathname; } catch (_) { return url || "default"; }
  }

  return {
    markerToText: markerToText,
    normalizeHeading: normalizeHeading,
    soapBlockFor: soapBlockFor,
    SOAP_LABELS: SOAP_LABELS,
    noteSources: noteSources,
    resolveSource: resolveSource,
    buildSelector: buildSelector,
    emptyMapping: emptyMapping,
    upsertRule: upsertRule,
    removeRule: removeRule,
    ruleFor: ruleFor,
    formKeyFromUrl: formKeyFromUrl,
  };
});
