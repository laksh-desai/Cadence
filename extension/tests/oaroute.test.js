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

// ---- Practice rules: layout per note type, encounter date, one encounter per day ----

// Layouts as a practice would save them in Manage Office. Nothing is built into the extension.
const PRACTICE = R.layoutRulesFrom({
  initial: { id: "374261", name: "Cadence Init Eval" },
  initial_updated: { id: "374261", name: "Cadence Init Eval" },
  followup: { id: "361919", name: "Progress Notes" },
});

test("no layout is built in: without Manage Office settings nothing is linked or blocked", () => {
  assert.deepStrictEqual(R.REQUIRED_LAYOUT, {});
  assert.strictEqual(R.checkLayout("initial", "361919", "Progress Notes").ok, true);
  assert.strictEqual(R.officeAllyUrls("123456789", "initial").addNote, "");
});

test("an Initial Evaluation must go into 'Cadence Init Eval' and a Follow-Up into 'Progress Notes'", () => {
  assert.strictEqual(R.checkLayout("initial", "374261", "Cadence Init Eval", PRACTICE).ok, true);
  assert.strictEqual(R.checkLayout("initial_updated", "", "Cadence Init Eval", PRACTICE).ok, true);
  assert.strictEqual(R.checkLayout("followup", "361919", "Progress Notes", PRACTICE).ok, true);
  const wrong = R.checkLayout("initial", "361919", "Progress Notes", PRACTICE);
  assert.strictEqual(wrong.ok, false);
  assert.ok(wrong.reason.indexOf("Cadence Init Eval") !== -1);
  assert.strictEqual(R.checkLayout("followup", "374261", "Cadence Init Eval", PRACTICE).ok, false);
});

test("a look-alike layout name is not accepted ('Copy Of Progress Notes' is not 'Progress Notes')", () => {
  assert.strictEqual(R.checkLayout("followup", "375083", "Copy Of Progress Notes", PRACTICE).ok, false);
  assert.strictEqual(R.checkLayout("followup", "352530", "DailyNotes New", PRACTICE).ok, false);
});

test("custom Cadence templates and non-Office-Ally pages are not blocked by the layout rule", () => {
  assert.strictEqual(R.checkLayout("my_custom_form", "361919", "Progress Notes", PRACTICE).ok, true);
  assert.strictEqual(R.checkLayout("initial", "", "", PRACTICE).ok, true);
});

test("noteDate gives the note's local calendar date as MM/DD/YYYY", () => {
  assert.strictEqual(R.noteDate("2026-09-28T10:15:00"), "09/28/2026"); // no zone → local
  assert.strictEqual(R.noteDate(""), "");
});

test("the Office Ally encounter date must equal the Cadence note date", () => {
  assert.strictEqual(R.checkEncounterDate("09/28/2026", { month: "9", day: "28", year: "2026" }).ok, true);
  const bad = R.checkEncounterDate("09/28/2026", { month: "9", day: "27", year: "2026" });
  assert.strictEqual(bad.ok, false);
  assert.ok(bad.reason.indexOf("09/27/2026") !== -1 && bad.reason.indexOf("09/28/2026") !== -1);
  assert.strictEqual(R.checkEncounterDate("", { month: "9", day: "28", year: "2026" }).ok, false);
  assert.strictEqual(R.checkEncounterDate("09/28/2026", "").ok, true); // not a note page
});

const ENCOUNTER_LIST_HTML = `
<table>
  <tr><th>Date</th><th>Encounter</th><th>Type</th></tr>
  <tr><td>09/28/2026</td><td><a href="PatientChart_EditNote.aspx?PageAction=EditNote&EID=349893114&PID=155793457">349893114</a></td><td>Initial Evaluation</td></tr>
  <tr><td>9/30/2026</td><td><a onclick="OpenNote('x', EID=351111111)">351111111</a></td><td>Progress Notes</td></tr>
  <tr><td>No link here 10/01/2026</td></tr>
</table>`;

test("parseEncounters reads encounter ids and dates from Office Ally's list", () => {
  assert.deepStrictEqual(R.parseEncounters(ENCOUNTER_LIST_HTML), [
    { eid: "349893114", date: "09/28/2026" },
    { eid: "351111111", date: "09/30/2026" },
  ]);
});

