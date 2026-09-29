/* Cadence → Office Ally — automatic field routing (pure, DOM-free).
 *
 * The problem this solves: a Cadence note has one "## " section per field (Chief Complaint,
 * Diagnoses, Medications, … ~17 of them for an Initial Evaluation), while an Office Ally SOAP
 * layout has a DIFFERENT, smaller set of text boxes (Chief Complaints, History Of Present Illness,
 * Objective Notes, Assessment, Plan Notes, …), each capped at 2,000 characters. The two outlines
 * do not line up, and a practice can relabel Office Ally's custom boxes per layout.
 *
 * Office Ally's user-defined layouts all draw from ONE fixed set of field keys
 * (`ctl00_phFolderContent_ucSOAPNote_<KEY>`); a layout only chooses which boxes are shown and what
 * the custom ones are called. So routing is done against the keys and labels that are actually on
 * the page at fill time, never against a hard-coded layout:
 *
 *   1. Each Cadence section is classified into a CONCEPT by its heading (chief complaint,
 *      medications, goals, …). The concept names its preferred Office Ally keys and the label words
 *      that identify a box meant for it (a custom box the practice labelled "Medications" wins).
 *   2. Candidates, in order: boxes whose label names the concept → the concept's preferred keys →
 *      the SOAP bucket's general boxes (e.g. anything Objective falls back to Objective Notes).
 *   3. Sections are packed into boxes in note order, WHOLE, with their heading as a sub-label.
 *      A section that does not fit moves whole to the next candidate; only a section that is by
 *      itself longer than a box is split, and then only at a paragraph or sentence boundary into a
 *      "(cont.)" part. Nothing is ever cut mid-sentence and nothing is ever truncated — whatever
 *      cannot be placed is reported as unplaced so the clinician pastes it by hand.
 *
 * The clinician reviews every box in Office Ally before signing; this only drafts the fill.
 */
