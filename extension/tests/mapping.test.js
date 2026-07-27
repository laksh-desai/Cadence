"use strict";
// Pure-helper tests for the extension core. No browser needed.
//   node --test extension/tests/mapping.test.js
const test = require("node:test");
const assert = require("node:assert");
const M = require("../lib/mapping.js");

const NOTE = {
  form_name: "Follow-Up Visit",
  sections: [
    { heading: "Functional Status", body: "Ambulates 200 ft with a cane. [[NEEDS: assist level — verify]]", carried_forward: true },
    { heading: "Gait Training", body: "Minutes: 15. Parallel bars. [[CPT: 97116 Gait Training — confirm]]", carried_forward: false },
    { heading: "Plan", body: "Continue 3x/week.", carried_forward: false },
  ],
};
const PATIENT = { name: "Alex Rivera", dob: "01/02/1960", mrn: "01023-557" };

test("markerToText renders NEEDS and CPT markers legibly", () => {
  assert.strictEqual(M.markerToText("x [[NEEDS: assist level — verify]]"), "x [! assist level — verify]");
  assert.strictEqual(M.markerToText("y [[CPT: 97116 Gait Training — confirm]]"), "y [CPT: 97116 Gait Training]");
});

test("noteSources yields patient fields, sections, and SOAP blocks", () => {
  const sources = M.noteSources(NOTE, PATIENT);
  const ids = sources.map((s) => s.id);
  assert.ok(ids.includes("patient:name"));
  assert.ok(ids.includes("section:functional status"));
  assert.ok(ids.includes("section:gait training"));
  assert.ok(ids.includes("soap:P")); // "Plan" -> Plan block
  // Section text has markers rendered and is trimmed.
  const fs = sources.find((s) => s.id === "section:functional status");
  assert.strictEqual(fs.text, "Ambulates 200 ft with a cane. [! assist level — verify]");
});

test("resolveSource returns mapped text, or null when absent", () => {
  assert.strictEqual(M.resolveSource("patient:mrn", NOTE, PATIENT), "01023-557");
  assert.strictEqual(M.resolveSource("section:plan", NOTE, PATIENT), "Continue 3x/week.");
  assert.strictEqual(M.resolveSource("section:nonexistent", NOTE, PATIENT), null);
});

test("buildSelector prefers id, then name, then a path", () => {
  assert.strictEqual(M.buildSelector({ id: "fldFunc", tag: "textarea" }), "#fldFunc");
  assert.strictEqual(M.buildSelector({ name: "func_status", tag: "textarea" }), 'textarea[name="func_status"]');
  assert.strictEqual(
    M.buildSelector({ tag: "input", path: [{ tag: "form", index: 1 }, { tag: "input", index: 3 }] }),
    "form:nth-of-type(1) > input:nth-of-type(3)"
  );
  // An id that isn't a valid bare selector falls back to a path/name, not "#weird id".
  assert.notStrictEqual(M.buildSelector({ id: "weird id", name: "n", tag: "input" }), "#weird id");
});

test("mapping record upsert/remove/ruleFor are pure and de-duplicate by source", () => {
  let m = M.emptyMapping("PT Follow-Up");
  m = M.upsertRule(m, "section:functional status", "#a", "textarea");
  m = M.upsertRule(m, "section:plan", "#b", "textarea");
  assert.strictEqual(m.rules.length, 2);
  // Re-mapping the same source replaces, not duplicates.
  m = M.upsertRule(m, "section:functional status", "#a2", "textarea");
  assert.strictEqual(m.rules.length, 2);
  assert.strictEqual(M.ruleFor(m, "section:functional status").selector, "#a2");
  m = M.removeRule(m, "section:plan");
  assert.strictEqual(m.rules.length, 1);
  assert.strictEqual(M.ruleFor(m, "section:plan"), null);
});

test("formKeyFromUrl is stable per form (host + path, ignores query)", () => {
  assert.strictEqual(
    M.formKeyFromUrl("https://ehr.officeally.com/note/edit?id=5&t=2"),
    "ehr.officeally.com/note/edit"
  );
});