test("a second encounter on the same day blocks the fill", () => {
  const encs = R.parseEncounters(ENCOUNTER_LIST_HTML);
  const dup = R.checkSameDayEncounters(encs, "09/28/2026", "353868524");
  assert.strictEqual(dup.ok, false);
  assert.strictEqual(dup.block, true);
  assert.ok(dup.reason.indexOf("349893114") !== -1);
  assert.ok(/Delete the older encounter/.test(dup.reason));
});

test("the encounter being filled does not count as its own duplicate", () => {
  const encs = R.parseEncounters(ENCOUNTER_LIST_HTML);
  assert.strictEqual(R.checkSameDayEncounters(encs, "09/28/2026", "349893114").ok, true);
  assert.strictEqual(R.checkSameDayEncounters(encs, "10/05/2026", "999").ok, true);
});

test("an unreadable or empty encounter list asks the clinician to check instead of passing silently", () => {
  const unread = R.checkSameDayEncounters(null, "09/28/2026", "1");
  assert.strictEqual(unread.ok, false);
  assert.strictEqual(unread.block, false);
  const empty = R.checkSameDayEncounters([], "09/28/2026", "1");
  assert.strictEqual(empty.ok, false);
  assert.strictEqual(empty.block, false);
});

// ---- Login / page detection ----

test("pageKind tells a logged-in Office Ally page from its sign-in page and from other sites", () => {
  assert.strictEqual(R.pageKind("pm.officeally.com", "/emr/PatientCharts/PatientChart_EditNote.aspx", false), "officeally");
  assert.strictEqual(R.pageKind("x02.officeally.com", "/auth0bridge/Logon/CleanLogon", false), "login");
  assert.strictEqual(R.pageKind("pm.officeally.com", "/emr/default.aspx", true), "login"); // password box on page
  assert.strictEqual(R.pageKind("localhost", "/test-oa-form.html", false), "practice");
  assert.strictEqual(R.pageKind("example.com", "/", false), "other");
  assert.strictEqual(R.pageKind("officeally.com.evil.example", "/", false), "other");
});

test("looksLoggedOut spots an expired Office Ally session", () => {
  assert.strictEqual(R.looksLoggedOut("https://x02.officeally.com/auth0bridge/Logon/CleanLogon?returnUrl=/emr", ""), true);
  assert.strictEqual(R.looksLoggedOut("https://pm.officeally.com/emr/x.aspx", '<form><input type="password" name="p"></form>'), true);
  assert.strictEqual(R.looksLoggedOut("https://pm.officeally.com/emr/PatientCharts/Patient_Encounters.aspx", "<table><tr><td>09/28/2026</td></tr></table>"), false);
  // Every logged-in page has this keep-alive script; it must not read as "logged out" (real bug, 2026-09-28).
  const keepAlive = '<script>var loginPageUrl = "https://x02.officeally.com/auth0bridge/Logon/CleanLogon" + "?returnUrl=" + window.location.pathname;</script><table></table>';
  assert.strictEqual(R.looksLoggedOut("https://pm.officeally.com/emr/PatientCharts/PatientChart_ProgressNotes.aspx", keepAlive), false);
});

test("officeAllyUrls builds the practice's Progress Notes list and Add Note links for the right layout", () => {
  const eval_ = R.officeAllyUrls("123456789", "initial", PRACTICE);
  assert.strictEqual(eval_.addNote,
    "https://pm.officeally.com/emr/PatientCharts/PatientChart_EditNote.aspx?PageAction=AddNote&SoapLayoutID=374261&Tab=C&PID=123456789&Scope=&Date1=&Date2=");
  assert.strictEqual(eval_.progressNotes,
    "https://pm.officeally.com/emr/PatientCharts/PatientChart_ProgressNotes.aspx?PageAction=ProgressNotes,PatientCharts_ProgressNotes_Add&Tab=C&PID=123456789&Scope=&Date1=&Date2=");
  assert.ok(R.officeAllyUrls("123456789", "followup", PRACTICE).addNote.indexOf("SoapLayoutID=361919") !== -1);
  assert.strictEqual(R.officeAllyUrls("123456789", "my_custom", PRACTICE).addNote, ""); // no required layout
});