(function (root, factory) {
  const api = factory();
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.CadenceRoute = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  const FIELD_PREFIX = "ctl00_phFolderContent_ucSOAPNote_";
  const DEFAULT_MAX = 2000;

  // Office Ally's own label for each built-in box (used when the page gives no custom label).
  const DEFAULT_LABELS = {
    S_ChiefComplaint: "Chief Complaints",
    S_HOPI_Original: "History Of Present Illness",
    S_MedicalHistory: "Medical History",
    S_SurgicalHistory: "Surgical History",
    S_FamilyHistory: "Family History",
    S_SocialHistory: "Social History",
    S_Medications: "Medications",
    S_Allergies: "Allergies",
    O_Objective: "Objective Notes",
    O_FunctionalStatus: "Functional Status",
    O_PE_Musculoskeletal: "Musculoskeletal",
    O_PE_Neurological: "Neurological",
    O_PE_Cardiovascular: "Cardiovascular",
    O_PE_Skin: "Skin",
    P_Procedures: "Procedure Notes",
    P_GoalNotes: "Goal Notes",
    P_Plans: "Plan Notes",
    P_PatientInstructions: "Patient Instructions / Follow Up",
    P_PatientComments: "Patient / Parent or Guardian Comments",
  };

  // Where a section goes when nothing more specific fits — the general box of its SOAP bucket.
  // Built-in keys first, then CUSTOM boxes whose label says they are a general box of that part
  // (Progress Notes' "Assessment" / "Assessment (Cont)", "Next Steps"). Never a custom box by key.
  const BUCKET_FALLBACK = {
    S: { keys: ["S_HOPI_Original", "S_MedicalHistory"], labels: [] },
    O: { keys: ["O_Objective", "O_PE_Musculoskeletal"], labels: ["objective"] },
    A: { keys: [], labels: ["assessment", "clinical presentation", "impression"] },
    P: { keys: ["P_Plans"], labels: ["plan", "next step"] },
  };

  // Concepts, checked IN ORDER against the Cadence heading (first match wins, so specific phrases
  // come before general ones: "functional status" before "status", "short-term goal" before
  // "goal", treatment names before "exercise"). `labels` are the words that mark an Office Ally box
  // as meant for this concept; they are matched against box LABELS only, never against the
  // section heading, so "Therapeutic Exercise" cannot be routed into "Exercises (Continue)".
  //
  // `keys` name BUILT-IN boxes only (S_ChiefComplaint, P_GoalNotes, …), whose meaning is fixed.
  // CUSTOM boxes (S_Custom1…4, A_Custom1…2, P_Custom1…4, O_PE_Custom…) mean different things on
  // different layouts — P_Custom1 is "Goals (Continue)" on Progress Notes but "Patient Education" on
  // Cadence Init Eval — so they are only ever chosen by their LABEL, never by key.
  //
  // `anyBucket`: the label is specific enough to trust even when the practice put that box in a
  // different SOAP part (e.g. "History of Falls" sits under Subjective on Cadence Init Eval).
  const CONCEPTS = [
    { id: "chief_complaint", match: ["chief complaint", "complaint"], bucket: "S",
      keys: ["S_ChiefComplaint"], labels: ["chief complaint", "complaint"] },
    { id: "narrative", match: ["summary of daily", "present illness", "subjective"], bucket: "S",
      keys: ["S_HOPI_Original"], labels: ["present illness", "subjective"] },
    { id: "treatment_diagnosis", match: ["treatment diagnosis"], bucket: "A", anyBucket: true,
      keys: [], labels: ["treatment diagnosis"] },
    { id: "diagnosis", match: ["diagnos"], bucket: "A",
      keys: [], labels: ["diagnos"] },
    { id: "medications", match: ["medication"], bucket: "S",
      keys: ["S_Medications", "S_MedicalHistory"], labels: ["medication"] },
    { id: "allergies", match: ["allerg"], bucket: "S",
      keys: ["S_Allergies", "S_MedicalHistory"], labels: ["allerg"] },
    { id: "social", match: ["social history", "living environment", "social"], bucket: "S",
      keys: ["S_SocialHistory"], labels: ["social", "living"] },
    { id: "personal_factors", match: ["personal factor"], bucket: "S", anyBucket: true,
      keys: ["S_SocialHistory"], labels: ["personal factor"] },
    { id: "cognition", match: ["cognition", "cognitive"], bucket: "O", anyBucket: true,
      keys: ["O_Objective"], labels: ["cognition", "cognitive"] },
    { id: "falls", match: ["fall"], bucket: "O", anyBucket: true,
      keys: ["O_Objective"], labels: ["fall"] },
    { id: "contraindication", match: ["contraindication", "contra indication", "contra-indication"], bucket: "S", anyBucket: true,
      keys: ["S_MedicalHistory"], labels: ["contraindication", "contra indication", "contra-indication"] },
    // "history" alone is NOT a label word: "History Of Present Illness" and "History of Falls" are
    // not where a referral and past medical history belong.
    { id: "history", match: ["referral", "history", "precaution", "prior level"], bucket: "S",
      keys: ["S_MedicalHistory", "S_HOPI_Original"], labels: ["medical history", "precaution"] },
    { id: "treatment", bucket: "O",
      match: ["therapeutic exercise", "therapeutic activit", "neuromuscular", "gait training",
        "manual therapy", "self-care", "home management", "ultrasound", "electrical stim", "e-stim",
        "traction", "massage", "modalit", "intervention", "treatment performed"],
      keys: ["P_Procedures", "O_Objective"], labels: ["procedure", "intervention"] },
    { id: "functional", match: ["functional status", "functional mobility", "function"], bucket: "O",
      keys: ["O_FunctionalStatus", "O_Objective"], labels: ["functional"] },
    { id: "special_tests", match: ["special test"], bucket: "O", anyBucket: true,
      keys: ["O_Objective"], labels: ["special test"] },
    { id: "outcome_measures", match: ["outcome", "standardized test", "berg", "timed up and go"], bucket: "O", anyBucket: true,
      keys: ["O_Objective"], labels: ["outcome"] },
    // Before "assessment": a heading like "Musculoskeletal Assessment" is exam findings (Objective),
    // not the clinical assessment.
    { id: "musculoskeletal", match: ["musculoskeletal", "range of motion", "strength", "mmt"], bucket: "O",
      keys: ["O_Objective", "O_PE_Musculoskeletal"], labels: ["objective", "musculoskeletal"] },
    { id: "short_goals", match: ["short-term goal", "short term goal"], bucket: "P",
      keys: ["P_GoalNotes"], labels: ["goal"] },
    { id: "long_goals", match: ["long-term goal", "long term goal", "goal"], bucket: "P",
      keys: ["P_GoalNotes"], labels: ["goal"] },
    { id: "rehab_potential", match: ["rehab potential", "rehabilitation potential", "prognosis"], bucket: "A", anyBucket: true,
      keys: [], labels: ["rehab potential", "rehabilitation potential", "prognosis"] },
    { id: "education", match: ["patient education", "education"], bucket: "P", anyBucket: true,
      keys: ["P_PatientInstructions"], labels: ["education"] },
    { id: "assessment", bucket: "A",
      match: ["assessment", "impression", "clinical complexity", "clinical presentation",
        "response to treatment", "justification"],
      keys: [], labels: ["assessment", "clinical presentation", "impression"] },
    { id: "home_program", match: ["home exercise", "home program", "hep"], bucket: "P",
      keys: ["P_PatientInstructions"], labels: ["instruction", "home", "exercise"] },
    { id: "plan", match: ["plan", "recommendation", "discharge", "next visit", "frequency"], bucket: "P",
      keys: ["P_Plans"], labels: ["plan", "next step"] },
    { id: "objective", bucket: "O",
      match: ["objective", "other systems", "cardiopulmonary", "vital", "pain",
        "coordination", "sensation", "edema", "posture"],
      keys: ["O_Objective"], labels: ["objective"] },
  ];

  function norm(s) { return String(s || "").toLowerCase().replace(/\s+/g, " ").trim(); }

  function conceptFor(heading) {
    const h = norm(heading);
    for (let i = 0; i < CONCEPTS.length; i++) {
      const c = CONCEPTS[i];
      for (let j = 0; j < c.match.length; j++) if (h.indexOf(c.match[j]) !== -1) return c;
    }
    return { id: "other", match: [], bucket: "O", keys: ["O_Objective"], labels: [] };
  }

  // Office Ally stores the box value with CRLF line breaks, so a newline costs two characters
  // against the 2,000 limit. Measuring it as one would let a box pass here and fail there.
  function oaLength(text) {
    const s = String(text || "");
    return s.length + (s.match(/\n/g) || []).length;
  }

  // The key part of an Office Ally field id, or null if the element is not a SOAP text box.
  // Accepts any prefix ending in "ucSOAPNote_" — a custom layout may render the note control under
  // a different parent than Progress Notes' `ctl00_phFolderContent_`.
  function keyFromId(id) {
    const m = /(?:^|_)ucSOAPNote_([SOAP]_[A-Za-z0-9_]+)$/.exec(String(id || ""));
    return m ? m[1] : null;
  }

  function bucketOfKey(key) { return String(key).charAt(0); }

  // Normalise the discovered page fields: [{ key, label?, maxLen? }] in page order.
  function normalizeFields(fields) {
    // Review-of-Systems boxes are the patient's per-system answers; no Cadence section is one, so
    // they are never auto-filled (they stay available for a manual mapping).
    return (fields || []).filter(function (f) { return f && f.key && f.key.indexOf("S_ROS_") !== 0; }).map(function (f, i) {
      const label = String(f.label || DEFAULT_LABELS[f.key] || f.key).replace(/[:\s]+$/, "").trim();
      return { key: f.key, label: label, maxLen: f.maxLen > 0 ? f.maxLen : DEFAULT_MAX, order: i };
    });
  }

  function candidatesFor(concept, fields) {
    const byKey = {};
    fields.forEach(function (f) { byKey[f.key] = f; });
    const out = [];
    const push = function (f) { if (f && out.indexOf(f) === -1) out.push(f); };
    // 1. A box labelled for this concept (a practice's own naming wins over the defaults) — only
    //    within the section's SOAP bucket, so an Objective finding never lands in a Subjective box
    //    that happens to share a word.
    //    (A concept marked anyBucket trusts its very specific label wherever the box sits.)
    const labelled = function (words, anyBucket) {
      fields.forEach(function (f) {
        const l = norm(f.label);
        if ((anyBucket || bucketOfKey(f.key) === concept.bucket) && words.some(function (w) { return l.indexOf(w) !== -1; })) push(f);
      });
    };
    labelled(concept.labels, concept.anyBucket);
    // 2. The concept's preferred BUILT-IN boxes.
    concept.keys.forEach(function (k) { push(byKey[k]); });
    // 3. The general boxes of the section's SOAP part: built-in ones, then custom ones by label.
    const fb = BUCKET_FALLBACK[concept.bucket] || { keys: [], labels: [] };
    fb.keys.forEach(function (k) { push(byKey[k]); });
    labelled(fb.labels, false);
    return out;
  }

  // Last-resort room for a section too long for its own boxes: the OTHER general boxes of the same
  // SOAP part (e.g. Objective Notes full -> Functional Status), and any box the practice labelled as
  // a continuation ("Assessment (Cont)", "Goals (Continue)"). Custom boxes with a specific topic
  // ("Special Test", "Diagnosis") are never used as overflow — unrelated text there would mislead.
  // Only "(cont.)" parts land here, so the reader always sees where a section carries on.
  function overflowFor(concept, fields, taken) {
    return fields.filter(function (f) {
      if (taken.indexOf(f) !== -1 || bucketOfKey(f.key) !== concept.bucket) return false;
      return f.key.indexOf("Custom") === -1 || /\bcont(inue|inued)?\b|\(cont\b/.test(norm(f.label));
    });
  }

  // Split an oversized body at paragraph, then sentence, boundaries into pieces of at most
  // `limit` Office Ally characters. Returns null if even one sentence is longer than the limit —
  // the caller then reports the section unplaced rather than cutting a sentence in half.
  function splitAtBoundaries(body, limit) {
    // Each unit remembers how it joins the one before it: a new paragraph keeps its blank line,
    // a sentence continuing the same paragraph joins with a space.
    const units = [];
    String(body).split(/\n\s*\n/).forEach(function (para) {
      para = para.trim();
      if (!para) return;
      if (oaLength(para) <= limit) { units.push({ text: para, sep: "\n\n" }); return; }
      (para.match(/[^.!?]+[.!?]+["')\]]*\s*|[^.!?]+$/g) || [para]).forEach(function (s, k) {
        s = s.trim();
        if (s) units.push({ text: s, sep: k === 0 ? "\n\n" : " " });
      });
    });
    const parts = [];
    let cur = "";
    for (let i = 0; i < units.length; i++) {
      const u = units[i];
      if (oaLength(u.text) > limit) return null;
      const next = cur ? cur + u.sep + u.text : u.text;
      if (oaLength(next) <= limit) cur = next;
      else { parts.push(cur); cur = u.text; }
    }
    if (cur) parts.push(cur);
    return parts;
  }

  // A body cut into paragraphs, and long paragraphs into sentences — each remembering how it
  // joins the previous one (a blank line between paragraphs, a space within one).
  function boundaryUnits(body) {
    const units = [];
    String(body).split(/\n\s*\n/).forEach(function (para) {
      para = para.trim();
      if (!para) return;
      (para.match(/[^.!?]+[.!?]+["')\]]*\s*|[^.!?]+$/g) || [para]).forEach(function (s, k) {
        s = s.trim();
        if (s) units.push({ text: s, sep: k === 0 ? "\n\n" : " " });
      });
    });
    return units;
  }

  // Render one section as it appears inside a shared box. The heading is dropped only when the
  // section is alone in a box that already carries the same name, so the box never reads
  // "Chief Complaints: / Chief Complaint: …".
  function renderBlock(heading, body) { return heading + ":\n" + body; }

  function sameName(a, b) {
    const x = norm(a).replace(/s\b/g, ""), y = norm(b).replace(/s\b/g, "");
    return x === y || x.indexOf(y) !== -1 || y.indexOf(x) !== -1;
  }

  function boxText(box) {
    if (box.blocks.length === 1 && sameName(box.blocks[0].heading, box.label)) return box.blocks[0].body;
    return box.blocks.map(function (b) { return renderBlock(b.heading, b.body); }).join("\n\n");
  }

  function fits(box, heading, body) {
    const trial = { label: box.label, blocks: box.blocks.concat([{ heading: heading, body: body }]) };
    return oaLength(boxText(trial)) <= box.maxLen;
  }

  /**
   * Plan how a note's sections fill the Office Ally boxes present on the page.
   *   sections: [{ heading, text }]      text already rendered for an EHR (markers converted)
   *   fields:   [{ key, label?, maxLen? }] boxes discovered on the page, in page order
   *   opts.skipHeadings: normalised headings the clinician mapped by hand (routed elsewhere)
   *   opts.reservedKeys: box keys already taken by a hand mapping
   * Returns { boxes: [{ key, label, maxLen, text, length, sections: [heading] }],
   *           unplaced: [{ heading, reason }] }
   */
  function planRouting(sections, fields, opts) {
    opts = opts || {};
    const skip = opts.skipHeadings || [];
    const reserved = opts.reservedKeys || [];
    const all = normalizeFields(fields).filter(function (f) { return reserved.indexOf(f.key) === -1; });
    const boxes = {};
    const boxFor = function (f) {
      if (!boxes[f.key]) boxes[f.key] = { key: f.key, label: f.label, maxLen: f.maxLen, order: f.order, blocks: [] };
      return boxes[f.key];
    };
    const unplaced = [];

    (sections || []).forEach(function (s) {
      const heading = String(s.heading || "").trim();
      const body = String(s.text || "").trim();
      if (!body || skip.indexOf(norm(heading)) !== -1) return;
      const cands = candidatesFor(conceptFor(heading), all);
      if (!cands.length) { unplaced.push({ heading: heading, reason: "no matching Office Ally box on this layout" }); return; }

      // Whole section into the first candidate with room.
      for (let i = 0; i < cands.length; i++) {
        const box = boxFor(cands[i]);
        if (fits(box, heading, body)) { box.blocks.push({ heading: heading, body: body }); return; }
      }

      // Too long for any box whole: pour it, sentence by sentence, into the candidates in order,
      // filling each box's REMAINING room (a box already holding another section still takes
      // what fits). Parts after the first are labelled "(cont.)". Never mid-sentence.
      const units = boundaryUnits(body);
      const pour = cands.concat(overflowFor(conceptFor(heading), all, cands));
      const biggest = Math.max.apply(null, pour.map(function (c) { return c.maxLen; }));
      if (units.some(function (u) { return oaLength(u.text) > biggest - oaLength(heading + " (cont.):\n"); })) {
        unplaced.push({ heading: heading, reason: "a single sentence is longer than an Office Ally box" });
        return;
      }
      const placed = [];
      let ui = 0;
      for (let ci = 0; ci < pour.length && ui < units.length; ci++) {
        const box = boxFor(pour[ci]);
        const h = placed.length ? heading + " (cont.)" : heading;
        let chunk = "";
        while (ui < units.length) {
          const next = chunk ? chunk + units[ui].sep + units[ui].text : units[ui].text;
          if (!fits(box, h, next)) break;
          chunk = next;
          ui++;
        }
        if (chunk) placed.push({ box: box, block: { heading: h, body: chunk } });
      }
      if (ui < units.length) {
        const left = units.slice(ui).reduce(function (n, u) { return n + oaLength(u.text) + 1; }, 0);
        unplaced.push({ heading: heading, over: left,
          reason: "about " + left.toLocaleString() + " characters more than its Office Ally boxes can hold — shorten it in Cadence " +
            "(Ask for changes: \"shorten " + heading + " by about " + left.toLocaleString() + " characters, keep every value\"), then Fill again" });
        return; // all or nothing: half a section in the chart is worse than none
      }
      placed.forEach(function (x) { x.box.blocks.push(x.block); });
    });

    const out = Object.keys(boxes).map(function (k) { return boxes[k]; })
      .filter(function (b) { return b.blocks.length; })
      .sort(function (a, b) { return a.order - b.order; })
      .map(function (b) {
        const text = boxText(b);
        return { key: b.key, label: b.label, maxLen: b.maxLen, text: text, length: oaLength(text),
          sections: b.blocks.map(function (x) { return x.heading; }) };
      });
    return { boxes: out, unplaced: unplaced };
  }

  // ---- Safety checks that do not need the DOM ----

  function digits(s) { return String(s || "").replace(/\D/g, ""); }

  // Is the Cadence patient the Office Ally chart that is open? Cadence stores the Office Ally
  // Patient ID in the patient's MRN field. Returns { ok, reason }.
  function checkPatient(pagePid, patient) {
    const page = digits(pagePid);
    if (!page) return { ok: true, reason: "not an Office Ally chart page" };
    const mrn = digits(patient && patient.mrn);
    if (!mrn) {
      return { ok: false, reason: "This Cadence patient has no Office Ally Patient ID. Enter " + page +
        " as the patient's MRN in Cadence (Edit patient), then try again." };
    }
    if (mrn !== page) {
      return { ok: false, reason: "Wrong chart: this Office Ally page is Patient ID " + page +
        " but the Cadence patient's ID is " + mrn + ". Nothing was filled." };
    }
    return { ok: true, reason: "" };
  }

  // ---- Practice rules: see docs/OfficeAlly_Integration_Rules.md ----

  // Each Cadence note type must be filled into exactly one Office Ally layout. Matched on the
  // layout's id OR its exact name — never a partial name, so "Copy Of Progress Notes" is not
  // "Progress Notes". NOTHING is built in: SoapLayoutIDs belong to one practice's Office Ally
  // account, so the rules come only from Cadence's Manage Office settings (layoutRulesFrom). A note
  // type with no saved layout has no rule and is not blocked.
  const REQUIRED_LAYOUT = {};

  // The Office Ally pages Cadence sends the clinician to (URL patterns supplied by the practice):
  //   progressNotes — the patient's Progress Notes list
  //   addNote       — a NEW encounter already on the layout this note type requires
  function officeAllyUrls(pid, formId, rules) {
    const base = "https://pm.officeally.com/emr/PatientCharts/";
    const p = encodeURIComponent(String(pid || "").replace(/\D/g, ""));
    const rule = (rules || REQUIRED_LAYOUT)[String(formId || "")];
    return {
      progressNotes: base + "PatientChart_ProgressNotes.aspx?PageAction=ProgressNotes,PatientCharts_ProgressNotes_Add&Tab=C&PID=" + p + "&Scope=&Date1=&Date2=",
      addNote: rule ? base + "PatientChart_EditNote.aspx?PageAction=AddNote&SoapLayoutID=" + rule.ids[0] + "&Tab=C&PID=" + p + "&Scope=&Date1=&Date2=" : "",
    };
  }

  // HARD rule: the wrong layout is never overridden and never filled into. Returns { ok, reason }.
  // Manage Office settings from Cadence ({ formId: { id, name } }) → layout rules. The practice's
  // own values replace the built-in defaults entirely; a note type with no saved layout has no rule.
  function layoutRulesFrom(layouts) {
    if (!layouts || typeof layouts !== "object") return null;
    const out = {};
    Object.keys(layouts).forEach(function (formId) {
      const row = layouts[formId] || {};
      const id = String(row.id || "").trim();
      if (!id) return;
      const name = String(row.name || "").trim();
      out[formId] = { label: name || ("layout " + id), ids: [id], names: name ? [norm(name)] : [] };
    });
    return out;
  }

  function checkLayout(formId, layoutId, layoutName, rules) {
    const rule = (rules || REQUIRED_LAYOUT)[String(formId || "")];
    if (!rule) return { ok: true, reason: "" };
    if (!layoutId && !layoutName) return { ok: true, reason: "not an Office Ally note page" };
    const name = norm(layoutName);
    if (rule.ids.indexOf(String(layoutId || "")) !== -1 || rule.names.indexOf(name) !== -1) return { ok: true, reason: "" };
    return { ok: false, reason: "Template mismatch: this Cadence note must go into the Office Ally layout \"" +
      rule.label + "\", but this page is \"" + (layoutName || layoutId) + "\". Nothing was filled. " +
      "Change the SOAP Note Layout to \"" + rule.label + "\" in Office Ally, then click Fill again." };
  }

  function pad2(n) { return (n < 10 ? "0" : "") + n; }

  // The date a Cadence note belongs to, as MM/DD/YYYY in the clinician's local time zone.
  // Cadence stores only when the note was SAVED (created_at, UTC), so a note saved the day after
  // the visit carries the later date — the rule doc says so.
  function noteDate(createdAt) {
    const d = createdAt ? new Date(createdAt) : null;
    if (!d || isNaN(d)) return "";
    return pad2(d.getMonth() + 1) + "/" + pad2(d.getDate()) + "/" + d.getFullYear();
  }

  // The visit day a Cadence note documents, MM/DD/YYYY: its saved visit_date (YYYY-MM-DD), or for
  // a note saved before visit dates existed, the local date it was saved.
  function visitDateOf(note) {
    const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String((note && note.visit_date) || ""));
    return m ? m[2] + "/" + m[3] + "/" + m[1] : noteDate(note && note.created_at);
  }

  // Is this Office Ally note form a brand-new encounter (Add Note) rather than an existing one?
  // Only a new encounter's date may be set by Cadence: its date is just Office Ally's default
  // (today), whereas changing an existing encounter's date would re-date a clinical record.
  function isNewEncounter(href, titleText) {
    return /[?&]PageAction=AddNote\b/i.test(String(href || "")) || /^\s*Add Note\b/i.test(String(titleText || ""));
  }

  // Normalise "9/28/2026", "09/28/2026" or {month, day, year} to MM/DD/YYYY ("" if unusable).
  function mdy(v) {
    let m, d, y;
    if (v && typeof v === "object") { m = v.month; d = v.day; y = v.year; }
    else {
      const x = /^\s*(\d{1,2})\/(\d{1,2})\/(\d{4})\s*$/.exec(String(v || ""));
      if (!x) return "";
      m = x[1]; d = x[2]; y = x[3];
    }
    m = parseInt(m, 10); d = parseInt(d, 10); y = parseInt(y, 10);
    if (!(m >= 1 && m <= 12 && d >= 1 && d <= 31 && y > 1900)) return "";
    return pad2(m) + "/" + pad2(d) + "/" + y;
  }

  // HARD rule: the Office Ally encounter's date must equal the Cadence note's date.
  function checkEncounterDate(cadenceDate, pageDate) {
    const c = mdy(cadenceDate), p = mdy(pageDate);
    if (!p) return { ok: true, reason: "not an Office Ally note page" };
    if (!c) return { ok: false, reason: "This Cadence note has no date, so it cannot be matched to an Office Ally encounter. Nothing was filled." };
    if (c === p) return { ok: true, reason: "" };
    return { ok: false, reason: "Date mismatch: the Cadence note is dated " + c + " but this Office Ally encounter is dated " +
      p + ". Nothing was filled. Open the encounter dated " + c + " (or create it), then click Fill again." };
  }

  // Office Ally's encounter list, read from its own page HTML: every table row that links to an
  // encounter (EID=…) and carries a date. The first date in the row is taken as the encounter
  // date. Returns [{ eid, date }] with duplicates removed.
  function parseEncounters(html) {
    const out = [], seen = {};
    String(html || "").split(/<tr[\s>]/i).slice(1).forEach(function (row) {
      const idm = /(?:\bEID|EncounterID)\s*=\s*['"]?(\d{5,})/i.exec(row);
      if (!idm) return;
      const text = row.replace(/<[^>]*>/g, " ");
      const dm = /\b(\d{1,2}\/\d{1,2}\/\d{4})\b/.exec(text);
      if (!dm || seen[idm[1]]) return;
      seen[idm[1]] = true;
      out.push({ eid: idm[1], date: mdy(dm[1]) });
    });
    return out;
  }

  // HARD rule: at most one encounter per patient per day. Returns
  //   { ok: true }                          no other encounter on that date
  //   { ok: false, block: true, reason }    another encounter exists on that date
  //   { ok: false, block: false, reason }   the list could not be read — clinician must check
  function checkSameDayEncounters(encounters, date, currentEid) {
    const day = mdy(date);
    if (encounters == null) {
      return { ok: false, block: false, reason: "Couldn't read this patient's encounter list from Office Ally, so Cadence cannot confirm there is only one encounter on " + day + ". Check the Encounters list yourself, then click Fill again." };
    }
    if (!encounters.length) {
      return { ok: false, block: false, reason: "No encounters were found in Office Ally's list to compare with. Check the Encounters list for another note on " + day + ", then click Fill again." };
    }
    const others = encounters.filter(function (e) { return e.date === day && String(e.eid) !== String(currentEid || ""); });
    if (!others.length) return { ok: true, reason: "" };
    return { ok: false, block: true, reason: "Duplicate encounter: Office Ally already has encounter " +
      others.map(function (e) { return e.eid; }).join(", ") + " on " + day +
      (currentEid ? " besides this one (" + currentEid + ")" : "") +
      ". Only one encounter per patient per day is allowed. Delete the older encounter in Office Ally, then retry. Nothing was filled." };
  }

  // Does the note type suit the open Office Ally layout? Advisory only — a practice may name its
  // layouts anything — so this returns a warning string, never a block.
  function layoutWarning(formId, layoutName) {
    const name = norm(layoutName);
    if (!name) return "";
    const isEvalLayout = /eval/.test(name);
    const isDailyLayout = /progress|daily/.test(name);
    const isEvalNote = /^initial/.test(String(formId || "")) || /eval/.test(String(formId || ""));
    if (isEvalNote && isDailyLayout) return "This is an evaluation note but the Office Ally layout is \"" + layoutName + "\". Switch the layout to your evaluation layout first?";
    if (!isEvalNote && isEvalLayout) return "This is a daily/follow-up note but the Office Ally layout is \"" + layoutName + "\". Switch the layout to Progress Notes first?";
    return "";
  }

  // ---- Where is the panel open, and is Office Ally still logged in? ----

  const LOGIN_HINT = /auth0bridge|logon|login|signin|sign-in/i;

  // "practice" (the local practice page), "login" (an Office Ally sign-in page),
  // "officeally" (a logged-in Office Ally page), or "other" (anything else — never filled).
  function pageKind(hostname, pathname, hasPasswordField) {
    const host = String(hostname || "").toLowerCase();
    if (host === "localhost" || host === "127.0.0.1") return "practice";
    if (!/(^|\.)officeally\.com$/.test(host)) return "other";
    if (hasPasswordField || LOGIN_HINT.test(String(pathname || ""))) return "login";
    return "officeally";
  }

  // Did a request made in the clinician's Office Ally session come back as the sign-in page?
  // Office Ally redirects an expired session to its auth0 bridge / logon page.
  // Judged by WHERE the answer came from (the sign-in server) or a password box — never by words in
  // the page: every logged-in Office Ally page carries a keep-alive script naming the
  // ".../auth0bridge/Logon/CleanLogon" URL, and matching on that text flagged every page as logged out.
  function looksLoggedOut(finalUrl, html) {
    if (LOGIN_HINT.test(String(finalUrl || ""))) return true;
    return /<input[^>]+type=["']?password/i.test(String(html || ""));
  }

  // Unresolved gap markers must not go into a chart unnoticed.
  function countGaps(sections) {
    return (sections || []).reduce(function (n, s) {
      return n + ((String(s.body || s.text || "").match(/\[\[NEEDS:|\[!\s/g) || []).length);
    }, 0);
  }

  // ---- Did it really land? ----

  // Office Ally hands text back with CRLF newlines and may trim the ends, so compare on those terms.
  function sameText(a, b) {
    const n = (s) => String(s || "").replace(/\r\n?/g, "\n").replace(/[ \t]+\n/g, "\n").trim();
    return n(a) === n(b);
  }

  // Compare what routing planned for each box with what the page's box holds now.
  // planBoxes: [{ key, label, text }]; current: { key: value } read from the page.
  // Returns { matched, differ, empty } — each a list of box labels — and ok (every box matches).
  function verifyBoxes(planBoxes, current) {
    const out = { matched: [], differ: [], empty: [], ok: false };
    (planBoxes || []).forEach(function (b) {
      const has = current && Object.prototype.hasOwnProperty.call(current, b.key) ? current[b.key] : null;
      if (has == null || !String(has).trim()) out.empty.push(b.label || b.key);
      else if (sameText(has, b.text)) out.matched.push(b.label || b.key);
      else out.differ.push(b.label || b.key);
    });
    out.ok = out.matched.length > 0 && !out.differ.length && !out.empty.length;
    return out;
  }

  return {
    sameText: sameText,
    verifyBoxes: verifyBoxes,
    FIELD_PREFIX: FIELD_PREFIX,
    DEFAULT_LABELS: DEFAULT_LABELS,
    conceptFor: conceptFor,
    keyFromId: keyFromId,
    bucketOfKey: bucketOfKey,
    oaLength: oaLength,
    splitAtBoundaries: splitAtBoundaries,
    planRouting: planRouting,
    checkPatient: checkPatient,
    layoutWarning: layoutWarning,
    REQUIRED_LAYOUT: REQUIRED_LAYOUT,
    officeAllyUrls: officeAllyUrls,
    layoutRulesFrom: layoutRulesFrom,
    pageKind: pageKind,
    looksLoggedOut: looksLoggedOut,
    checkLayout: checkLayout,
    noteDate: noteDate,
    visitDateOf: visitDateOf,
    isNewEncounter: isNewEncounter,
    mdy: mdy,
    checkEncounterDate: checkEncounterDate,
    parseEncounters: parseEncounters,
    checkSameDayEncounters: checkSameDayEncounters,
    countGaps: countGaps,
  };
});
