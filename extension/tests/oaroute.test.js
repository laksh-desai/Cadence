"use strict";
// Tests for automatic Cadence → Office Ally routing. No browser needed.
//   node --test extension/tests/
const test = require("node:test");
const assert = require("node:assert");
const R = require("../lib/oaroute.js");

// The text boxes on SDMPT's real "Progress Notes" layout (SoapLayoutID 361919), in page order,
// with the labels that page shows. Taken from a saved copy of the live form.
const PROGRESS_LAYOUT = [
  { key: "S_ChiefComplaint", label: "Chief Complaints" },
  { key: "S_HOPI_Original", label: "History Of Present Illness" },
  { key: "S_ROS_Neck", label: "Neck" },
  { key: "S_ROS_Custom1", label: "Back" },
  { key: "S_ROS_Custom2", label: "Shoulder" },
  { key: "O_Objective", label: "Objective Notes" },
  { key: "O_PE_Neck", label: "Neck" },
  { key: "O_PE_Cardiovascular", label: "Cardiovascular" },
  { key: "O_PE_Musculoskeletal", label: "Musculoskeletal" },
  { key: "O_PE_Custom1", label: "Back" },
  { key: "O_PE_Custom2", label: "Shoulder" },
  { key: "O_FunctionalStatus", label: "Functional Status" },
  { key: "A_Custom1", label: "Assessment" },
  { key: "A_Custom2", label: "Assessment (Cont)" },
  { key: "P_Procedures", label: "Procedure Notes" },
  { key: "P_GoalNotes", label: "Goal Notes" },
  { key: "P_Plans", label: "Plan Notes" },
  { key: "P_PatientInstructions", label: "Patient Instructions / Follow Up" },
  { key: "P_PatientComments", label: "Patient / Parent or Guardian Comments" },
  { key: "P_Custom1", label: "Goals (Continue)" },
  { key: "P_Custom2", label: "Exercises (Continue)" },
  { key: "P_Custom3", label: "Next Steps" },
];

// The 17 sections of Cadence's Initial Evaluation template (templates/initial.md), short bodies.
const INITIAL_SECTIONS = [
  ["Chief Complaint", "Left knee pain limiting stairs four weeks after total knee replacement."],
  ["Diagnoses", "Status post left total knee arthroplasty."],
  ["Medications", "Tylenol 500 mg as needed. Lisinopril 10 mg daily."],
  ["Allergies", "Sulfa."],
  ["Referral & Relevant History", "Referred by orthopedics. Hypertension. Weight-bearing as tolerated."],
  ["Social History & Living Environment", "Lives alone, one step to enter."],
  ["Objective Summary", "Reduced knee range and quadriceps strength limit transfers and gait."],
  ["Fall Risk", "One fall last month."],
  ["Musculoskeletal Assessment", "Left knee AROM 5 to 90 degrees. Quadriceps 3+/5."],
  ["Other Systems", "Incision clean and dry. Pain 4/10."],
  ["Cardiopulmonary", "BP 130/80, HR 74 at rest."],
  ["Functional Mobility", "Sit to stand min assist. Gait 100 ft with walker."],
  ["Coordination / Sensation / Edema", "Mild edema at the left knee."],
  ["Assessment Summary", "Strength and mobility deficits; skilled PT indicated; good rehab potential."],
  ["Short-Term Goals", "In 2 weeks, walk 200 ft with walker, min assist."],
  ["Long-Term Goals", "In 6 weeks, independent household ambulation without device."],
  ["Plan of Treatment", "2x/week for 8 weeks, 60 minutes per session."],
].map(([heading, text]) => ({ heading, text }));

function boxOf(plan, heading) {
  return plan.boxes.find((b) => b.sections.indexOf(heading) !== -1);
}