test("SOAP boxes are recognised under any parent prefix, still excluding diagnosis and nurse boxes", () => {
  assert.strictEqual(R.keyFromId("ctl00_phFolderContent_ucSOAPNote_S_Custom1"), "S_Custom1");
  assert.strictEqual(R.keyFromId("ctl00_ContentPlaceHolder1_ucSOAPNote_P_Plans"), "P_Plans");
  assert.strictEqual(R.keyFromId("ucSOAPNote_O_Objective"), "O_Objective");
  assert.strictEqual(R.keyFromId("ctl00_x_ucSOAPNote_ucDiagnosisCodes_A_A_10_1"), null);
  assert.strictEqual(R.keyFromId("ctl00_x_ucSOAPNote_NurseNote"), null);
});

test("layouts saved in Cadence's Manage Office replace the built-in defaults", () => {
  const rules = R.layoutRulesFrom({
    initial: { id: "500001", name: "Eval 2027" },
    followup: { id: "361919", name: "Progress Notes" },
    discharge: { id: "500002", name: "Discharge Summary" },
  });
  assert.strictEqual(R.checkLayout("initial", "500001", "Eval 2027", rules).ok, true);
  assert.strictEqual(R.checkLayout("initial", "374261", "Cadence Init Eval", rules).ok, false); // old default no longer accepted
  assert.ok(R.checkLayout("initial", "374261", "Cadence Init Eval", rules).reason.indexOf("Eval 2027") !== -1);
  assert.strictEqual(R.checkLayout("discharge", "500002", "Discharge Summary", rules).ok, true);
  assert.strictEqual(R.checkLayout("initial_updated", "999", "Anything", rules).ok, true); // no saved rule → not blocked
  assert.ok(R.officeAllyUrls("123456789", "discharge", rules).addNote.indexOf("SoapLayoutID=500002") !== -1);
  assert.strictEqual(R.layoutRulesFrom(null), null);
});

test("the visit date comes from the note's visit_date, else from when it was saved", () => {
  assert.strictEqual(R.visitDateOf({ visit_date: "2026-09-29", created_at: "2026-09-30T10:00:00" }), "09/29/2026");
  assert.strictEqual(R.visitDateOf({ created_at: "2026-09-28T10:00:00" }), "09/28/2026");
  assert.strictEqual(R.visitDateOf(null), "");
});

test("only a brand-new (Add Note) encounter counts as new", () => {
  assert.strictEqual(R.isNewEncounter("https://pm.officeally.com/emr/PatientCharts/PatientChart_EditNote.aspx?PageAction=AddNote&SoapLayoutID=361919&PID=1", ""), true);
  assert.strictEqual(R.isNewEncounter("", "Add Note / Encounter [Encounter ID 353868524 - User Defined SOAP Form]"), true);
  assert.strictEqual(R.isNewEncounter("https://pm.officeally.com/emr/PatientCharts/PatientChart_EditNote.aspx?PageAction=EditNote&EID=1", "Edit Note / Encounter [Encounter ID 1]"), false);
});

test("a long section fills the ROOM LEFT in a partly used box before moving on (found on the real page)", () => {
  const long = Array.from({ length: 30 }, (_, i) => "Finding " + i + ": steady progress with the prescribed program and tolerated increased load.").join(" ");
  const plan = R.planRouting([
    { heading: "Response to Treatment", text: "Good; tolerated the full session." },   // takes part of Assessment
    { heading: "Assessment Summary", text: long },
  ], PROGRESS_LAYOUT);
  assert.deepStrictEqual(plan.unplaced, []);
  const joined = plan.boxes.map((b) => b.text).join(" ");
  long.match(/[^.]+\./g).forEach((s) => assert.ok(joined.indexOf(s.trim()) !== -1, "lost: " + s));
  plan.boxes.forEach((b) => assert.ok(b.length <= 2000, b.key + " " + b.length));
});

// SDMPT's real "Cadence Init Eval" layout (SoapLayoutID 374261): the boxes and the labels the
// practice gave its custom boxes, read from a saved copy of the live form (no patient data).
const INIT_EVAL_LAYOUT = [
  { key: "S_ChiefComplaint" }, { key: "S_HOPI_Original" },
  { key: "S_Custom1", label: "Personal Factors" }, { key: "S_Custom2", label: "Cognition" },
  { key: "S_MedicalHistory" }, { key: "S_SurgicalHistory" }, { key: "S_SocialHistory" }, { key: "S_Medications" },
  { key: "S_Custom3", label: "History of Falls" }, { key: "S_Custom4", label: "Patient Goals" },
  { key: "S_ROS_Custom1", label: "Pain Description" },
  { key: "O_Objective" }, { key: "O_PE_Custom1", label: "Outcome Measurement tools" },
  { key: "O_PE_Custom2", label: "Special Test" }, { key: "O_FunctionalStatus" },
  { key: "A_Custom1", label: "Diagnosis" }, { key: "A_Custom2", label: "Clinical Presentation" },
  { key: "P_Procedures" }, { key: "P_GoalNotes" }, { key: "P_Plans" },
  { key: "P_Custom1", label: "Patient Education" }, { key: "P_Custom2", label: "Rehab Potential" },
  { key: "P_Custom3", label: "Contra Indication" }, { key: "P_Custom4", label: "Treatment Diagnosis" },
];

