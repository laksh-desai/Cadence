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
  const BUCKET_FALLBACK = {
    S: ["S_HOPI_Original", "S_MedicalHistory"],
    O: ["O_Objective", "O_PE_Musculoskeletal"],
    A: ["A_Custom1", "A_Custom2"],
    P: ["P_Plans", "P_Custom3"],
  };

  // Concepts, checked IN ORDER against the Cadence heading (first match wins, so specific phrases
  // come before general ones: "functional status" before "status", "short-term goal" before
  // "goal", treatment names before "exercise"). `labels` are the words that mark an Office Ally box
  // as meant for this concept; they are matched against box LABELS only, never against the
  // section heading, so "Therapeutic Exercise" cannot be routed into "Exercises (Continue)".
  const CONCEPTS = [
    { id: "chief_complaint", match: ["chief complaint", "complaint"], bucket: "S",
      keys: ["S_ChiefComplaint"], labels: ["chief complaint", "complaint"] },
    { id: "narrative", match: ["summary of daily", "present illness", "subjective"], bucket: "S",
      keys: ["S_HOPI_Original"], labels: ["present illness", "subjective"] },
    { id: "diagnosis", match: ["diagnos"], bucket: "A",
      keys: ["A_Custom1"], labels: ["diagnos"] },
    { id: "medications", match: ["medication"], bucket: "S",
      keys: ["S_Medications", "S_MedicalHistory"], labels: ["medication"] },
    { id: "allergies", match: ["allerg"], bucket: "S",
      keys: ["S_Allergies", "S_MedicalHistory"], labels: ["allerg"] },
    { id: "social", match: ["social history", "living environment", "social"], bucket: "S",
      keys: ["S_SocialHistory"], labels: ["social", "living"] },
    { id: "history", match: ["referral", "history", "precaution", "prior level"], bucket: "S",
      keys: ["S_MedicalHistory", "S_HOPI_Original"], labels: ["medical history", "history", "precaution"] },
    { id: "treatment", bucket: "O",
      match: ["therapeutic exercise", "therapeutic activit", "neuromuscular", "gait training",
        "manual therapy", "self-care", "home management", "ultrasound", "electrical stim", "e-stim",
        "traction", "massage", "modalit", "intervention", "treatment performed"],
      keys: ["P_Procedures", "O_Objective"], labels: ["procedure", "intervention", "treatment"] },
    { id: "functional", match: ["functional status", "functional mobility", "function"], bucket: "O",
      keys: ["O_FunctionalStatus", "O_Objective"], labels: ["functional"] },
    // Before "assessment": a heading like "Musculoskeletal Assessment" is exam findings (Objective),
    // not the clinical assessment.
    { id: "musculoskeletal", match: ["musculoskeletal", "range of motion", "strength", "mmt"], bucket: "O",
      keys: ["O_Objective", "O_PE_Musculoskeletal"], labels: ["objective", "musculoskeletal"] },
    { id: "short_goals", match: ["short-term goal", "short term goal"], bucket: "P",
      keys: ["P_GoalNotes", "P_Custom1"], labels: ["goal"] },
    { id: "long_goals", match: ["long-term goal", "long term goal", "goal"], bucket: "P",
      keys: ["P_GoalNotes", "P_Custom1"], labels: ["goal"] },
    { id: "assessment", bucket: "A",
      match: ["assessment", "impression", "clinical complexity", "rehab potential", "prognosis",
        "response to treatment", "justification"],
      keys: ["A_Custom1", "A_Custom2"], labels: ["assessment"] },
    { id: "home_program", match: ["home exercise", "home program", "hep"], bucket: "P",
      keys: ["P_PatientInstructions", "P_Custom2"], labels: ["instruction", "home", "exercise"] },
    { id: "plan", match: ["plan", "recommendation", "discharge", "next visit", "frequency"], bucket: "P",
      keys: ["P_Plans", "P_Custom3"], labels: ["plan", "next step"] },
    { id: "objective", bucket: "O",
      match: ["objective", "fall risk", "other systems", "cardiopulmonary", "vital", "pain",
        "coordination", "sensation", "edema", "posture", "special test", "outcome"],
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
  function keyFromId(id) {
    const s = String(id || "");
    if (s.indexOf(FIELD_PREFIX) !== 0) return null;
    const key = s.slice(FIELD_PREFIX.length);
    return /^[SOAP]_[A-Za-z0-9_]+$/.test(key) ? key : null;
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
    fields.forEach(function (f) {
      const l = norm(f.label);
      if (bucketOfKey(f.key) === concept.bucket && concept.labels.some(function (w) { return l.indexOf(w) !== -1; })) push(f);
    });
    // 2. The concept's preferred built-in boxes.
    concept.keys.forEach(function (k) { push(byKey[k]); });
    // 3. The general boxes of the section's SOAP bucket.
    (BUCKET_FALLBACK[concept.bucket] || []).forEach(function (k) { push(byKey[k]); });
    return out;
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

      // Too long for any box whole: split at boundaries across the candidates, in order. The
      // limit leaves room for the "Heading (cont.):" line so every part still fits once labelled.
      const limit = Math.min.apply(null, cands.map(function (c) { return c.maxLen; })) - oaLength(heading + " (cont.):\n\n\n");
      const parts = splitAtBoundaries(body, limit);
      if (!parts) { unplaced.push({ heading: heading, reason: "a single sentence is longer than an Office Ally box" }); return; }
      const placed = [];
      let ci = 0;
      for (let p = 0; p < parts.length; p++) {
        const h = p === 0 ? heading : heading + " (cont.)";
        while (ci < cands.length && !fits(boxFor(cands[ci]), h, parts[p])) ci++;
        if (ci >= cands.length) break;
        placed.push({ box: boxFor(cands[ci]), block: { heading: h, body: parts[p] } });
        ci++;
      }
      if (placed.length !== parts.length) {
        unplaced.push({ heading: heading, reason: "longer than the room left in its Office Ally boxes" });
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

  // Unresolved gap markers must not go into a chart unnoticed.
  function countGaps(sections) {
    return (sections || []).reduce(function (n, s) {
      return n + ((String(s.body || s.text || "").match(/\[\[NEEDS:|\[!\s/g) || []).length);
    }, 0);
  }

  return {
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
    countGaps: countGaps,
  };
});