test("every Initial Evaluation section lands in a sensible Progress Notes box", () => {
  const plan = R.planRouting(INITIAL_SECTIONS, PROGRESS_LAYOUT);
  assert.deepStrictEqual(plan.unplaced, []);
  const where = (h) => boxOf(plan, h).key;
  assert.strictEqual(where("Chief Complaint"), "S_ChiefComplaint");
  assert.strictEqual(where("Diagnoses"), "A_Custom1");
  // This layout has no Medications box, so medications go to the Subjective narrative box.
  assert.strictEqual(where("Medications"), "S_HOPI_Original");
  assert.strictEqual(where("Allergies"), "S_HOPI_Original");
  assert.strictEqual(where("Musculoskeletal Assessment"), "O_Objective"); // exam, not the Assessment
  assert.strictEqual(where("Functional Mobility"), "O_FunctionalStatus");
  assert.strictEqual(where("Assessment Summary"), "A_Custom1");
  assert.strictEqual(where("Short-Term Goals"), "P_GoalNotes");
  assert.strictEqual(where("Long-Term Goals"), "P_GoalNotes");
  assert.strictEqual(where("Plan of Treatment"), "P_Plans");
});

test("no box ever exceeds Office Ally's 2,000 characters, and Review-of-Systems boxes are never used", () => {
  const plan = R.planRouting(INITIAL_SECTIONS, PROGRESS_LAYOUT);
  plan.boxes.forEach((b) => {
    assert.ok(b.length <= 2000, b.key + " is " + b.length);
    assert.ok(b.key.indexOf("S_ROS_") !== 0, "routed into ROS box " + b.key);
  });
});

test("every section's text appears intact exactly once across the boxes", () => {
  const plan = R.planRouting(INITIAL_SECTIONS, PROGRESS_LAYOUT);
  const all = plan.boxes.map((b) => b.text).join("\n\n");
  INITIAL_SECTIONS.forEach((s) => {
    assert.strictEqual(all.split(s.text).length - 1, 1, "section " + s.heading);
  });
});

test("a box shared by several sections labels each one; a box with one same-named section does not repeat it", () => {
  const plan = R.planRouting(INITIAL_SECTIONS, PROGRESS_LAYOUT);
  const hopi = plan.boxes.find((b) => b.key === "S_HOPI_Original");
  assert.ok(/^Medications:\n/m.test(hopi.text));
  assert.ok(/^Allergies:\n/m.test(hopi.text));
  const cc = plan.boxes.find((b) => b.key === "S_ChiefComplaint");
  assert.strictEqual(cc.text, INITIAL_SECTIONS[0].text); // "Chief Complaints" box, no "Chief Complaint:" line
});

test("a box the practice labelled for a concept wins over the built-in default", () => {
  const layout = PROGRESS_LAYOUT.concat([{ key: "S_Custom1", label: "Medications" }, { key: "S_Custom2", label: "Allergies" }]);
  const plan = R.planRouting(INITIAL_SECTIONS, layout);
  assert.strictEqual(boxOf(plan, "Medications").key, "S_Custom1");
  assert.strictEqual(boxOf(plan, "Allergies").key, "S_Custom2");
});

test("a treatment performed today goes to Procedure Notes, never to the 'Exercises (Continue)' plan box", () => {
  const plan = R.planRouting([{ heading: "Therapeutic Exercise", text: "Minutes: 20. Quad sets, SLR." }], PROGRESS_LAYOUT);
  assert.strictEqual(plan.boxes[0].key, "P_Procedures");
});

test("when a box is full, the next section moves WHOLE to the next box of the same kind", () => {
  const long = "Assessment sentence here. ".repeat(60).trim(); // ~1,560 chars
  const sections = [
    { heading: "Diagnoses", text: long },
    { heading: "Assessment Summary", text: long },
  ];
  const plan = R.planRouting(sections, PROGRESS_LAYOUT);
  assert.deepStrictEqual(plan.unplaced, []);
  assert.strictEqual(boxOf(plan, "Diagnoses").key, "A_Custom1");
  assert.strictEqual(boxOf(plan, "Assessment Summary").key, "A_Custom2"); // "Assessment (Cont)"
  plan.boxes.forEach((b) => assert.ok(b.length <= 2000));
});