test("every Initial Evaluation section lands in the right box on the real Cadence Init Eval layout", () => {
  const plan = R.planRouting(INITIAL_SECTIONS, INIT_EVAL_LAYOUT);
  assert.deepStrictEqual(plan.unplaced, []);
  const where = (h) => boxOf(plan, h).key;
  assert.strictEqual(where("Chief Complaint"), "S_ChiefComplaint");
  assert.strictEqual(where("Diagnoses"), "A_Custom1");                   // "Diagnosis"
  assert.strictEqual(where("Medications"), "S_Medications");
  assert.strictEqual(where("Allergies"), "S_MedicalHistory");
  assert.strictEqual(where("Referral & Relevant History"), "S_MedicalHistory"); // not History Of Present Illness
  assert.strictEqual(where("Social History & Living Environment"), "S_SocialHistory");
  assert.strictEqual(where("Fall Risk"), "S_Custom3");                   // "History of Falls"
  assert.strictEqual(where("Musculoskeletal Assessment"), "O_Objective");
  assert.strictEqual(where("Functional Mobility"), "O_FunctionalStatus");
  assert.strictEqual(where("Assessment Summary"), "A_Custom2");          // "Clinical Presentation", not "Diagnosis"
  assert.strictEqual(where("Short-Term Goals"), "P_GoalNotes");
  assert.strictEqual(where("Plan of Treatment"), "P_Plans");
  plan.boxes.forEach((b) => assert.ok(b.key.indexOf("S_ROS_") !== 0));
});

test("a custom box is never chosen by its position: Init Eval's P_Custom1 is Patient Education, not goals", () => {
  const long = Array.from({ length: 40 }, (_, i) => "Goal " + i + ": walk further with less assistance within four weeks.").join(" ");
  const plan = R.planRouting([{ heading: "Short-Term Goals", text: long }], INIT_EVAL_LAYOUT);
  assert.ok(!plan.boxes.some((b) => b.key === "P_Custom1"), "goals overflowed into Patient Education");
  assert.ok(!plan.boxes.some((b) => b.key === "P_Custom3"), "goals overflowed into Contra Indication");
});

test("the practice's specific boxes receive sections of the same name", () => {
  const plan = R.planRouting([
    { heading: "Rehab Potential", text: "Good." }, { heading: "Patient Education", text: "HEP reviewed." },
    { heading: "Special Tests", text: "Lachman negative." }, { heading: "Outcome Measures", text: "TUG 14 s." },
    { heading: "Contraindications", text: "None." }, { heading: "Cognition", text: "Alert and oriented." },
    { heading: "Personal Factors", text: "Motivated." }, { heading: "Treatment Diagnosis", text: "Gait abnormality." },
  ], INIT_EVAL_LAYOUT);
  const where = (h) => boxOf(plan, h).key;
  assert.strictEqual(where("Rehab Potential"), "P_Custom2");
  assert.strictEqual(where("Patient Education"), "P_Custom1");
  assert.strictEqual(where("Special Tests"), "O_PE_Custom2");
  assert.strictEqual(where("Outcome Measures"), "O_PE_Custom1");
  assert.strictEqual(where("Contraindications"), "P_Custom3");
  assert.strictEqual(where("Cognition"), "S_Custom2");
  assert.strictEqual(where("Personal Factors"), "S_Custom1");
  assert.strictEqual(where("Treatment Diagnosis"), "P_Custom4");
});

// ---- Did the text really land in Office Ally? ----

test("verifyBoxes: every planned box holding exactly its text is a match (CRLF and trailing space ignored)", () => {
  const plan = R.planRouting([
    { heading: "Chief Complaint", text: "Left knee pain." },
    { heading: "Plan", text: "Continue 2x/week.\nProgress load." },
  ], PROGRESS_LAYOUT);
  const current = {};
  plan.boxes.forEach((b) => { current[b.key] = b.text.replace(/\n/g, "\r\n") + "  "; });
  const v = R.verifyBoxes(plan.boxes, current);
  assert.strictEqual(v.ok, true);
  assert.strictEqual(v.matched.length, plan.boxes.length);
});

test("verifyBoxes: an empty box or different text is reported by label, never counted as a match", () => {
  const boxes = [
    { key: "S_ChiefComplaint", label: "Chief Complaints", text: "Left knee pain." },
    { key: "P_Plans", label: "Plan Notes", text: "Continue 2x/week." },
    { key: "O_Objective", label: "Objective Notes", text: "AROM 5-90." },
  ];
  const v = R.verifyBoxes(boxes, { S_ChiefComplaint: "Left knee pain.", P_Plans: "", O_Objective: "AROM 5-9" });
  assert.strictEqual(v.ok, false);
  assert.deepStrictEqual(v.matched, ["Chief Complaints"]);
  assert.deepStrictEqual(v.empty, ["Plan Notes"]);
  assert.deepStrictEqual(v.differ, ["Objective Notes"]);
});

test("verifyBoxes: a box missing from the page counts as empty, and nothing planned is not ok", () => {
  assert.deepStrictEqual(R.verifyBoxes([{ key: "P_Plans", label: "Plan Notes", text: "x" }], {}).empty, ["Plan Notes"]);
  assert.strictEqual(R.verifyBoxes([], {}).ok, false);
});

// ---- Overflow into the other boxes of the same SOAP part ----

const longText = (n, word) => Array.from({ length: n }, (_, i) => word + " finding " + i + " was measured and recorded today.").join(" ");

test("a long Objective section overflows Objective Notes into Functional Status, never into topic boxes", () => {
  const body = longText(60, "Objective"); // ~3,300 characters: more than one box, less than two
  const plan = R.planRouting([{ heading: "Objective Summary", text: body }], INIT_EVAL_LAYOUT);
  assert.deepStrictEqual(plan.unplaced, []);
  const keys = plan.boxes.map((b) => b.key);
  assert.ok(keys.indexOf("O_Objective") !== -1);
  assert.ok(keys.indexOf("O_FunctionalStatus") !== -1, "overflow reached Functional Status: " + keys);
  assert.strictEqual(keys.indexOf("O_PE_Custom1"), -1);  // Outcome Measurement tools
  assert.strictEqual(keys.indexOf("O_PE_Custom2"), -1);  // Special Test
  const fs = plan.boxes.find((b) => b.key === "O_FunctionalStatus");
  assert.ok(/Objective Summary \(cont\.\)/.test(fs.text), "the continuation is labelled");
  plan.boxes.forEach((b) => assert.ok(b.length <= 2000));
  // Nothing lost: every sentence is somewhere.
  const joined = plan.boxes.map((b) => b.text).join(" ");
  body.split(/(?<=\.) /).forEach((sent) => assert.ok(joined.indexOf(sent) !== -1, "lost: " + sent));
});

test("overflow uses a box the practice labelled as a continuation, but never 'Contra Indication'", () => {
  const cont = R.planRouting([{ heading: "Plan of Treatment", text: longText(70, "Plan") }], PROGRESS_LAYOUT);
  assert.deepStrictEqual(cont.unplaced, []);
  const pk = cont.boxes.map((b) => b.key);
  assert.ok(pk.indexOf("P_Plans") !== -1);
  const init = R.planRouting([{ heading: "Plan of Treatment", text: longText(200, "Plan") }], INIT_EVAL_LAYOUT);
  assert.strictEqual(init.boxes.map((b) => b.key).indexOf("P_Custom3"), -1); // Contra Indication
  assert.strictEqual(init.boxes.map((b) => b.key).indexOf("P_Custom1"), -1); // Patient Education
});

test("a section that still cannot fit is reported with how much to cut, never truncated or reworded", () => {
  const plan = R.planRouting([{ heading: "Objective Summary", text: longText(400, "Objective") }], INIT_EVAL_LAYOUT);
  assert.strictEqual(plan.boxes.length, 0); // all or nothing
  assert.strictEqual(plan.unplaced.length, 1);
  assert.ok(plan.unplaced[0].over > 0);
  assert.ok(/shorten it in Cadence/.test(plan.unplaced[0].reason));
});