test("a section longer than any box is split only at sentence boundaries, into a '(cont.)' part", () => {
  const sentences = Array.from({ length: 70 }, (_, i) => "Finding number " + i + " was recorded today.");
  const plan = R.planRouting([{ heading: "Assessment Summary", text: sentences.join(" ") }], PROGRESS_LAYOUT);
  assert.deepStrictEqual(plan.unplaced, []);
  assert.strictEqual(plan.boxes.length, 2);
  assert.deepStrictEqual(plan.boxes.map((b) => b.key), ["A_Custom1", "A_Custom2"]);
  assert.ok(/Assessment Summary \(cont\.\):/.test(plan.boxes[1].text));
  const joined = plan.boxes.map((b) => b.text).join(" ");
  sentences.forEach((s) => assert.ok(joined.indexOf(s) !== -1, "lost or cut: " + s));
  plan.boxes.forEach((b) => assert.ok(b.length <= 2000));
});

test("a single sentence longer than a box is reported unplaced, never truncated", () => {
  const huge = "word ".repeat(600).trim(); // one 2,999-char sentence, no period
  const plan = R.planRouting([{ heading: "Assessment Summary", text: huge }], PROGRESS_LAYOUT);
  assert.strictEqual(plan.boxes.length, 0);
  assert.strictEqual(plan.unplaced.length, 1);
  assert.strictEqual(plan.unplaced[0].heading, "Assessment Summary");
});

test("a section with no matching box on the layout is reported, not dropped silently", () => {
  const plan = R.planRouting([{ heading: "Medications", text: "Lisinopril 10 mg." }], [{ key: "O_Objective" }]);
  assert.strictEqual(plan.boxes.length, 0);
  assert.strictEqual(plan.unplaced[0].heading, "Medications");
});

test("hand-mapped sections and boxes are left out of automatic routing", () => {
  const plan = R.planRouting(INITIAL_SECTIONS, PROGRESS_LAYOUT, {
    skipHeadings: ["chief complaint"], reservedKeys: ["A_Custom1"],
  });
  assert.ok(!boxOf(plan, "Chief Complaint"));
  assert.ok(!plan.boxes.some((b) => b.key === "A_Custom1"));
  assert.strictEqual(boxOf(plan, "Diagnoses").key, "A_Custom2");
});

test("Office Ally length counts each newline as two characters (stored as CRLF)", () => {
  assert.strictEqual(R.oaLength("ab"), 2);
  assert.strictEqual(R.oaLength("a\nb"), 4);
});

test("only SOAP text boxes are recognised as routable fields", () => {
  assert.strictEqual(R.keyFromId("ctl00_phFolderContent_ucSOAPNote_O_Objective"), "O_Objective");
  assert.strictEqual(R.keyFromId("ctl00_phFolderContent_ucSOAPNote_NurseNote"), null);
  assert.strictEqual(R.keyFromId("ctl00_phFolderContent_ucSOAPNote_ucDiagnosisCodes_A_A_10_1"), null);
  assert.strictEqual(R.keyFromId("something_else"), null);
});

test("checkPatient blocks a mismatched or unlinked chart and allows the matching one", () => {
  assert.strictEqual(R.checkPatient("155793457", { mrn: "155793457" }).ok, true);
  assert.strictEqual(R.checkPatient("155793457", { mrn: "999" }).ok, false);
  const unlinked = R.checkPatient("155793457", { mrn: "" });
  assert.strictEqual(unlinked.ok, false);
  assert.ok(unlinked.reason.indexOf("155793457") !== -1);
  assert.strictEqual(R.checkPatient("", { mrn: "" }).ok, true); // not an Office Ally chart (test form)
});

test("layoutWarning flags an evaluation filled into a daily layout and vice versa", () => {
  assert.ok(R.layoutWarning("initial", "Progress Notes"));
  assert.ok(R.layoutWarning("followup", "Cadence Init Eval"));
  assert.strictEqual(R.layoutWarning("initial", "Cadence Init Eval"), "");
  assert.strictEqual(R.layoutWarning("followup", "Progress Notes"), "");
});

test("countGaps counts unresolved [[NEEDS: ...]] markers", () => {
  assert.strictEqual(R.countGaps([{ body: "a [[NEEDS: x]] b [[NEEDS: y]]" }, { body: "none" }]), 2);
});
