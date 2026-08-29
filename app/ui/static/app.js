(function(){
  // ---------- API ----------
  async function getForms(){ const r=await fetch("/api/forms"); return r.json(); }
  async function getPatients(){ const r=await fetch("/api/patients"); return r.json(); }
  async function getPatient(id){ const r=await fetch(`/api/patients/${id}`); return r.json(); }
  async function createPatient(payload){
    const r=await fetch("/api/patients",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(payload)});
    if(!r.ok) throw new Error("create patient failed");
    return r.json();
  }
  async function updatePatient(id, payload){
    const r=await fetch(`/api/patients/${id}`,{method:"PATCH",headers:{"Content-Type":"application/json"},body:JSON.stringify(payload)});
    if(!r.ok) throw new Error("update patient failed");
    return r.json();
  }
  async function deletePatient(id){
    const r=await fetch(`/api/patients/${id}`,{method:"DELETE"});
    if(!r.ok && r.status!==204) throw new Error("delete patient failed");
  }
  async function deleteNote(patientId, noteId){
    const r=await fetch(`/api/patients/${patientId}/notes/${noteId}`,{method:"DELETE"});
    if(!r.ok && r.status!==204) throw new Error("delete note failed");
  }
  async function getPatientNotes(id){ const r=await fetch(`/api/patients/${id}/notes`); return r.json(); }
  async function getNote(id, noteId){ const r=await fetch(`/api/patients/${id}/notes/${noteId}`); return r.json(); }
  async function transcribeAudio(blob){
    const fd=new FormData();
    fd.append("audio", blob, "dictation.wav");
    // Generous ceiling: a full-length clip (see MAX_CLIP_MS) of CPU-only MedASR
    // decoding can take a couple of minutes on the target hardware; this timeout
    // must comfortably exceed that so a slow-but-working transcription is never
    // aborted and lost.
    const r=await fetch("/api/transcribe", { method:"POST", body:fd, signal: AbortSignal.timeout(6*60*1000) });
    if(!r.ok){
      const body=await r.json().catch(()=>({}));
      throw new Error(body.detail || "Transcription failed.");
    }
    const data=await r.json();
    return data.text || "";
  }
  async function generateNote(payload){
    return fetch("/api/generate",{
      method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify(payload),
      signal: AbortSignal.timeout(30*60*1000),
    });
  }
  // Background generation queue. A note is 5-9 minutes on this hardware, so it runs on the SERVER
  // and the browser just watches: enqueue, then poll by cursor. Closing the tab, switching
  // patients, or reloading no longer kills the note.
  async function enqueueGeneration(payload){
    const r=await fetch("/api/generate/jobs",{
      method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify(payload)});
    if(!r.ok){ const b=await r.json().catch(()=>({})); throw new Error(b.detail||"Could not start the note."); }
    return r.json();
  }
  async function listJobs(){ const r=await fetch("/api/generate/jobs"); return r.ok ? r.json() : []; }
  async function tailJob(id, cursor){
    const r=await fetch(`/api/generate/jobs/${id}?cursor=${cursor|0}`);
    return r.ok ? r.json() : null;
  }
  async function cancelJob(id){ await fetch(`/api/generate/jobs/${id}`,{method:"DELETE"}); }
  // Streaming generate: reads newline-delimited JSON events from /api/generate/stream and fans them
  // out to callbacks. The note is watched live as the model writes it, so a long generation is never
  // a blank wait and is never lost to a timeout (data flows the whole time). 30-min ceiling matches
  // the server. cbs: {onStatus, onToken, onDone(result), onError(detail)}.
  async function generateStream(payload, cbs, url){
    let res;
    try{
      res = await fetch(url || "/api/generate/stream",{
        method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify(payload),
        signal: AbortSignal.timeout(30*60*1000),
      });
    }catch(_){ cbs.onError && cbs.onError("Couldn't reach the local model just now."); return; }
    if(!res.ok || !res.body){
      const b = await res.json().catch(()=>({}));
      cbs.onError && cbs.onError(b.detail || "Couldn't reach the local model just now.");
      return;
    }
    const reader = res.body.getReader(), dec = new TextDecoder();
    let buf="";
    try{
      for(;;){
        const {value, done} = await reader.read();
        if(done) break;
        buf += dec.decode(value, {stream:true});
        let nl;
        while((nl = buf.indexOf("\n")) >= 0){
          const line = buf.slice(0,nl).trim(); buf = buf.slice(nl+1);
          if(!line) continue;
          let msg; try{ msg = JSON.parse(line); }catch(_){ continue; }
          if(msg.type==="token") cbs.onToken && cbs.onToken(msg.text);
          else if(msg.type==="status") cbs.onStatus && cbs.onStatus(msg.text);
          else if(msg.type==="done") cbs.onDone && cbs.onDone(msg.result);
          else if(msg.type==="error") cbs.onError && cbs.onError(msg.detail);
        }
      }
    }catch(_){ cbs.onError && cbs.onError("The connection dropped while the note was generating."); }
  }
  async function saveNote(patientId, payload){
    return fetch(`/api/patients/${patientId}/notes`,{
      method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify(payload),
    });
  }
  async function getTemplate(id){ const r=await fetch(`/api/forms/${id}/template`); if(!r.ok) throw new Error("load template failed"); return r.json(); }
  async function createTemplate(payload){
    const r=await fetch("/api/forms",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(payload)});
    if(!r.ok){ const b=await r.json().catch(()=>({})); throw new Error(b.detail||"create template failed"); }
    return r.json();
  }
  async function saveTemplate(id, payload){
    const r=await fetch(`/api/forms/${id}/template`,{method:"PUT",headers:{"Content-Type":"application/json"},body:JSON.stringify(payload)});
    if(!r.ok){ const b=await r.json().catch(()=>({})); throw new Error(b.detail||"save template failed"); }
    return r.json();
  }
  async function duplicateTemplate(id){
    const r=await fetch(`/api/forms/${id}/duplicate`,{method:"POST"});
    if(!r.ok) throw new Error("duplicate template failed");
    return r.json();
  }
  async function resetTemplate(id){
    const r=await fetch(`/api/forms/${id}/template/reset`,{method:"POST"});
    if(!r.ok) throw new Error("reset template failed");
    return r.json();
  }
  async function deleteTemplate(id){
    const r=await fetch(`/api/forms/${id}`,{method:"DELETE"});
    if(!r.ok && r.status!==204) throw new Error("delete template failed");
  }

  // ---------- State ----------
  let FORMS_LIST=[], FORMS_BY_ID={}, PATIENTS_BY_ID={};
  let currentPatient=null, currentForm=null, priorOn=true, lastResult=null;
  let fastMode=false;  // Fast-draft model tier (smaller/faster) vs the 4B quality model

  const $ = id => document.getElementById(id);
  const dictation=$("dictation"), output=$("output");
  const overlay=$("overlay"), modalBody=$("modalBody");
  const patientSel=$("patientSel"), formSel=$("formSel");
  const priorFlag=$("priorFlag");

  // ---------- Helpers ----------
  function esc(s){ return (s||"").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;"); }
  function withGaps(s){ return esc(s)
    .replace(/\[\[NEEDS:\s*([^\]]+)\]\]/g,'<span class="gap">⌖ $1</span>')
    // A chip still carrying "— confirm" is an open question; once the clinician decides, the
    // suffix is dropped and the chip renders as settled. The marker text IS the state — there is
    // no parallel bookkeeping to fall out of sync with what the saved note actually says.
    .replace(/\[\[CPT:\s*([^\]]+)\]\]/g, (m, inner)=>
      /—\s*confirm\s*$/.test(inner)
        ? '<span class="code">CPT · '+inner+'</span>'
        : '<span class="code code-ok">✓ CPT · '+inner+'</span>'); }
  // Count the amber [[NEEDS:...]] flags (model gaps + verification-layer fabrication/verify flags)
  // sitting INSIDE section bodies, so the save hint reflects them too — a note can have
  // missing_info: none yet still carry inline flags, and "Looks complete" would then mislead.
  function countGapFlags(sections){ return (sections||[]).reduce((n,s)=>n+(((s.body||"").match(/\[\[NEEDS:/g))||[]).length,0); }
  // Pull the suggested CPT codes (with each section's stated minutes) out of the note bodies.
  // This is the FALLBACK path, used for a SAVED note (the database stores sections, not the
  // billing draft) and for a revised note. It reads markers out of the note; it deliberately
  // holds no code table of its own — the timed/untimed set lives once, in Python
  // (app/generate/cpt.py TIMED_CODES), so there is nothing here to drift out of sync with it.
  function billingCodes(sections){
    const out=[];
    (sections||[]).forEach(s=>{
      const m=/\[\[CPT:\s*([0-9A-Z]+)\s+(.+?)\s+—\s*confirm\]\]/.exec(s.body||"");
      if(!m) return;
      const mm=/Minutes:\s*(\d+)/i.exec(s.body||"") || /\b(\d{1,3})\s*minutes?\b/i.exec(s.body||"");
      out.push({code:m[1], label:m[2].trim(), minutes: mm?parseInt(mm[1],10):null});
    });
    return out;
  }
  const STATUS_LABEL={negated:"not performed today", prior_visit:"prior visit", planned:"planned",
                      home_program:"home program", uncertain:"needs confirming"};
  // The rich card: the server's deterministic draft from the DICTATION — codes, per-intervention
  // minutes, both unit methods, and the excluded lines with their reasons.
  // ---------- CPT code decisions ----------
  // `confirm_required=True` has always been true of the DATA; until now there was nowhere to
  // actually do the confirming, so every code reached Save still marked "— confirm" and the
  // decision happened in the clinician's head or in Office Ally. Each decision rewrites the
  // [[CPT: ...]] marker inside the section body, which means the NOTE is the record of what was
  // decided — nothing to persist separately, and a saved note cannot disagree with the card.
  const CPT_MARKER_RE = /\[\[CPT:\s*([^\]]+)\]\]/g;

  function codeDecision(r, code){ return (r.codeDecisions||{})[code] || {state:"pending"}; }

  function rewriteCptMarkers(sections, code, state, replacement){
    return (sections||[]).map(sec=>{
      const body=(sec.body||"").replace(CPT_MARKER_RE, (marker, inner)=>{
        if(inner.trim().indexOf(code)!==0) return marker;      // a different code's chip
        if(state==="removed" && !replacement) return "";
        const label=inner.replace(/\s*—\s*confirm\s*$/,"").replace(/^\S+\s*/,"").trim();
        if(state==="removed" && replacement){
          // A clinician-assigned code carries no table label — Cadence must not invent one for a
          // code it did not choose.
          return "[[CPT: "+replacement+" — clinician-assigned]]";
        }
        return "[[CPT: "+code+(label?" "+label:"")+"]]";       // confirmed: drop the question
      });
      // Collapse the double space a removed marker leaves mid-sentence.
      return {...sec, body: body.replace(/[ \t]{2,}/g," ").replace(/\s+$/,"")};
    });
  }

  function setCodeDecision(r, code, state, replacement){
    r.codeDecisions = r.codeDecisions || {};
    if(state==="pending"){
      // Undo has to restore the "— confirm" suffix, or an un-decided line would still read as
      // settled in the note.
      r.sections = (r.sections||[]).map(sec=>({...sec,
        body:(sec.body||"").replace(CPT_MARKER_RE,(marker,inner)=>{
          if(inner.trim().indexOf(code)!==0) return marker;
          const label=inner.replace(/\s*—\s*(confirm|clinician-assigned)\s*$/,"").replace(/^\S+\s*/,"").trim();
          return "[[CPT: "+code+(label?" "+label:"")+" — confirm]]";
        })}));
      delete r.codeDecisions[code];
    } else {
      const prev=r.codeDecisions[code];
      // Re-deciding must start from the original marker, not from a already-rewritten one.
      if(prev) setCodeDecision(r, code, "pending");
      r.codeDecisions[code]={state:state, replacement:replacement||null};
      r.sections = rewriteCptMarkers(r.sections, code, state, replacement);
    }
    renderResult(r);
  }

  function codeActionsHTML(r, code){
    const d=codeDecision(r, code);
    if(d.state==="confirmed"){
      return '<span class="bstate bstate-ok">✓ confirmed</span>'
        +'<button class="btn btn-ghost btn-sm bundo" data-code="'+esc(code)+'">Undo</button>';
    }
    if(d.state==="removed"){
      return '<span class="bstate bstate-no">removed'+(d.replacement?' → '+esc(d.replacement):'')+'</span>'
        +'<button class="btn btn-ghost btn-sm bundo" data-code="'+esc(code)+'">Undo</button>'
        +(d.replacement?'':'<span class="brepl"><input class="brepl-in" data-code="'+esc(code)
          +'" placeholder="replacement code" size="8"><button class="btn btn-ghost btn-sm brepl-go" data-code="'
          +esc(code)+'">Use</button></span>');
    }
    return '<button class="btn btn-ghost btn-sm bconfirm" data-code="'+esc(code)+'">Confirm</button>'
      +'<button class="btn btn-ghost btn-sm bremove" data-code="'+esc(code)+'">Remove</button>';
  }

  function billingDraftHTML(b, r){
    const billable=(b.interventions||[]).filter(x=>x.status==="performed");
    const excluded=(b.interventions||[]).filter(x=>x.status!=="performed");
    const icd=b.icd_candidates||[];
    if(!billable.length && !excluded.length && !icd.length) return "";
    const codeList=billable.map(c=>c.code).concat(icd.map(c=>c.code)).join(", ");
    const undecided = r ? billable.filter(c=>codeDecision(r,c.code).state==="pending").length : 0;
    let h='<div class="billing"><h3>Billing draft <span class="bhint">— '
      +(r ? (undecided ? undecided+' code'+(undecided===1?'':'s')+' still to confirm' : 'all codes decided')
          : 'confirm every line before submitting')
      +'</span> '
      +(r && undecided ? '<button class="btn btn-ghost btn-sm bconfirm-all">Confirm all</button> ' : '')
      +'<button class="btn btn-ghost btn-sm copy-codes" data-codes="'+esc(codeList)+'">Copy codes</button></h3>';

    if(icd.length){
      h+='<p class="bsub">Diagnosis (ICD-10)</p><ul>';
      icd.forEach(c=>{
        h+='<li><span class="bcode">'+esc(c.code)+'</span> '+esc(c.label)
          +(c.laterality_stated?'':' <span class="bwarn">side not stated</span>')
          +'<span class="bcue">“'+esc(c.cue)+'”</span></li>';
      });
      h+='</ul>';
    }
    if(billable.length){
      h+='<p class="bsub">Treatments performed</p><ul>';
      billable.forEach(c=>{
        const st = r ? codeDecision(r, c.code).state : "pending";
        h+='<li class="bline bline-'+st+'"><span class="bcode">'+esc(c.code)+'</span> '+esc(c.label)
          +' <span class="bmin">('+(c.timed?'timed':'untimed')
          +(c.minutes!=null?' · '+c.minutes+' min':'; minutes not stated')+')</span>'
          +'<span class="bcue">“'+esc(c.cue)+'”</span>'
          +(r?'<span class="bacts">'+codeActionsHTML(r, c.code)+'</span>':'')
          +'</li>';
      });
      h+='</ul>';
    }
    if(b.units){
      h+='<p class="bunits"><b>'+b.total_timed_minutes+' timed min</b> → <b>'+b.units.total_units
        +(b.units.total_units===1?' unit':' units')+'</b> <span class="bhint">(CMS substitution)</span>';
      // Two payer rules genuinely disagree; showing one number would be picking a side.
      if(b.units_alt && b.units_alt.total_units!==b.units.total_units){
        h+='<br><span class="bwarn">AMA rule of eights gives '+b.units_alt.total_units
          +(b.units_alt.total_units===1?' unit':' units')+' — payers differ; the biller decides.</span>';
      }
      if(b.units.ambiguous) h+='<br><span class="bwarn">'+esc(b.units.note)+'</span>';
      h+='</p>';
    }
    if(excluded.length){
      h+='<p class="bsub">Mentioned but not billed</p><ul class="bexcl">';
      excluded.forEach(c=>{
        // Minutes are shown on an unbilled line too. An "uncertain" line is one Cadence found a
        // duration for but wouldn't name a code for on its own authority — the clinician needs to
        // see what confirming it would add, not just that something was skipped.
        h+='<li><span class="bcode">'+esc(c.code)+'</span> '+esc(c.label)
          +' <span class="bwarn">'+esc(STATUS_LABEL[c.status]||c.status)+'</span>'
          +(c.minutes!=null?' <span class="bmin">· '+c.minutes+' min if confirmed</span>':'')
          +'<span class="bcue">“'+esc(c.cue)+'”</span></li>';
      });
      h+='</ul>';
      // What the unit count becomes if every unconfirmed-but-timed line is accepted. The
      // arithmetic is done SERVER-side (billing.units_if_confirmed) and only rendered here — the
      // 8-minute rule must live in exactly one place, which is why the timed-code set was moved
      // out of this file too.
      const ifc=b.units_if_confirmed;
      if(ifc && b.units && ifc.total_units!==b.units.total_units){
        const add=ifc.total_timed_minutes-b.total_timed_minutes;
        h+='<p class="bwarn" style="margin:6px 0 0;font-size:12.5px">Confirming the lines above'
          +' would add '+add+' timed min → <b>'+ifc.total_units
          +(ifc.total_units===1?' unit':' units')+'</b> instead of '+b.units.total_units+'.</p>';
      }
    }
    (b.conflicts||[]).forEach(c=>{
      h+='<p class="bconflict'+(c.severity==="high"?' bconflict-hi':'')+'">'+esc(c.detail)+'</p>';
    });
    (b.missing||[]).forEach(m=>{ h+='<p class="bmissing">⌖ '+esc(m)+'</p>'; });
    return h+'<p class="bnote">Read from what you dictated, then mapped to codes from a fixed table — Cadence never writes a code of its own. Confirm or change every code and every duration; units and modifiers are the biller\'s call.</p></div>';
  }
  // Consolidated billing block. Prefers the server draft; falls back to the note\'s own CPT chips
  // for a saved note, where only the sections were persisted.
  function billingHTML(sections, billing, resultForCodes){
    if(billing) return billingDraftHTML(billing, resultForCodes);
    const codes=billingCodes(sections);
    if(!codes.length) return "";
    const codeList=codes.map(c=>c.code).join(", ");
    let h='<div class="billing"><h3>Suggested billing codes <span class="bhint">— confirm before submitting</span> <button class="btn btn-ghost btn-sm copy-codes" data-codes="'+esc(codeList)+'">Copy codes</button></h3><ul>';
    codes.forEach(c=>{ h+='<li><span class="bcode">'+esc(c.code)+'</span> '+esc(c.label)+(c.minutes!=null?' <span class="bmin">· '+c.minutes+' min</span>':'')+'</li>'; });
    return h+'</ul><p class="bnote">Deterministic suggestions from the stated interventions — confirm each code, and apply units / the 8-minute rule / modifiers per payer rules.</p></div>';
  }
  // Render the inline [[...]] markers as readable bracketed text for a plain-text copy (so a note
  // pasted into an EHR carries its flags/codes legibly instead of raw double-bracket syntax).
  function markerToText(body){
    return (body||"")
      .replace(/\[\[NEEDS:\s*([^\]]+)\]\]/g, "[! $1]")
      .replace(/\[\[CPT:\s*([^\]]+?)\s*—\s*confirm\]\]/g, "[CPT: $1]");
  }
  // Build the finished note as clean plain text — for the "Copy note" button (paste into the EHR).
  function noteToText(r){
    const p=PATIENTS_BY_ID[r.patientId]||PATIENTS_BY_ID[currentPatient];
    let t=(r.formName||"Note")+"\n"+((p&&p.name)||"")+" · "+fmtDate(r.date)+"\n\n";
    (r.sections||[]).forEach(s=>{ t+=s.heading+"\n"+markerToText(s.body).trim()+"\n\n"; });
    const b=r.billing;
    if(b){
      const billable=(b.interventions||[]).filter(x=>x.status==="performed");
      (b.icd_candidates||[]).forEach(c=>{
        if(!t.includes("Billing draft")) t+="Billing draft (confirm every line before submitting):\n";
        t+="  ICD-10 "+c.code+" "+c.label+(c.laterality_stated?"":" [side not stated]")+"\n";
      });
      if(billable.length && !t.includes("Billing draft")) t+="Billing draft (confirm every line before submitting):\n";
      billable.forEach(c=>{
        t+="  "+c.code+" "+c.label+" ("+(c.timed?"timed":"untimed")
          +(c.minutes!=null?" — "+c.minutes+" min":"; minutes not stated")+")\n";
      });
      if(b.units){
        t+="  Total timed: "+b.total_timed_minutes+" min = "+b.units.total_units+" unit(s) (CMS)";
        if(b.units_alt && b.units_alt.total_units!==b.units.total_units){
          t+="; "+b.units_alt.total_units+" unit(s) (AMA rule of eights) — payers differ";
        }
        t+="\n";
      }
    } else {
      const codes=billingCodes(r.sections);
      if(codes.length){
        t+="Suggested billing codes (confirm before submitting):\n";
        codes.forEach(c=>{ t+="  "+c.code+" "+c.label+(c.minutes!=null?" — "+c.minutes+" min":"")+"\n"; });
      }
    }
    return t.trim()+"\n";
  }
  // ---------- Copy for Office Ally (group the field-per-section note into the 4 SOAP fields) ----------
  // Office Ally partitions a note into Subjective / Objective / Assessment / Plan. The note is
  // generated one section per field; this maps each section's heading to a SOAP block so the
  // clinician can copy one block straight into each Office Ally field. Best-effort by keyword
  // (the clinician reviews before pasting) — most specific phrases first so e.g. "Patient Goals"
  // (subjective) and "Functional Mobility" (objective) don't get mis-bucketed by a generic word.
  const SOAP_LABELS = {S:"Subjective", O:"Objective", A:"Assessment", P:"Plan"};
  const SOAP_RULES = [
    // Subjective — history / patient-reported / visit context.
    ["chief complaint","S"],["history of present","S"],["summary of daily","S"],
    ["social history","S"],["living environment","S"],["referral","S"],["precaution","S"],
    ["medication","S"],["allerg","S"],["patient goal","S"],["subjective","S"],["complaint","S"],
    // Plan — targets + next steps (checked before the objective/assessment generics).
    ["short-term goal","P"],["long-term goal","P"],["plan","P"],["recommendation","P"],
    ["home program","P"],["hep","P"],["goal","P"],
    // Disambiguators — headings that contain a generic word but belong elsewhere. These MUST come
    // before the generic "assessment" / "treatment" / "functional"/"mobility" rules below, e.g.
    // "Musculoskeletal Assessment" is Objective, "Response to Treatment" is Assessment.
    ["response to treatment","A"],["functional status","A"],
    ["functional mobility","O"],["objective summary","O"],["musculoskeletal","O"],
    // Objective — exam findings + treatments / modalities.
    ["range of motion","O"],["strength","O"],["mmt","O"],["gait","O"],["mobility","O"],
    ["vitals","O"],["cardiopulmonary","O"],["pain","O"],["fall risk","O"],["other systems","O"],
    ["coordination","O"],["sensation","O"],["edema","O"],["observation","O"],["posture","O"],
    ["special test","O"],["outcome","O"],
    ["therapeutic exercise","O"],["gait training","O"],["manual therapy","O"],["neuromuscular","O"],
    ["therapeutic activit","O"],["ultrasound","O"],["e-stim","O"],["electrical stim","O"],
    ["massage","O"],["traction","O"],["modalit","O"],["minutes","O"],["treatment","O"],
    // Assessment — clinical judgment (generic, last, so the specifics above win).
    ["assessment","A"],["diagnos","A"],["impression","A"],["rehab potential","A"],
    ["prognosis","A"],["justification","A"],["skilled service","A"],["clinical complexity","A"],
  ];
  function soapBlockFor(heading){
    const h=(heading||"").toLowerCase();
    for(const [kw,blk] of SOAP_RULES){ if(h.indexOf(kw)!==-1) return blk; }
    return "O"; // unmatched clinical content defaults to Objective
  }
  function soapGroups(sections){
    const g={S:[],O:[],A:[],P:[]};
    (sections||[]).forEach(s=>{ g[soapBlockFor(s.heading)].push(s); });
    return g;
  }
  function soapBlockText(secs){
    return (secs||[]).map(s=> s.heading+"\n"+markerToText(s.body).trim()).join("\n\n").trim();
  }
  function officeAllyHTML(sections){
    const g=soapGroups(sections);
    let h='<div class="oa"><h3>Copy for Office Ally <span class="oa-hint">— one block per SOAP field</span></h3><div class="oa-row">';
    ["S","O","A","P"].forEach(k=>{
      const n=g[k].length, dis=n?"":" disabled";
      h+='<button class="btn btn-ghost btn-sm oa-copy" data-soap="'+k+'"'+dis+'>Copy '+SOAP_LABELS[k]+' <span class="oa-n">'+n+'</span></button>';
    });
    return h+'</div></div>';
  }
  function wireOfficeAlly(container, sections){
    const g=soapGroups(sections);
    Array.prototype.forEach.call(container.querySelectorAll(".oa-copy"), b=>{
      if(b.disabled) return;
      b.addEventListener("click", async ()=>{
        try{ await navigator.clipboard.writeText(soapBlockText(g[b.dataset.soap])); toast(SOAP_LABELS[b.dataset.soap]+" copied for Office Ally."); }
        catch(_){ toast("Couldn't copy — select the note text manually."); }
      });
    });
  }

  function firstName(n){ return (n||"").trim().split(/\s+/)[0]||n; }
  function initialsOf(n){ return (n||"").trim().split(/\s+/).slice(0,2).map(w=>w[0]?w[0].toUpperCase():"").join("")||"PT"; }
  function fmtDate(d){ const x=d?new Date(d):new Date(); return isNaN(x)?"":x.toLocaleDateString(); }
  function fmtDateTime(d){ const x=d?new Date(d):new Date(); if(isNaN(x)) return ""; return x.toLocaleDateString()+" "+x.toLocaleTimeString([], {hour:"2-digit",minute:"2-digit"}); }
  function buildSub(p){
    const parts=[];
    if(p.mrn) parts.push("MRN "+p.mrn);
    if(p.dob) parts.push("DOB "+p.dob);
    if(p.condition) parts.push(p.condition);
    return parts.join(" · ") || "—";
  }

  // ---------- Data loading ----------
  async function loadForms(){
    FORMS_LIST = await getForms();
    FORMS_BY_ID = {};
    FORMS_LIST.forEach(f=>{ FORMS_BY_ID[f.id]=f; });
  }
  async function loadPatients(){
    const list = await getPatients();
    PATIENTS_BY_ID = {};
    list.forEach(p=>{ PATIENTS_BY_ID[p.id] = Object.assign({}, p, {sub: buildSub(p)}); });
    return list;
  }
  async function refreshCurrentPatient(){
    if(!currentPatient) return;
    const p = await getPatient(currentPatient);
    PATIENTS_BY_ID[currentPatient] = Object.assign({}, p, {sub: buildSub(p)});
  }

  function populatePatientSelect(){
    patientSel.innerHTML="";
    Object.values(PATIENTS_BY_ID).forEach(p=>{
      const o=document.createElement("option");
      o.value=p.id; o.textContent=p.name+(p.note_count===0?" (new)":"");
      patientSel.appendChild(o);
    });
    if(currentPatient) patientSel.value=currentPatient;
  }
  function populateFormSelect(){
    formSel.innerHTML="";
    FORMS_LIST.forEach(f=>{ const o=document.createElement("option"); o.value=f.id; o.textContent=f.name; formSel.appendChild(o); });
    if(currentForm) formSel.value=currentForm;
  }

  patientSel.addEventListener("change", ()=>{ currentPatient=patientSel.value; onPatientChange(); });
  formSel.addEventListener("change", ()=>{ currentForm=formSel.value; onFormChange(); });

  function setHasPatient(has){
    $("generateBtn").disabled = !has;
    $("micBtn").disabled = $("micBtn").disabled || !has;
    dictation.disabled = !has;
    $("editPatientBtn").disabled = !has;
    $("filesBtn").disabled = !has;
    const mg=$("modeGuided"); if(mg) mg.disabled = !has;
    if(!has && guidedMode) setMode("free");
  }

  async function onPatientChange(){
    const p=PATIENTS_BY_ID[currentPatient];
    if(!p){ setHasPatient(false); return; }
    setHasPatient(true);
    $("pAvatar").textContent=initialsOf(p.name);
    $("pName").innerHTML=esc(p.name)+(p.note_count===0?' <span class="fake-tag">· new patient</span>':"");
    $("pSub").textContent=p.sub;
    priorOn=!!p.has_prior;
    // Stop tailing whatever note was writing into this pane. The JOB keeps running (that is the
    // point of the queue) but streaming patient A's note into a view headed by patient B is
    // exactly how a note gets reviewed against the wrong chart.
    detachJob();
    dictation.value="";
    // New patient loaded = fresh session: reset any in-progress guided walkthrough.
    guidedResetFor(FORMS_BY_ID[currentForm]);
    if(guidedMode) renderGuidedStep();
    resetOutput();
    renderPriorFlag();
    updateFilesButton();
  }
  function onFormChange(){
    const form=FORMS_BY_ID[currentForm];
    if(!form) return;
    $("formHint").textContent="Building: "+form.name+" · "+(form.mode==="require"?"all applicable fields required":"includes only what you mention");
    updateGuidedAvailability(form);
    // Changing note type mid-walkthrough restarts the guided flow for the new form.
    if(guidedMode){ guidedResetFor(form); renderGuidedStep(); }
    resetOutput();
    renderPriorFlag();
  }

  // ---------- Guided section-by-section dictation ----------
  // Walks the clinician through the selected form one real section at a time, each
  // with a concrete example, capturing voice or text per section. It is purely an
  // INPUT AID: on finish it assembles a labeled summary into the free dictation box
  // and hands off to the same /api/generate pipeline — the model still does all the
  // structuring, and the after-generate gap-flagging still catches anything skipped.
  // The per-form steps come from each template's `steps:` frontmatter (form.steps).
  let guidedMode=false;    // whether the guided view is showing
  let guidedFormId=null;   // form the current walkthrough belongs to
  let guidedSteps=[];      // steps for guidedFormId
  let guidedAnswers=[];    // answers, parallel to guidedSteps
  let guidedIndex=0;
  let guidedBuilt=false;   // guided DOM constructed once, then reused across steps

  function guidedResetFor(form){
    guidedFormId = form ? form.id : null;
    guidedSteps = (form && form.steps) || [];
    guidedAnswers = guidedSteps.map(()=>"");
    guidedIndex = 0;
  }

  // The guided DOM is built ONCE and its fields are updated per step (rather than
  // re-rendered), so the single #gAnswer / #gMic pair persists — setupDictation is
  // wired to them a single time and the recorder always targets the live textarea.
  function buildGuidedView(){
    const v=$("guidedView");
    v.innerHTML=
      '<div class="gstep-top"><span class="gstep-count" id="gCount"></span><div class="gprogress"><span id="gProgress"></span></div></div>'+
      '<div class="gstep-label"><span id="gLabel"></span><span class="gopt hidden" id="gOpt">optional</span></div>'+
      '<div class="gstep-eg"><span class="gstep-eg-tag">For example</span><span id="gEgText"></span></div>'+
      '<div class="gbar"><button class="btn btn-mic" id="gMic"><span class="pulse"></span><span id="gMicLabel">Dictate</span></button><button class="btn btn-ghost" id="gClear">Clear</button></div>'+
      '<textarea id="gAnswer" placeholder="Speak or type just this part — or Skip it."></textarea>'+
      '<p class="mic-help-sm" id="gMicHelp"></p>'+
      '<div class="gnav"><button class="btn btn-ghost" id="gBack">← Back</button><span class="gnav-spacer"></span><button class="btn btn-ghost" id="gSkip">Skip</button><button class="btn btn-primary" id="gNext">Next →</button></div>'+
      '<button class="gfinish" id="gFinish">Finish &amp; review everything →</button>';
    setupDictation($("gMic"), $("gAnswer"), $("gMicHelp"), $("gMicLabel"));
    $("gClear").addEventListener("click", ()=>{ if(dictationBusy) return; $("gAnswer").value=""; $("gAnswer").focus(); });
    $("gBack").addEventListener("click", ()=>guidedGo(-1));
    $("gSkip").addEventListener("click", guidedSkip);
    $("gNext").addEventListener("click", ()=>guidedGo(1));
    $("gFinish").addEventListener("click", guidedFinish);
    guidedBuilt=true;
  }

  function guidedSnapshot(){
    if(guidedIndex>=0 && guidedIndex<guidedSteps.length) guidedAnswers[guidedIndex]=($("gAnswer").value||"").trim();
  }

  function renderGuidedStep(){
    const total=guidedSteps.length, step=guidedSteps[guidedIndex];
    if(!step) return;
    const form=FORMS_BY_ID[guidedFormId];
    $("gCount").textContent=(form?form.name:"")+" · step "+(guidedIndex+1)+" of "+total;
    $("gProgress").style.width=Math.round(((guidedIndex+1)/total)*100)+"%";
    $("gLabel").textContent=step.label;
    $("gOpt").classList.toggle("hidden", !step.optional);
    $("gEgText").textContent=" "+step.example;
    $("gAnswer").value=guidedAnswers[guidedIndex]||"";
    $("gMicHelp").textContent="";
    $("gBack").disabled=(guidedIndex===0);
    const last=(guidedIndex===total-1);
    $("gNext").textContent=last?"Finish & review →":"Next →";
    $("gSkip").textContent=step.optional?"Skip":"Nothing to add";
    $("gFinish").classList.toggle("hidden", last);
  }

  function guidedBlockedIfBusy(){
    if(dictationBusy){ const h=$("gMicHelp"); if(h) h.textContent="Click Stop to finish the recording before moving on."; return true; }
    return false;
  }

  function guidedGo(dir){
    if(guidedBlockedIfBusy()) return;
    guidedSnapshot();
    const next=guidedIndex+dir;
    if(next>=guidedSteps.length){ guidedFinish(); return; }
    if(next<0) return;
    guidedIndex=next;
    renderGuidedStep();
    $("gAnswer").focus();
  }

  function guidedSkip(){
    if(guidedBlockedIfBusy()) return;
    guidedAnswers[guidedIndex]=""; // an explicit skip drops anything typed here
    if(guidedIndex>=guidedSteps.length-1){ guidedFinish(); return; }
    guidedIndex++;
    renderGuidedStep();
    $("gAnswer").focus();
  }

  function assembleGuided(){
    const lines=[];
    guidedSteps.forEach((s,i)=>{ const a=(guidedAnswers[i]||"").trim(); if(a) lines.push(s.label+": "+a); });
    return lines.join("\n");
  }

  // Compose the answered sections into the free dictation box (merging with anything
  // already there) and switch back to Free so the clinician can review/edit before
  // generating. Answers stay in state, so reopening Guided resumes where they left off.
  function guidedFinish(){
    if(guidedBlockedIfBusy()) return;
    guidedSnapshot();
    const text=assembleGuided();
    if(text) dictation.value = dictation.value.trim() ? (dictation.value.trim()+"\n"+text) : text;
    setMode("free");
    const filled=guidedAnswers.filter(a=>a && a.trim()).length;
    $("micHelp").textContent = filled
      ? "Built from your guided answers — review or add anything, then Generate. Reopen Guided to add more."
      : "Nothing captured yet — speak or type your summary, or reopen Guided to step through the form.";
    dictation.focus();
  }

  function updateGuidedAvailability(form){
    const has=!!(form && form.steps && form.steps.length);
    const mg=$("modeGuided");
    mg.disabled=!has;
    mg.style.opacity=has?"":".5";
    if(!has && guidedMode) setMode("free");
  }

  function setMode(mode){
    const wasGuided=guidedMode;
    guidedMode=(mode==="guided");
    if(wasGuided && !guidedMode && guidedBuilt) guidedSnapshot(); // don't lose the visible answer on toggle-away
    $("modeFree").classList.toggle("active", !guidedMode);
    $("modeFree").setAttribute("aria-selected", String(!guidedMode));
    $("modeGuided").classList.toggle("active", guidedMode);
    $("modeGuided").setAttribute("aria-selected", String(guidedMode));
    $("freeView").classList.toggle("hidden", guidedMode);
    $("guidedView").classList.toggle("hidden", !guidedMode);
    if(guidedMode){
      if(!guidedBuilt) buildGuidedView();
      if(guidedFormId!==currentForm) guidedResetFor(FORMS_BY_ID[currentForm]);
      renderGuidedStep();
      $("gAnswer").focus();
    }
  }

  $("modeFree").addEventListener("click", ()=>{ if(!dictationBusy) setMode("free"); });
  $("modeGuided").addEventListener("click", ()=>{
    if(dictationBusy) return;
    const form=FORMS_BY_ID[currentForm];
    if(!form || !form.steps || !form.steps.length){ toast("No guided walkthrough for this note type."); return; }
    setMode("guided");
  });
  // Model tier: Quality (MedGemma 4B) vs Fast draft (smaller/faster). The fast tier is explicitly a
  // quick first pass to edit or regenerate on Quality before signing — every note is reviewed either way.
  function setFast(on){
    fastMode=!!on;
    $("modeQuality").classList.toggle("active", !fastMode);
    $("modeQuality").setAttribute("aria-selected", String(!fastMode));
    $("modeFast").classList.toggle("active", fastMode);
    $("modeFast").setAttribute("aria-selected", String(fastMode));
    $("modelHint").textContent = fastMode ? "Faster, lower quality — a draft to refine, then regenerate on Quality before signing." : "";
  }
  $("modeQuality").addEventListener("click", ()=>setFast(false));
  $("modeFast").addEventListener("click", ()=>setFast(true));
  // Before a note is generated, the review card doubles as a live reference: it shows the
  // selected form's full outline (read-only) beside the dictation box, so the clinician can
  // read through it while speaking to make sure they cover everything. Once a note is
  // generated it's replaced by the note; Clear / changing form or patient brings it back.
  function templateReferenceHTML(form){
    if(!form || !form.spec) return '<div class="empty"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg><div>Dictate a session and generate to see the '+esc(form?form.name:"")+'.</div></div>';
    const modeDesc = form.mode==="require"
      ? "Require mode — all applicable fields expected; missing ones are flagged, never invented."
      : "Omit mode — includes only what you mention.";
    return '<div class="tpl-ref">'
      +'<div class="tpl-ref-head"><span class="tpl-ref-tag">Template</span><span class="tpl-ref-name">'+esc(form.name)+'</span></div>'
      +'<p class="tpl-ref-mode">'+esc(modeDesc)+'</p>'
      +'<pre class="tpl-outline">'+esc(form.spec)+'</pre>'
      +'<p class="tpl-ref-foot">Reference while you dictate. Edit or add outlines in the <button type="button" class="linkbtn" data-goto="templates">Templates</button> tab.</p>'
      +'</div>';
  }
  function resetOutput(){
    lastResult=null;
    output.innerHTML=templateReferenceHTML(FORMS_BY_ID[currentForm]);
  }
  function updateFilesButton(){
    const p=PATIENTS_BY_ID[currentPatient];
    $("filesBtn").textContent="Patient file ("+(p?p.note_count:0)+")";
  }

  // ---------- Prior flag ----------
  function renderPriorFlag(){
    const p=PATIENTS_BY_ID[currentPatient], form=FORMS_BY_ID[currentForm];
    if(!p || !form) return;
    priorFlag.classList.remove("hidden","disabled","off");
    if(!form.carry){ priorFlag.classList.add("hidden"); return; }
    if(!p.has_prior){ priorFlag.classList.add("off","disabled"); priorFlag.setAttribute("aria-pressed","false"); $("priorFlagText").textContent="No previous visit"; return; }
    priorFlag.classList.toggle("off", !priorOn);
    priorFlag.setAttribute("aria-pressed", String(priorOn));
    $("priorFlagText").textContent=priorOn?"Previous visit on file":"Ignore previous visit";
  }
  function togglePrior(){ const p=PATIENTS_BY_ID[currentPatient], form=FORMS_BY_ID[currentForm]; if(!form||!form.carry||!p||!p.has_prior) return; priorOn=!priorOn; renderPriorFlag(); }
  priorFlag.addEventListener("click", togglePrior);
  priorFlag.addEventListener("keydown", e=>{ if(e.key==="Enter"||e.key===" "){ e.preventDefault(); togglePrior(); }});

  // ---------- Buttons ----------
  $("clearBtn").addEventListener("click", ()=>{ dictation.value=""; dictation.focus(); });

  // ---------- Reusable dictation (local MedASR transcription) ----------
  let activeRecording=null; // whichever mic button is currently recording/transcribing
  // True from the moment recording starts until its transcription finishes. Guided
  // mode reads this to block step navigation mid-clip, so an async transcription can
  // never land its text in the wrong section's box after the user has moved on.
  let dictationBusy=false;

  // A single recording is capped at this length, then auto-stops and transcribes
  // itself. Because each finished clip is APPENDED to the field, the clinician just
  // clicks Dictate again to continue exactly where they left off -- so total
  // dictation is effectively unlimited, while no single clip grows long enough to
  // lose progress or to overload CPU-only transcription. Kept in sync with the
  // "3 minutes" copy in index.html's #micHelp and the guide panel.
  const MAX_CLIP_MS=3*60*1000;
  const WARN_CLIP_MS=25*1000; // heads-up window before auto-save
  function fmtClock(ms){ const s=Math.max(0,Math.ceil(ms/1000)); return Math.floor(s/60)+":"+String(s%60).padStart(2,"0"); }

  function encodeWav16kMono(float32Samples){
    const sampleRate=16000, numCh=1, bitsPerSample=16;
    const blockAlign=numCh*bitsPerSample/8;
    const byteRate=sampleRate*blockAlign;
    const dataSize=float32Samples.length*2;
    const buf=new ArrayBuffer(44+dataSize);
    const view=new DataView(buf);
    function writeStr(off,s){ for(let i=0;i<s.length;i++) view.setUint8(off+i, s.charCodeAt(i)); }
    writeStr(0,"RIFF"); view.setUint32(4,36+dataSize,true); writeStr(8,"WAVE");
    writeStr(12,"fmt "); view.setUint32(16,16,true); view.setUint16(20,1,true);
    view.setUint16(22,numCh,true); view.setUint32(24,sampleRate,true);
    view.setUint32(28,byteRate,true); view.setUint16(32,blockAlign,true);
    view.setUint16(34,bitsPerSample,true);
    writeStr(36,"data"); view.setUint32(40,dataSize,true);
    let off=44;
    for(let i=0;i<float32Samples.length;i++,off+=2){
      const s=Math.max(-1,Math.min(1,float32Samples[i]));
      view.setInt16(off, s<0?s*0x8000:s*0x7fff, true);
    }
    return new Blob([buf],{type:"audio/wav"});
  }

  function resampleTo16k(samples, fromRate){
    if(fromRate===16000) return samples;
    const ratio=fromRate/16000;
    const outLen=Math.floor(samples.length/ratio);
    const out=new Float32Array(outLen);
    for(let i=0;i<outLen;i++){
      const srcIdx=i*ratio, i0=Math.floor(srcIdx), frac=srcIdx-i0;
      out[i]=samples[i0]+(samples[Math.min(i0+1,samples.length-1)]-samples[i0])*frac;
    }
    return out;
  }

  function mergeFloat32(chunks){
    let total=0; chunks.forEach(c=>{ total+=c.length; });
    const out=new Float32Array(total);
    let off=0; chunks.forEach(c=>{ out.set(c, off); off+=c.length; });
    return out;
  }

  function setupDictation(btn, target, help, labelEl){
    if(!btn || !target) return;
    const idle=(labelEl && labelEl.textContent) || "Dictate";
    if(!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia){
      btn.disabled=true; btn.style.opacity=.5; btn.style.cursor="default";
      if(help) help.textContent="Voice typing isn't available in this browser — type instead.";
      return;
    }
    let state="idle"; // idle | recording | transcribing
    let rec=null; // {stream, audioCtx, processor, source, chunks}
    let clipTimer=null, clipStart=0, autoSaved=false;

    function clearClipTimer(){ if(clipTimer){ clearInterval(clipTimer); clipTimer=null; } }

    // While recording, the countdown owns the button label and the help line so the
    // clinician can always see how much of the current clip is left before it
    // auto-saves.
    function tickClip(){
      const remaining=MAX_CLIP_MS-(Date.now()-clipStart);
      if(remaining<=0){ autoSaved=true; stopAndTranscribe(); return; }
      if(labelEl) labelEl.textContent="Stop · "+fmtClock(remaining);
      if(help){
        help.textContent = remaining<=WARN_CLIP_MS
          ? "Saving this clip in "+fmtClock(remaining)+"… it'll transcribe automatically — click Dictate again to keep going."
          : "Recording — "+fmtClock(remaining)+" left on this clip. Click Stop when done, or keep talking and it saves automatically.";
      }
    }

    function setState(next){
      state=next;
      btn.classList.toggle("live", state==="recording");
      btn.classList.toggle("busy", state==="transcribing");
      btn.disabled=(state==="transcribing");
      if(state!=="recording") clearClipTimer();
      if(labelEl && state!=="recording") labelEl.textContent = state==="transcribing" ? "Transcribing…" : idle;
    }

    async function stopAndTranscribe(){
      if(!rec) return;
      const wasAuto=autoSaved; autoSaved=false;
      setState("transcribing");
      const {stream, audioCtx, processor, source, chunks}=rec;
      rec=null;
      if(activeRecording===api) activeRecording=null;
      try{
        processor.disconnect(); source.disconnect();
        stream.getTracks().forEach(t=>t.stop());
        const sampleRate=audioCtx.sampleRate;
        const pcm=mergeFloat32(chunks);
        await audioCtx.close();
        const resampled=resampleTo16k(pcm, sampleRate);
        const wavBlob=encodeWav16kMono(resampled);
        const text=(await transcribeAudio(wavBlob)).trim();
        if(text) target.value += (target.value && !/\s$/.test(target.value) ? " " : "") + text;
        if(help) help.textContent = wasAuto
          ? "Saved this clip automatically at the 3-minute limit — click Dictate to continue where you left off."
          : "";
      }catch(err){
        if(help) help.textContent=(err && err.message) || "Transcription failed — type instead.";
      }finally{
        dictationBusy=false;
        setState("idle");
      }
    }

    const api={ stop: stopAndTranscribe };

    async function start(){
      try{
        if(activeRecording && activeRecording!==api) activeRecording.stop();
        const stream=await navigator.mediaDevices.getUserMedia({audio:true});
        const audioCtx=new (window.AudioContext||window.webkitAudioContext)();
        const source=audioCtx.createMediaStreamSource(stream);
        const processor=audioCtx.createScriptProcessor(4096,1,1);
        const chunks=[];
        processor.onaudioprocess=e=>{ chunks.push(new Float32Array(e.inputBuffer.getChannelData(0))); };
        source.connect(processor);
        processor.connect(audioCtx.destination);
        rec={stream, audioCtx, processor, source, chunks};
        activeRecording=api;
        autoSaved=false;
        dictationBusy=true;
        setState("recording");
        clipStart=Date.now();
        tickClip(); // paint the countdown immediately, don't wait a full interval
        clipTimer=setInterval(tickClip, 500);
      }catch(err){
        setState("idle");
        if(help) help.textContent="The mic is blocked in this browser — type instead.";
      }
    }

    btn.addEventListener("click", ()=>{
      if(state==="idle") start();
      else if(state==="recording") stopAndTranscribe();
    });
  }

  // Upload a recording -> same local /api/transcribe path as the mic, inserted into the same
  // field. Works even where the mic is blocked/unavailable, since it needs no getUserMedia.
  function setupAudioUpload(input, target, help){
    if(!input || !target) return;
    input.addEventListener("change", async ()=>{
      const file=input.files && input.files[0];
      if(!file) return;
      if(help) help.textContent="Transcribing the uploaded recording locally… this can take a couple of minutes.";
      input.disabled=true; dictationBusy=true;
      try{
        const text=(await transcribeAudio(file)).trim();
        if(text) target.value += (target.value && !/\s$/.test(target.value) ? " " : "") + text;
        if(help) help.textContent = text ? "" : "No speech was found in that file.";
      }catch(err){
        if(help) help.textContent=(err && err.message) || "Couldn't transcribe that file — a WAV recording works best.";
      }finally{
        input.value=""; // let the same file be re-selected
        input.disabled=false; dictationBusy=false;
      }
    });
  }
  // Live in-session capture: continuous, hands-off recording of the whole visit. Records into
  // ~3-min segments and transcribes each locally through a SINGLE serialized worker (one MedASR
  // pass at a time, to stay within the CPU-only budget), appending to the same field in order.
  // Recording never blocks on transcription — segments queue and drain in the background.
  function setupLiveCapture(btn, target, help, labelEl){
    if(!btn || !target) return;
    const idle=(labelEl && labelEl.textContent) || "Record session";
    if(!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia){
      btn.disabled=true; btn.style.opacity=.5; btn.style.cursor="default";
      return; // typing/upload still work without a mic
    }
    const CHUNK_MS=MAX_CLIP_MS; // transcribe the session in ~3-min segments as it runs
    let state="idle"; // idle | recording | finishing
    let live=null, buffer=[], sampleRate=16000;
    let sessionStart=0, uiTimer=null, chunkTimer=null;
    let queue=[], workerRunning=false, recordingDone=false;

    function appendText(t){
      t=(t||"").trim();
      if(t) target.value += (target.value && !/\s$/.test(target.value) ? " " : "") + t;
    }
    function updateHelp(){
      if(!help || state!=="recording") return;
      const pend=queue.length + (workerRunning?1:0);
      help.textContent="Recording the session — "+fmtClock(Date.now()-sessionStart)+" elapsed, transcribing locally as you go"
        +(pend?(" ("+pend+" segment"+(pend>1?"s":"")+" processing)"):"")+". Click Stop when the visit ends.";
    }
    async function worker(){
      if(workerRunning) return;
      workerRunning=true;
      while(queue.length){
        const seg=queue.shift();
        try{ appendText(await transcribeAudio(encodeWav16kMono(resampleTo16k(seg.pcm, seg.rate)))); }
        catch(err){ /* a dropped segment must not kill the running session */ }
        updateHelp();
      }
      workerRunning=false;
      if(recordingDone) finalizeUI();
    }
    function flushSegment(){
      if(!buffer.length) return;
      queue.push({pcm:mergeFloat32(buffer), rate:sampleRate});
      buffer=[];
      if(!workerRunning) worker();
    }
    function tick(){
      if(labelEl) labelEl.textContent="Stop · "+fmtClock(Date.now()-sessionStart);
      updateHelp();
    }
    function finalizeUI(){
      state="idle";
      btn.classList.remove("live","busy");
      btn.disabled=false; dictationBusy=false;
      if(labelEl) labelEl.textContent=idle;
      if(help) help.textContent="Session transcript added below — review and edit it, then Generate. (Live capture has no speaker separation, so tidy up any cross-talk.)";
    }
    async function start(){
      try{
        if(activeRecording && activeRecording!==api) activeRecording.stop();
        const stream=await navigator.mediaDevices.getUserMedia({audio:true});
        const audioCtx=new (window.AudioContext||window.webkitAudioContext)();
        sampleRate=audioCtx.sampleRate;
        const source=audioCtx.createMediaStreamSource(stream);
        const processor=audioCtx.createScriptProcessor(4096,1,1);
        processor.onaudioprocess=e=>{ buffer.push(new Float32Array(e.inputBuffer.getChannelData(0))); };
        source.connect(processor); processor.connect(audioCtx.destination);
        live={stream, audioCtx, processor, source};
        activeRecording=api; dictationBusy=true; recordingDone=false; queue=[]; buffer=[];
        sessionStart=Date.now();
        state="recording"; btn.classList.add("live"); btn.classList.remove("busy");
        tick(); uiTimer=setInterval(tick,1000); chunkTimer=setInterval(flushSegment,CHUNK_MS);
      }catch(err){
        state="idle"; btn.classList.remove("live","busy");
        if(help) help.textContent="The mic is blocked in this browser — type or upload instead.";
      }
    }
    async function stop(){
      if(state!=="recording") return;
      clearInterval(uiTimer); clearInterval(chunkTimer);
      state="finishing"; btn.classList.remove("live"); btn.classList.add("busy"); btn.disabled=true;
      if(labelEl) labelEl.textContent="Finishing…";
      if(help) help.textContent="Finishing the last segment(s) — transcribing locally…";
      const l=live; live=null;
      if(activeRecording===api) activeRecording=null;
      if(l){ try{ l.processor.disconnect(); l.source.disconnect(); l.stream.getTracks().forEach(t=>t.stop()); await l.audioCtx.close(); }catch(e){} }
      flushSegment();       // enqueue the final partial segment
      recordingDone=true;   // the worker finalizes the UI once the queue drains
      if(!workerRunning){ if(queue.length) worker(); else finalizeUI(); }
    }
    const api={ stop };
    btn.addEventListener("click", ()=>{
      if(state==="idle") start();
      else if(state==="recording") stop();
    });
  }
  setupDictation($("micBtn"), dictation, $("micHelp"), $("micLabel"));
  setupAudioUpload($("audioFile"), dictation, $("micHelp"));
  setupLiveCapture($("liveBtn"), dictation, $("micHelp"), $("liveLabel"));

  // ---------- Generate ----------
  $("generateBtn").addEventListener("click", ()=>generate());
  // Delegated: "Copy codes" appears in the billing block of both the review and the saved-note
  // view; each button carries its own comma-joined codes in data-codes, so one listener covers both.
  output.addEventListener("click", async (e)=>{
    const b=e.target.closest(".copy-codes"); if(!b) return;
    try{ await navigator.clipboard.writeText(b.dataset.codes||""); toast("Codes copied: "+(b.dataset.codes||"")); }
    catch(_){ toast("Couldn't copy — select and copy manually."); }
  });
  // Delegated CPT decision handlers. Scoped to `output` so they can only ever act on the note
  // currently under review — never on a saved note, which has no draft to decide about.
  output.addEventListener("click", (e)=>{
    if(!lastResult) return;
    const confirmAll=e.target.closest(".bconfirm-all");
    if(confirmAll){
      const billable=((lastResult.billing||{}).interventions||[]).filter(x=>x.status==="performed");
      billable.forEach(c=>{
        if(codeDecision(lastResult, c.code).state==="pending"){
          lastResult.codeDecisions=lastResult.codeDecisions||{};
          lastResult.codeDecisions[c.code]={state:"confirmed", replacement:null};
          lastResult.sections=rewriteCptMarkers(lastResult.sections, c.code, "confirmed", null);
        }
      });
      renderResult(lastResult);
      toast("All codes confirmed.");
      return;
    }
    const ok=e.target.closest(".bconfirm");
    if(ok){ setCodeDecision(lastResult, ok.dataset.code, "confirmed"); return; }
    const no=e.target.closest(".bremove");
    if(no){ setCodeDecision(lastResult, no.dataset.code, "removed"); return; }
    const undo=e.target.closest(".bundo");
    if(undo){ setCodeDecision(lastResult, undo.dataset.code, "pending"); return; }
    const go=e.target.closest(".brepl-go");
    if(go){
      const input=output.querySelector('.brepl-in[data-code="'+go.dataset.code+'"]');
      const val=((input&&input.value)||"").trim();
      if(!val){ if(input) input.focus(); return; }
      setCodeDecision(lastResult, go.dataset.code, "removed", val);
    }
  });
  // Enter in the replacement box applies it, so the clinician never has to reach for the mouse.
  output.addEventListener("keydown", (e)=>{
    if(e.key!=="Enter" || !e.target.classList.contains("brepl-in")) return;
    e.preventDefault();
    const val=(e.target.value||"").trim();
    if(val && lastResult) setCodeDecision(lastResult, e.target.dataset.code, "removed", val);
  });

  // The template-reference footer link jumps to the Templates tab (showPage is hoisted).
  output.addEventListener("click", (e)=>{
    const g=e.target.closest(".linkbtn[data-goto]"); if(!g) return;
    showPage(g.getAttribute("data-goto"));
  });
  // Ctrl/Cmd+Enter in the dictation box generates, for a keyboard-fast workflow (guarded so it
  // can't fire a second generation while one is already running).
  if(dictation) dictation.addEventListener("keydown", (e)=>{
    if(e.key==="Enter" && (e.ctrlKey||e.metaKey) && !$("generateBtn").disabled){ e.preventDefault(); generate(); }
  });
  // ---------- Live generation view (token streaming) ----------
  // The note streams from the on-device model token-by-token, so the clinician watches it write and a
  // long generation is never a blank wait or discarded by a timeout (data flows the whole time). An
  // elapsed timer runs alongside; the raw stream is a live draft, replaced by the structured, flagged
  // note when it completes.
  let genTimer=null;
  function startGenLive(form, elapsedSeconds){
    output.innerHTML='<div class="genlive">'+
      '<div class="genlive-head"><span class="spin"></span><span class="genlive-label">Writing the '+esc(form.name)+'…</span><span class="genlive-el" id="genpEl">0:00</span></div>'+
      '<div class="genlive-status" id="genLiveStatus"></div>'+
      '<pre class="genlive-text" id="genLiveText"></pre>'+
      '<div class="genlive-hint">Streaming live from the on-device model — read it as it writes; nothing is lost if it takes a while.</div>'+
      '</div>';
    // Offset by however long the job has ALREADY been running, so re-attaching after a reload
    // shows the note's real age rather than restarting the clock at 0:00.
    const start=Date.now() - (elapsedSeconds||0)*1000;
    genTimer=setInterval(()=>{ const el=$("genpEl"); if(!el){ stopGenProgress(); return; } el.textContent=fmtClock(Date.now()-start); },1000);
  }
  function appendGenLive(t){
    const el=$("genLiveText"); if(!el) return;
    const near = el.scrollHeight-el.scrollTop-el.clientHeight < 40;  // don't yank the view if they scrolled up to read
    el.textContent+=t; if(near) el.scrollTop=el.scrollHeight;
  }
  function setGenLiveStatus(t){ const el=$("genLiveStatus"); if(el) el.textContent=t||""; }
  function stopGenProgress(){ if(genTimer){ clearInterval(genTimer); genTimer=null; } }

  // ---------- Notes in progress (the generation queue) ----------
  // Generation runs server-side; the browser is a viewer. `attachedJob` is the one being tailed
  // into the live pane — at most one, because there is only one output pane. Every other job keeps
  // running regardless, which is the entire point: start a note, go see the next patient.
  let attachedJob=null, attachCursor=0, attachTimer=null, trayTimer=null;
  const TRAY_POLL_MS=1500;

  function trayRowHTML(j){
    const bits=[j.form_name];
    if(j.status==="queued") bits.push(j.queue_position ? ("#"+j.queue_position+" in line") : "waiting");
    else if(j.status==="running") bits.push((j.detail||"Writing…")+" · "+fmtClock(j.elapsed_seconds*1000));
    else if(j.status==="done") bits.push("ready to review · took "+fmtClock(j.elapsed_seconds*1000));
    else if(j.status==="error") bits.push(j.error||"failed");
    else bits.push("cancelled");
    if(j.fast) bits.push("fast draft");
    const canOpen = j.status==="done";
    return '<div class="tray-row '+esc(j.status)+'">'+
      '<span class="tray-dot"></span>'+
      '<div class="tray-main"><div class="tray-who">'+esc(j.patient_name)+'</div>'+
      '<div class="tray-meta">'+esc(bits.join(" · "))+'</div></div>'+
      '<div class="tray-actions">'+
        (canOpen ? '<button class="btn btn-primary btn-sm tray-open" data-job="'+esc(j.id)+'">Review</button>' : '')+
        (j.status==="running" && attachedJob!==j.id ? '<button class="btn btn-ghost btn-sm tray-watch" data-job="'+esc(j.id)+'">Watch</button>' : '')+
        '<button class="btn btn-ghost btn-sm tray-x" data-job="'+esc(j.id)+'">'+(j.status==="queued"||j.status==="running" ? "Cancel" : "Dismiss")+'</button>'+
      '</div></div>';
  }

  // Announce a note that finished while the clinician was elsewhere. Without this the queue is
  // silent and they have to keep checking, which puts the waiting back on them.
  const trayLastStatus={};
  function announceFinished(rows){
    rows.forEach(j=>{
      const prev=trayLastStatus[j.id];
      if(prev && prev!==j.status){
        if(j.status==="done") toast("Note ready to review — "+j.patient_name+".");
        else if(j.status==="error") toast("Note failed for "+j.patient_name+".");
      }
      trayLastStatus[j.id]=j.status;
    });
    Object.keys(trayLastStatus).forEach(id=>{
      if(!rows.some(r=>r.id===id)) delete trayLastStatus[id];
    });
  }

  async function refreshTray(){
    const tray=$("genTray"); if(!tray) return [];
    let rows=[];
    try{ rows=await listJobs(); }catch(_){ return []; }
    announceFinished(rows);
    tray.classList.toggle("hidden", rows.length===0);
    if(!rows.length){ $("trayList").innerHTML=""; $("traySub").textContent=""; return rows; }
    const active=rows.filter(r=>r.status==="queued"||r.status==="running").length;
    const ready=rows.filter(r=>r.status==="done").length;
    $("traySub").textContent=[active?active+" writing":null, ready?ready+" ready to review":null]
      .filter(Boolean).join(" · ");
    $("trayList").innerHTML=rows.map(trayRowHTML).join("");
    return rows;
  }

  // One poll loop for the tray, running only while something is actually in it. Stopping when the
  // tray empties keeps an idle app from waking the CPU every 1.5s — this machine needs its cores.
  function ensureTrayPolling(){
    if(trayTimer) return;
    trayTimer=setInterval(async ()=>{
      const rows=await refreshTray();
      if(!rows.length){ clearInterval(trayTimer); trayTimer=null; }
    }, TRAY_POLL_MS);
  }

  // Tail one job's output into the live pane. Detaching (switching patients, watching another
  // note) stops the POLL, never the job.
  function clearAttachPoll(){ if(attachTimer){ clearInterval(attachTimer); attachTimer=null; } }
  function detachJob(){
    clearAttachPoll();
    attachedJob=null; attachCursor=0; stopGenProgress();
  }

  function attachJob(jobId){
    // clearAttachPoll, NOT detachJob: the caller has just called startGenLive to put the elapsed
    // clock on screen, and detachJob stops that clock. Re-attaching swaps which job we poll; it
    // does not tear down the view we are about to write into.
    clearAttachPoll();
    attachedJob=jobId; attachCursor=0;
    ensureTrayPolling();
    const poll=async ()=>{
      if(attachedJob!==jobId) return;
      const t=await tailJob(jobId, attachCursor);
      if(!t){ detachJob(); return; }
      attachCursor=t.cursor;
      if(t.text) appendGenLive(t.text);
      if(t.status==="queued"){
        setGenLiveStatus(t.queue_position ? ("Waiting — #"+t.queue_position+" in line behind another note.")
                                          : "Waiting to start…");
      } else if(t.status==="running"){ setGenLiveStatus(t.detail||""); }
      if(t.status==="done"){
        detachJob();
        adoptResult(t.result, {patientId: t.patient_id, summary: t.summary, extraInfo: t.extra_info});
        refreshTray();
      } else if(t.status==="error"){
        detachJob(); showError(t.error||"Generation failed."); refreshTray();
      } else if(t.status==="cancelled"){
        detachJob(); output.innerHTML='<div class="empty">Generation cancelled.</div>'; refreshTray();
      }
    };
    attachTimer=setInterval(poll, 900);
    poll();
  }

  document.addEventListener("click", async (e)=>{
    const open=e.target.closest(".tray-open");
    if(open){
      const t=await tailJob(open.dataset.job, 0);
      if(!t || !t.result) return;
      // Re-open on the patient the note was written for — reviewing note A while the header says
      // patient B is exactly how a note gets saved to the wrong chart.
      if(t.patient_id && t.patient_id!==currentPatient){
        currentPatient=t.patient_id; patientSel.value=t.patient_id; await onPatientChange();
      }
      showPage("home");
      adoptResult(t.result, {patientId: t.patient_id, summary: t.summary, extraInfo: t.extra_info});
      return;
    }
    const watch=e.target.closest(".tray-watch");
    if(watch){
      showPage("home");
      const j=(await listJobs()).find(r=>r.id===watch.dataset.job);
      startGenLive({name:(j&&j.form_name)||"note"}, j&&j.elapsed_seconds);
      attachJob(watch.dataset.job);
      return;
    }
    const x=e.target.closest(".tray-x");
    if(x){
      if(attachedJob===x.dataset.job){ detachJob(); output.innerHTML='<div class="empty">Generation cancelled.</div>'; }
      await cancelJob(x.dataset.job);
      refreshTray();
    }
  });

  // Turn a /api/generate result into the reviewable `lastResult` and render it. Shared by the
  // live attach below and by re-opening a finished job from the tray, so a note reviewed ten
  // minutes later is byte-identical to one reviewed the moment it finished.
  function adoptResult(data, ctx){
    if(!data.sections || !data.sections.length){
      if(data.raw_text && data.raw_text.trim()){
        output.innerHTML='<div class="sheet"><div class="sec"><div class="sec-body">'+withGaps(data.raw_text)+'</div></div></div>';
      } else { showError("The model didn't return a note this time."); }
      return;
    }
    // mapSections is called TWICE on purpose so `sections` and `originalSections` are genuinely
    // independent object graphs. If they ever aliased, the "Done editing" handler — which writes
    // r.sections[i].body in place — would destroy the original exactly as it did before capture
    // existed, and no test would catch it. Object.freeze is cheap insurance on top.
    const mapSections = arr => (arr||[]).map(s=>({heading:s.heading, body:s.body, carriedForward:s.carried_forward}));
    lastResult={
      sections: mapSections(data.sections),
      // Pinned ONCE at generation and never overwritten. The question this must answer later is
      // "how far is the signed note from what the model produced unaided?" — the revise channel
      // is recorded separately, so the two stay disentangleable.
      originalSections: Object.freeze(mapSections(data.sections).map(Object.freeze)),
      reviseInstructions: [],
      modelId: data.model_id || null,
      fastTier: !!data.fast,
      templateSpecSha: data.template_spec_sha || null,
      templateCustomized: !!data.template_customized,
      missingInfo: data.missing_info || [],
      formName: data.form_name, formId: data.form_id,
      patientId: ctx.patientId,
      dictationRaw: ctx.extraInfo ? (ctx.summary+"\n\nADDITIONAL DETAILS: "+ctx.extraInfo) : ctx.summary,
      usedPrior: !!data.used_prior,
      // The server's deterministic billing draft (app/generate/billing.py), derived from the
      // DICTATION. Null on a revise, which has only the note's prose to work from — the client
      // then keeps whatever draft the original generate produced.
      billing: data.billing || (lastResult && lastResult.billing) || null,
      date: new Date(),
    };
    renderResult(lastResult);
  }

  async function generate(extraInfo){
    // If the user hits Generate while still in the guided walkthrough, fold their
    // answers into the dictation box (and switch to Free) before reading it.
    if(guidedMode){
      if(dictationBusy){ toast("Click Stop to finish the recording first."); return; }
      guidedFinish();
    }
    const summary=dictation.value.trim();
    if(!summary){ dictation.focus(); dictation.style.borderColor="#cf4631"; setTimeout(()=>dictation.style.borderColor="",1200); return; }
    const form=FORMS_BY_ID[currentForm];
    const btn=$("generateBtn"); btn.disabled=true;
    let job;
    try{
      job = await enqueueGeneration({ patient_id: currentPatient, form_id: currentForm, summary,
        use_prior: priorOn, extra_info: extraInfo || null, fast: fastMode });
    }catch(e){
      btn.disabled=false; showError(e.message||"Could not start the note."); return;
    }
    btn.disabled=false;                 // the note is the SERVER's job now — start another whenever
    startGenLive(form);
    refreshTray();
    attachJob(job.id);
  }
  function showError(msg){ output.innerHTML='<div class="empty">'+esc(msg)+' Try Generate again — the local model can occasionally be slow to respond.</div>'; }

  // ---------- Sheet rendering ----------
  // Split a section body into "Label: value" rows so every subfield is identifiable (block-format
  // notes pack many fields under one heading). Returns null for plain prose, which renders as-is.
  const FIELD_LINE=/^\s*([A-Z][A-Za-z0-9 /&()\-–—]{1,44}?):\s*(.*)$/;
  function bodyToFields(body){
    const lines=(body||"").split("\n"); const fields=[]; const lead=[]; let cur=null, matched=false;
    lines.forEach(line=>{
      const m=line.match(FIELD_LINE);
      if(m && m[1].trim().split(/\s+/).length<=6){                 // short "Label:" -> a field, not prose
        matched=true; if(cur) fields.push(cur); cur={label:m[1].trim(), value:m[2].trim()};
      } else if(cur){ if(line.trim()) cur.value+=(cur.value?" ":"")+line.trim(); }   // value continuation
      else if(line.trim()){ lead.push(line.trim()); }
    });
    if(cur) fields.push(cur);
    return matched ? {fields:fields, lead:lead.join(" ").trim()} : null;
  }
  function sectionBodyHTML(body){
    const parsed=bodyToFields(body);
    if(!parsed) return '<div class="sec-body">'+withGaps(body)+'</div>';
    let h = parsed.lead ? '<div class="sec-body">'+withGaps(parsed.lead)+'</div>' : '';
    h += '<div class="flds">'+parsed.fields.map(f=>
      '<div class="fld"><span class="fld-l">'+esc(f.label)+'</span><span class="fld-v">'+(f.value?withGaps(f.value):'<span class="fld-empty">—</span>')+'</span></div>'
    ).join('')+'</div>';
    return h;
  }
  function secBoxHTML(s){
    return '<div class="sec'+(s.carriedForward?' cf':'')+'"><div class="sec-h"><span class="lbl">'+esc(s.heading)+'</span>'+(s.carriedForward?'<span class="cf-badge">Carried forward</span>':'')+'</div>'+sectionBodyHTML(s.body)+'</div>';
  }
  function sheetHTML(formName, p, sections, date){
    let h='<div class="sheet"><div class="sheet-head"><div class="sheet-title">'+esc(formName)+'</div><div class="sheet-sub">'+esc(p.name)+' · '+esc((p.sub.split("·")[0]||"").trim())+' · '+fmtDate(date)+'</div></div>';
    // Bucket sections into the 4 SOAP blocks and render each block ONCE, in S/O/A/P order — a
    // sequential "band on change" approach produced duplicate "Subjective" bands when the classifier
    // wasn't monotonic (e.g. Chief Complaint→S, Diagnoses→A, Medications→S).
    const buckets={S:[],O:[],A:[],P:[]};
    (sections||[]).forEach(s=>{ buckets[soapBlockFor(s.heading)].push(s); });
    ["S","O","A","P"].forEach(k=>{
      const bs=buckets[k]; if(!bs.length) return;
      // Suppress the band if the single section IS the block itself (a "## Subjective" section from the
      // block template already carries the block name as its heading).
      const onlyBlock = bs.length===1 && (bs[0].heading||"").toLowerCase().includes(SOAP_LABELS[k].toLowerCase());
      if(!onlyBlock) h+='<div class="soap-block">'+esc(SOAP_LABELS[k])+'</div>';
      bs.forEach(s=>{ h+=secBoxHTML(s); });
    });
    return h+'</div>';
  }

  // rows for an edit textarea: enough to show the section without scrolling, within reason.
  function editRows(body){ body=body||""; return Math.min(16, Math.max(2, body.split("\n").length + Math.ceil(body.length/72))); }

  // Edit mode: every section body becomes a textarea (markers shown raw so they can be confirmed,
  // changed, or removed). "Done editing" writes the edits back into r.sections and re-renders the
  // read-only review; nothing is persisted until Save. This is the confirm-before-finalize step.
  function renderEditView(r, p){
    let html='<div class="savebar"><button class="btn btn-save" id="doneEditBtn">Done editing</button><span class="savehint">Edit any section — including confirming or changing a suggested CPT code. Changes apply on Done; nothing is saved until you Save.</span></div>';
    html+='<div class="sheet editing"><div class="sheet-head"><div class="sheet-title">'+esc(r.formName)+'</div></div>';
    (r.sections||[]).forEach((s,i)=>{
      html+='<div class="sec'+(s.carriedForward?' cf':'')+'"><div class="sec-h"><span class="lbl">'+esc(s.heading)+'</span>'+(s.carriedForward?'<span class="cf-badge">Carried forward</span>':'')+'</div>';
      html+='<textarea class="sec-edit" data-i="'+i+'" rows="'+editRows(s.body)+'">'+esc(s.body||"")+'</textarea></div>';
    });
    html+='</div>';
    output.innerHTML=html;
    $("doneEditBtn").addEventListener("click", ()=>{
      output.querySelectorAll("textarea.sec-edit").forEach(t=>{ r.sections[+t.dataset.i].body=t.value; });
      renderResult(r, false);
    });
  }

  function renderResult(r, editing){
    const p=PATIENTS_BY_ID[r.patientId]||PATIENTS_BY_ID[currentPatient];
    if(editing){ renderEditView(r, p); return; }
    const missing=Array.isArray(r.missingInfo)?r.missingInfo.filter(Boolean):[];
    const reviewCount=missing.length+countGapFlags(r.sections);
    const savehint=reviewCount?(reviewCount+(reviewCount===1?" item":" items")+" to review before signing"):"Looks complete";
    let html='<div class="savebar"><button class="btn btn-save" id="saveBtn">Save to '+esc(firstName(p.name))+"'s file</button><button class=\"btn btn-ghost\" id=\"editBtn\">Edit</button><button class=\"btn btn-ghost\" id=\"copyBtn\">Copy note</button><button class=\"btn btn-ghost\" id=\"printBtn\">Print</button><span class=\"savehint\">"+esc(savehint)+'</span></div>';
    if(missing.length){
      html+='<div class="needs"><h3><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>Before finalizing, please provide</h3><ul>';
      missing.forEach(x=> html+="<li>"+esc(x)+"</li>");
      html+='</ul><div class="resolve"><textarea id="resolveBox" placeholder="Add the missing details (e.g. \'manual therapy 10 minutes, BP 128/78, HR 72\') — type or dictate."></textarea><div class="resolve-actions"><button class="btn btn-mic" id="resolveMic"><span class="pulse"></span><span id="resolveMicLabel">Dictate</span></button><button class="btn btn-amber" id="resolveBtn">Add details &amp; update note</button></div><p class="mic-help-sm" id="resolveMicHelp"></p></div></div>';
    }
    html+=billingHTML(r.sections, r.billing, r);
    html+=officeAllyHTML(r.sections);
    html+=sheetHTML(r.formName, p, r.sections, r.date);
    // Ask-for-changes: the clinician tells the model what to adjust in plain language and it
    // rewrites the note (streams live, nothing saved until Save).
    html+='<div class="revise"><h3>Ask for changes</h3><p class="revise-lede">Tell Cadence what to adjust and it rewrites the note — e.g. “make the assessment more concise”, “move the meds list to the top”, “write the goals as bullet points”.</p>'
      +'<textarea id="reviseBox" placeholder="Describe the change you want — type or dictate."></textarea>'
      +'<div class="resolve-actions"><button class="btn btn-mic" id="reviseMic"><span class="pulse"></span><span id="reviseMicLabel">Dictate</span></button><button class="btn btn-save" id="reviseBtn">Apply changes</button></div><p class="mic-help-sm" id="reviseMicHelp"></p></div>';
    output.innerHTML=html;
    wireOfficeAlly(output, r.sections);

    $("saveBtn").addEventListener("click", ()=>saveCurrent(r));
    $("editBtn").addEventListener("click", ()=>renderResult(r, true));
    $("copyBtn").addEventListener("click", async ()=>{
      try{ await navigator.clipboard.writeText(noteToText(r)); toast("Note copied to clipboard."); }
      catch(e){ toast("Couldn't copy — select the note text and copy manually."); }
    });
    $("printBtn").addEventListener("click", ()=>window.print());
    const rb=$("resolveBtn");
    if(rb){ rb.addEventListener("click", ()=>{ const extra=($("resolveBox").value||"").trim(); if(!extra){ $("resolveBox").focus(); return; } generate(extra); }); }
    const rmic=$("resolveMic");
    if(rmic) setupDictation(rmic, $("resolveBox"), $("resolveMicHelp"), $("resolveMicLabel"));
    const vb=$("reviseBtn");
    if(vb) vb.addEventListener("click", ()=>{ const ins=($("reviseBox").value||"").trim(); if(!ins){ $("reviseBox").focus(); return; } reviseNote(r, ins); });
    const vmic=$("reviseMic");
    if(vmic) setupDictation(vmic, $("reviseBox"), $("reviseMicHelp"), $("reviseMicLabel"));
  }

  // Plain-text form of the note the revise prompt rewrites (## headings + bodies, no patient header).
  function noteToPlain(r){
    return (r.sections||[]).map(s=>"## "+s.heading+(s.carriedForward?" [[CARRIED FORWARD]]":"")+"\n"+(s.body||"")).join("\n\n");
  }
  async function reviseNote(r, instruction){
    const form=FORMS_BY_ID[r.formId]||FORMS_BY_ID[currentForm];
    startGenLive(form||{name:r.formName});
    setGenLiveStatus("Applying your changes…");
    let finalResult=null, hadError=false;
    await generateStream(
      { patient_id: r.patientId, form_id: r.formId, note_text: noteToPlain(r), instruction: instruction, fast: fastMode },
      {
        onToken: (t)=>appendGenLive(t),
        onDone:  (res)=>{ finalResult=res; },
        onError: (m)=>{ hadError=true; stopGenProgress(); showError(m); },
      },
      "/api/revise/stream"
    );
    stopGenProgress();
    const returned = !!(finalResult && finalResult.sections && finalResult.sections.length);
    // "Did we get sections back" was the old test, and it is true even when the model handed the
    // note back word for word — so the clinician waited minutes and was told "Changes applied"
    // about a note that had not changed. Compare the actual text instead.
    const sig = arr => (arr||[]).map(x=>(x.heading||"")+" "+(x.body||"")).join("");
    const changed = returned && sig(finalResult.sections) !== sig(r.sections);
    // The clinician describing in their own words what was wrong is the highest-signal correction
    // data in the app, and it used to be discarded the moment the stream ended. A FAILED revision
    // is recorded too — "the model couldn't do X" is signal, and it costs nothing.
    (r.reviseInstructions || (r.reviseInstructions=[])).push(
      {text: instruction, applied: changed, at: new Date().toISOString()});
    if(changed){
      // Only r.sections is reassigned — r.originalSections stays pinned to the first generation.
      r.sections=finalResult.sections.map(s=>({heading:s.heading, body:s.body, carriedForward:s.carried_forward}));
      r.missingInfo=finalResult.missing_info||[];
      renderResult(r);
      toast("Changes applied — review before saving.");
    } else if(returned){
      // The model answered and produced nothing different. Say exactly that — a clinician who is
      // told "applied" about an unchanged note stops trusting the button, and re-running the same
      // request is the one thing guaranteed not to help.
      renderResult(r);
      toast("The model returned the note unchanged — try naming the section and the exact wording.");
    } else if(!hadError){
      renderResult(r);
      toast("The model couldn't produce a revision — the note is unchanged.");
    }
  }

  async function saveCurrent(r){
    const res = await saveNote(r.patientId, {
      form_id: r.formId, form_name: r.formName,
      sections: r.sections.map(s=>({heading:s.heading, body:s.body, carried_forward:s.carriedForward})),
      missing_info: r.missingInfo || [],
      dictation_raw: r.dictationRaw || "",
      used_prior: !!r.usedPrior,
      // Correction capture: what the model produced, what the clinician asked for, and enough
      // provenance to interpret both later. Stays in the encrypted local DB — see schema.sql.
      original_sections: (r.originalSections||[]).map(s=>({heading:s.heading, body:s.body, carried_forward:s.carriedForward})),
      revise_instructions: r.reviseInstructions || [],
      model_id: r.modelId || null,
      fast: !!r.fastTier,
      template_spec_sha: r.templateSpecSha || null,
      template_customized: !!r.templateCustomized,
    });
    if(!res.ok){ toast("Couldn't save — try again."); return; }
    await refreshCurrentPatient();
    updateFilesButton();
    renderPriorFlag();
    const b=$("saveBtn"); if(b){ b.textContent="Saved ✓"; b.classList.add("done"); b.disabled=true; }
    toast("Saved to "+firstName(PATIENTS_BY_ID[r.patientId].name)+"'s file");
  }

  // ---------- Modal + toast ----------
  function openOverlay(title, wide){
    $("modalTitle").textContent=title;
    overlay.querySelector(".modal").classList.toggle("wide", !!wide);
    overlay.classList.add("open");
  }
  function closeOverlay(){ overlay.classList.remove("open"); modalBody.innerHTML=""; }
  $("modalClose").addEventListener("click", closeOverlay);
  overlay.addEventListener("click", e=>{ if(e.target===overlay) closeOverlay(); });
  document.addEventListener("keydown", e=>{ if(e.key==="Escape" && overlay.classList.contains("open")) closeOverlay(); });

  let toastT;
  function toast(msg){ const t=$("toast"); t.textContent=msg; t.classList.add("show"); clearTimeout(toastT); toastT=setTimeout(()=>t.classList.remove("show"),2200); }

  // ---------- New patient ----------
  $("newPatientBtn").addEventListener("click", openNewPatient);
  function openNewPatient(){
    openOverlay("New patient");
    modalBody.innerHTML=
      '<div class="mfield"><label>Full name</label><input id="npName" placeholder="e.g. Alex Rivera" autocomplete="off"></div>'+
      '<div class="mrow"><div class="mfield"><label>Date of birth</label><input id="npDob" placeholder="MM/DD/YYYY" autocomplete="off"></div><div class="mfield"><label>MRN</label><input id="npMrn" placeholder="e.g. 01023-557" autocomplete="off"></div></div>'+
      '<div class="mfield"><label>Condition / clinical summary</label><textarea id="npCond" rows="3" placeholder="e.g. L ankle sprain, 2 weeks post-injury — type or dictate"></textarea><div class="resolve-actions"><button class="btn btn-mic" id="npMic"><span class="pulse"></span><span id="npMicLabel">Dictate</span></button></div><p class="mic-help-sm" id="npMicHelp"></p></div>'+
      '<div class="mfield"><label>Scheduling notes <span class="mfield-opt">(optional)</span></label><input id="npSched" placeholder="e.g. Tue/Thu mornings; prefers early slots" autocomplete="off"></div>'+
      '<div class="modal-actions"><button class="btn btn-ghost" id="npCancel">Cancel</button><button class="btn btn-primary" style="width:auto;margin:0" id="npSave">Add patient</button></div>';
    setupDictation($("npMic"), $("npCond"), $("npMicHelp"), $("npMicLabel"));
    $("npName").focus();
    $("npCancel").addEventListener("click", closeOverlay);
    $("npSave").addEventListener("click", async ()=>{
      const name=($("npName").value||"").trim();
      if(!name){ $("npName").focus(); $("npName").style.borderColor="#cf4631"; setTimeout(()=>$("npName").style.borderColor="",1200); return; }
      const dob=($("npDob").value||"").trim(), mrn=($("npMrn").value||"").trim(), cond=($("npCond").value||"").trim(), sched=($("npSched").value||"").trim();
      const saveBtn=$("npSave"); saveBtn.disabled=true;
      try{
        const patient = await createPatient({name, dob: dob||null, mrn: mrn||null, condition: cond||null, scheduling_notes: sched||null});
        await loadPatients();
        currentPatient = patient.id;
        populatePatientSelect();
        await onPatientChange();
        closeOverlay();
        if(currentPage==="patients") renderRoster();
        toast(firstName(name)+" added");
      }catch(err){
        saveBtn.disabled=false;
        toast("Couldn't add patient — try again.");
      }
    });
  }

  // ---------- Edit patient ----------
  function openEditPatient(patientId){
    const p=PATIENTS_BY_ID[patientId];
    if(!p) return;
    openOverlay("Edit patient");
    modalBody.innerHTML=
      '<div class="mfield"><label>Full name</label><input id="epName" autocomplete="off"></div>'+
      '<div class="mrow"><div class="mfield"><label>Date of birth</label><input id="epDob" placeholder="MM/DD/YYYY" autocomplete="off"></div><div class="mfield"><label>MRN</label><input id="epMrn" placeholder="e.g. 01023-557" autocomplete="off"></div></div>'+
      '<div class="mfield"><label>Condition / clinical summary</label><textarea id="epCond" rows="3" placeholder="e.g. L ankle sprain, 2 weeks post-injury — type or dictate"></textarea><div class="resolve-actions"><button class="btn btn-mic" id="epMic"><span class="pulse"></span><span id="epMicLabel">Dictate</span></button></div><p class="mic-help-sm" id="epMicHelp"></p></div>'+
      '<div class="mfield"><label>Scheduling notes <span class="mfield-opt">(optional)</span></label><input id="epSched" placeholder="e.g. Tue/Thu mornings; prefers early slots" autocomplete="off"></div>'+
      '<div class="modal-actions"><button class="btn btn-ghost" id="epCancel">Cancel</button><button class="btn btn-primary" style="width:auto;margin:0" id="epSave">Save changes</button></div>';
    // Set field values as properties (not embedded in the HTML string) so names
    // with quotes/special characters can't break the markup.
    $("epName").value=p.name||"";
    $("epDob").value=p.dob||"";
    $("epMrn").value=p.mrn||"";
    $("epCond").value=p.condition||"";
    $("epSched").value=p.scheduling_notes||"";
    setupDictation($("epMic"), $("epCond"), $("epMicHelp"), $("epMicLabel"));
    $("epName").focus();
    $("epCancel").addEventListener("click", closeOverlay);
    $("epSave").addEventListener("click", async ()=>{
      const name=($("epName").value||"").trim();
      if(!name){ $("epName").focus(); $("epName").style.borderColor="#cf4631"; setTimeout(()=>$("epName").style.borderColor="",1200); return; }
      const b=$("epSave"); b.disabled=true;
      try{
        await updatePatient(patientId, {
          name,
          dob: ($("epDob").value||"").trim()||null,
          mrn: ($("epMrn").value||"").trim()||null,
          condition: ($("epCond").value||"").trim()||null,
          scheduling_notes: ($("epSched").value||"").trim()||null,
        });
        await loadPatients();
        populatePatientSelect();
        // If we're editing the patient currently loaded on Home, refresh just the
        // header display -- do NOT call onPatientChange(), which would wipe any
        // in-progress dictation and generated note.
        if(currentPatient===patientId){
          const up=PATIENTS_BY_ID[patientId];
          $("pAvatar").textContent=initialsOf(up.name);
          $("pName").innerHTML=esc(up.name)+(up.note_count===0?' <span class="fake-tag">· new patient</span>':"");
          $("pSub").textContent=up.sub;
        }
        if(currentPage==="patients") renderRoster();
        closeOverlay();
        toast(firstName(name)+" updated");
      }catch(err){
        b.disabled=false;
        toast("Couldn't save changes — try again.");
      }
    });
  }

  // ---------- Patient files ----------
  // openPatientNotes/showPatientNotesList/showPatientNoteView render into an
  // explicit `mount` element and take an explicit patientId (not the implicit
  // currentPatient), so the same code serves both the home "Patient file" button
  // (mount = modalBody, no onBack -- X closes) and the "All Patients" page's
  // per-row note drill-down (mount = #rosterMount, onBack returns to the roster).
  $("filesBtn").addEventListener("click", ()=>{
    const p=PATIENTS_BY_ID[currentPatient];
    if(!p) return;
    openOverlay("Patient file — "+p.name);
    openPatientNotes(modalBody, currentPatient, null);
  });
  $("editPatientBtn").addEventListener("click", ()=>{ if(currentPatient) openEditPatient(currentPatient); });

  async function openPatientNotes(mount, patientId, onBack){
    const p = PATIENTS_BY_ID[patientId];
    if(!p) return;
    mount.innerHTML='<div class="loadwrap"><span class="spin"></span></div>';
    const notes = await getPatientNotes(patientId);
    showPatientNotesList(mount, patientId, notes, onBack);
  }
  function showPatientNotesList(mount, patientId, notes, onBack){
    const p = PATIENTS_BY_ID[patientId];
    let h = onBack
      ? '<button class="backbtn" id="notesBack">← All Patients</button>'
      : "";
    if(onBack) h += '<div class="fileshead">'+esc(p.name)+' · '+notes.length+' note'+(notes.length===1?"":"s")+'</div>';
    if(!notes.length){
      h += '<div class="files-empty">No notes saved yet.<br>Generate a note and choose “Save to file”.</div>';
    } else {
      notes.forEach(f=>{
        h+='<div class="fileitem" data-id="'+esc(f.id)+'"><div class="ft">'+esc(f.form_name)+'</div><div class="fd">'+esc(fmtDateTime(f.created_at))+'</div><div class="fsnip">'+esc(f.snippet)+'</div></div>';
      });
    }
    mount.innerHTML=h;
    Array.prototype.forEach.call(mount.querySelectorAll(".fileitem"), el=>{
      el.addEventListener("click", ()=>showPatientNoteView(mount, patientId, el.getAttribute("data-id"), onBack));
    });
    const backBtn=mount.querySelector("#notesBack");
    if(backBtn) backBtn.addEventListener("click", onBack);
  }
  async function showPatientNoteView(mount, patientId, noteId, onBack){
    mount.innerHTML='<div class="loadwrap"><span class="spin"></span></div>';
    const note = await getNote(patientId, noteId);
    const p = PATIENTS_BY_ID[patientId];
    const sections = note.sections.map(s=>({heading:s.heading, body:s.body, carriedForward:s.carried_forward}));
    let h='<div class="noteview-top"><button class="backbtn" id="fileBack">← All files</button><span id="noteDelWrap"><button class="btn btn-ghost btn-sm noteview-delbtn" id="noteDelBtn">Delete note</button></span></div>';
    h+=billingHTML(sections);
    h+=officeAllyHTML(sections);
    h+=sheetHTML(note.form_name, p, sections, note.created_at);
    const savedFlags=(note.missing_info?note.missing_info.length:0)+countGapFlags(sections);
    if(savedFlags){ h+='<p class="savehint" style="margin-top:10px">'+esc(savedFlags+(savedFlags===1?" item was":" items were")+" flagged when this was saved.")+'</p>'; }
    mount.innerHTML=h;
    wireOfficeAlly(mount, sections);
    mount.querySelector("#fileBack").addEventListener("click", ()=>openPatientNotes(mount, patientId, onBack));

    const delWrap=mount.querySelector("#noteDelWrap");
    mount.querySelector("#noteDelBtn").addEventListener("click", ()=>{
      // Inline confirm rather than a modal: this view can itself already be inside
      // the overlay (Home's "Patient file"), and opening the overlay again would
      // clobber it.
      delWrap.innerHTML='<span class="confirm-inline">Delete this note permanently? <button class="btn btn-danger btn-sm" id="noteDelYes">Delete</button> <button class="btn btn-ghost btn-sm" id="noteDelNo">Cancel</button></span>';
      mount.querySelector("#noteDelNo").addEventListener("click", ()=>{
        delWrap.innerHTML='<button class="btn btn-ghost btn-sm noteview-delbtn" id="noteDelBtn2">Delete note</button>';
        mount.querySelector("#noteDelBtn2").addEventListener("click", ()=>showPatientNoteView(mount, patientId, noteId, onBack));
      });
      mount.querySelector("#noteDelYes").addEventListener("click", async ()=>{
        const yes=mount.querySelector("#noteDelYes"); yes.disabled=true; yes.textContent="Deleting…";
        try{
          await deleteNote(patientId, noteId);
          await loadPatients();
          populatePatientSelect();
          if(patientId===currentPatient){ updateFilesButton(); renderPriorFlag(); }
          toast("Note deleted");
          openPatientNotes(mount, patientId, onBack); // back to the (now shorter) list
        }catch(err){
          yes.disabled=false; yes.textContent="Delete";
          toast("Couldn't delete the note — try again.");
        }
      });
    });
  }

  // ---------- All Patients page ----------
  const rosterMount=$("rosterMount");
  $("rosterNewBtn").addEventListener("click", openNewPatient);

  async function renderRoster(){
    rosterMount.innerHTML='<div class="loadwrap"><span class="spin"></span></div>';
    const list = await loadPatients();
    populatePatientSelect(); // keep the home dropdown in sync with any new/renamed patients
    showRosterTable(list);
  }
  function showRosterTable(list){
    if(!list.length){
      rosterMount.innerHTML='<div class="files-empty">No patients yet.<br>Use “+ New patient” to add one.</div>';
      return;
    }
    let h='<div class="card rostercard"><table class="roster-table"><thead><tr><th>Name</th><th>DOB</th><th>MRN</th><th>Condition</th><th>Scheduling notes</th><th>Notes</th><th></th></tr></thead><tbody>';
    list.forEach(p=>{
      h+='<tr class="roster-row" data-id="'+esc(p.id)+'">'+
         '<td>'+esc(p.name)+'</td>'+
         '<td>'+esc(p.dob||"—")+'</td>'+
         '<td>'+esc(p.mrn||"—")+'</td>'+
         '<td>'+esc(p.condition||"—")+'</td>'+
         '<td>'+esc(p.scheduling_notes||"—")+'</td>'+
         '<td><span class="roster-notes-link">'+p.note_count+' note'+(p.note_count===1?"":"s")+'</span></td>'+
         '<td class="roster-actions"><button class="roster-edit" data-id="'+esc(p.id)+'" title="Edit patient" aria-label="Edit '+esc(p.name)+'">Edit</button><button class="roster-del" data-id="'+esc(p.id)+'" data-name="'+esc(p.name)+'" data-notes="'+p.note_count+'" title="Remove patient" aria-label="Remove '+esc(p.name)+'">Remove</button></td>'+
         '</tr>';
    });
    h+='</tbody></table></div>';
    rosterMount.innerHTML=h;
    Array.prototype.forEach.call(rosterMount.querySelectorAll(".roster-row"), el=>{
      el.addEventListener("click", ()=>openPatientNotes(rosterMount, el.getAttribute("data-id"), renderRoster));
    });
    // Edit/Remove live inside the clickable row, so they must swallow the click
    // (otherwise they'd also open the patient's notes underneath).
    Array.prototype.forEach.call(rosterMount.querySelectorAll(".roster-edit"), btn=>{
      btn.addEventListener("click", e=>{ e.stopPropagation(); openEditPatient(btn.getAttribute("data-id")); });
    });
    Array.prototype.forEach.call(rosterMount.querySelectorAll(".roster-del"), btn=>{
      btn.addEventListener("click", e=>{
        e.stopPropagation();
        confirmRemovePatient(btn.getAttribute("data-id"), btn.getAttribute("data-name"), parseInt(btn.getAttribute("data-notes"),10)||0);
      });
    });
  }

  function confirmRemovePatient(patientId, name, noteCount){
    openOverlay("Remove patient");
    const notesWarning = noteCount
      ? '<strong>'+esc(name)+'</strong> has <strong>'+noteCount+' saved note'+(noteCount===1?"":"s")+'</strong>. Removing this patient permanently deletes the patient and every one of those notes. This cannot be undone.'
      : 'This permanently removes <strong>'+esc(name)+'</strong>. This cannot be undone.';
    modalBody.innerHTML=
      '<div class="danger-note">'+notesWarning+'</div>'+
      '<div class="modal-actions"><button class="btn btn-ghost" id="rmCancel">Cancel</button><button class="btn btn-danger" style="width:auto;margin:0" id="rmConfirm">Delete permanently</button></div>';
    $("rmCancel").addEventListener("click", closeOverlay);
    $("rmConfirm").addEventListener("click", async ()=>{
      const b=$("rmConfirm"); b.disabled=true; b.textContent="Removing…";
      try{
        await deletePatient(patientId);
        // If the removed patient was the one selected on the Home page, rebuild
        // Home's state so it doesn't keep pointing at a patient that's gone.
        const wasCurrent = currentPatient===patientId;
        await loadPatients();
        if(wasCurrent){
          const ids=Object.keys(PATIENTS_BY_ID);
          currentPatient = ids.length ? ids[0] : null;
          populatePatientSelect();
          if(currentPatient){ await onPatientChange(); }
          else { setHasPatient(false); $("pName").textContent="No patients yet"; $("pSub").textContent="Click + New to add one"; $("pAvatar").textContent="—"; resetOutput(); }
        } else {
          populatePatientSelect();
        }
        closeOverlay();
        renderRoster();
        toast(firstName(name)+" removed");
      }catch(err){
        b.disabled=false; b.textContent="Delete permanently";
        toast("Couldn't remove — try again.");
      }
    });
  }

  // ---------- Status page ----------
  const statusMount=$("statusMount");
  $("statusRefresh").addEventListener("click", renderStatus);

  async function renderStatus(){
    statusMount.innerHTML='<div class="loadwrap"><span class="spin"></span></div>';
    let data;
    try{
      const r=await fetch("/api/status");
      if(!r.ok) throw new Error();
      data=await r.json();
    }catch(err){
      statusMount.innerHTML='<div class="files-empty">Couldn\'t load status just now.</div>';
      return;
    }
    // Version first. It is the thing you read out loud when reporting a problem, and the thing
    // the updater compares against — so it belongs at the top of Status, not buried in an About box.
    let h='';
    if(data.version){
      h+='<div class="status-item"><span class="status-dot ok"></span>'
        +'<div class="status-meta"><span class="status-name">Cadence '+esc(data.version)+'</span>'
        +'<span class="status-detail">Every note you save records the version that wrote it.</span></div>'
        +'<span class="status-badge ok">Installed</span></div>';
    }
    h='<div class="status-list">'+h;
    (data.integrations||[]).forEach(it=>{
      const cls=it.ready?"ok":"bad";
      h+='<div class="status-item">'+
         '<span class="status-dot '+cls+'"></span>'+
         '<div class="status-meta"><span class="status-name">'+esc(it.name)+'</span><span class="status-detail">'+esc(it.detail)+'</span></div>'+
         '<span class="status-badge '+cls+'">'+(it.ready?"Ready":"Not ready")+'</span>'+
         '</div>';
    });
    h+='</div>';
    statusMount.innerHTML=h;
  }

  // ---------- Templates page ----------
  const templatesMount=$("templatesMount");
  let currentTpl=null; // template selected in the Templates tab

  // Re-pull the form set after any template create/edit/delete so the Home note-type
  // dropdown and the live outline reference reflect it without a page reload. If the
  // Home selection was deleted, fall back to the first form; if the currently-shown
  // reference (no note generated yet) is for an edited form, refresh it in place.
  async function refreshFormsUI(){
    const prevForm=currentForm;
    await loadForms();
    if(!FORMS_BY_ID[currentForm]) currentForm = FORMS_LIST.length ? FORMS_LIST[0].id : null;
    populateFormSelect();
    if(!lastResult){
      if(currentForm!==prevForm) onFormChange();
      else resetOutput();
    }
  }

  $("tplNewBtn").addEventListener("click", openNewTemplate);

  async function renderTemplates(){
    if(!FORMS_LIST.length) await loadForms();
    if(!currentTpl || !FORMS_BY_ID[currentTpl]){
      currentTpl = (currentForm && FORMS_BY_ID[currentForm]) ? currentForm : (FORMS_LIST[0] && FORMS_LIST[0].id) || null;
    }
    templatesMount.innerHTML='<div class="tpl-wrap"><div class="tpl-list" id="tplList"></div><div class="tpl-detail card" id="tplDetail"></div></div>';
    renderTplList();
    if(currentTpl) showTemplate(currentTpl);
  }

  function tplPick(f){
    const active=f.id===currentTpl?" active":"";
    const dot=f.customized?'<span class="tpl-dot" title="Edited from the shipped default"></span>':"";
    return '<button class="tpl-pick'+active+'" data-id="'+esc(f.id)+'"><span class="tpl-pick-name">'+esc(f.name)+'</span><span class="tpl-pick-meta">'+esc(f.mode)+dot+'</span></button>';
  }
  function renderTplList(){
    const list=$("tplList"); if(!list) return;
    const builtins=FORMS_LIST.filter(f=>f.builtin);
    const customs=FORMS_LIST.filter(f=>!f.builtin);
    let h='<div class="tpl-list-group">Built-in</div>';
    builtins.forEach(f=>{ h+=tplPick(f); });
    h+='<div class="tpl-list-group">Your templates</div>';
    if(customs.length){ customs.forEach(f=>{ h+=tplPick(f); }); }
    else { h+='<div class="tpl-list-empty">None yet — “+ New template” or Duplicate one.</div>'; }
    list.innerHTML=h;
    Array.prototype.forEach.call(list.querySelectorAll(".tpl-pick"), el=>{
      el.addEventListener("click", ()=>{ currentTpl=el.getAttribute("data-id"); renderTplList(); showTemplate(currentTpl); });
    });
  }

  function tplModeDesc(mode){
    return mode==="require"
      ? "Require mode — all applicable fields expected; missing ones are flagged, never invented."
      : "Omit mode — includes only what you mention.";
  }

  function showTemplate(id){
    const f=FORMS_BY_ID[id], d=$("tplDetail"); if(!f||!d) return;
    const tags='<span class="tpl-tag '+(f.builtin?"builtin":"custom")+'">'+(f.builtin?"Built-in":"Custom")+'</span>'+(f.customized?'<span class="tpl-tag edited">Edited</span>':"");
    let actions='<button class="btn btn-ghost btn-sm" id="tplEdit">Edit outline</button>'
      +'<button class="btn btn-ghost btn-sm" id="tplDup">Duplicate</button>';
    if(f.builtin && f.customized) actions+='<button class="btn btn-ghost btn-sm" id="tplReset">Reset to default</button>';
    if(!f.builtin) actions+='<button class="btn btn-ghost btn-sm tpl-danger" id="tplDel">Delete</button>';
    const outline = (f.spec && f.spec.trim())
      ? '<pre class="tpl-outline">'+esc(f.spec)+'</pre>'
      : '<div class="tpl-empty-outline">This template’s outline didn’t load. If you just updated Cadence, <strong>restart the server</strong> so it picks up template changes, then reload this page.</div>';
    d.innerHTML='<div class="tpl-detail-head"><div class="tpl-detail-name">'+esc(f.name)+'</div><div class="tpl-detail-tags">'+tags+'</div></div>'
      +'<p class="tpl-detail-mode">'+esc(tplModeDesc(f.mode))+'</p>'
      +'<div class="tpl-actions">'+actions+'</div>'
      +outline;
    $("tplEdit").addEventListener("click", ()=>editTemplate(id));
    $("tplDup").addEventListener("click", ()=>doDuplicate(id));
    const rs=$("tplReset"); if(rs) rs.addEventListener("click", ()=>doReset(id));
    const dl=$("tplDel"); if(dl) dl.addEventListener("click", ()=>confirmDeleteTemplate(id));
  }

  function editTemplate(id){
    const f=FORMS_BY_ID[id], d=$("tplDetail"); if(!f||!d) return;
    let head;
    if(f.builtin){
      head='<p class="tpl-edit-note">Built-in template — its name, mode, and carry-forward behavior are fixed; you’re editing the outline the model fills. Use “Reset to default” anytime to restore the shipped version.</p>';
    } else {
      head='<div class="mfield"><label>Template name</label><input id="tplName" autocomplete="off"></div>'
        +'<div class="mfield"><label>Completeness mode</label><select id="tplMode"><option value="require">Require — flag missing fields</option><option value="omit">Omit — only what’s mentioned</option></select></div>';
    }
    d.innerHTML='<div class="tpl-detail-head"><div class="tpl-detail-name">Editing · '+esc(f.name)+'</div></div>'
      +head
      +'<label class="tpl-edit-label">Outline</label>'
      +'<textarea class="tpl-edit" id="tplSpec" spellcheck="false"></textarea>'
      +'<p class="tpl-edit-hint">This outline is exactly what the local model is told to produce — keep section labels clear. Every generated note is still clinician-reviewed.</p>'
      +'<div class="tpl-actions"><button class="btn btn-save" id="tplSave">Save</button><button class="btn btn-ghost btn-sm" id="tplCancel">Cancel</button></div>';
    $("tplSpec").value=f.spec||"";
    if(!f.builtin){ $("tplName").value=f.name||""; $("tplMode").value=f.mode||"require"; }
    $("tplCancel").addEventListener("click", ()=>showTemplate(id));
    $("tplSave").addEventListener("click", ()=>doSaveTemplate(id));
  }

  async function doSaveTemplate(id){
    const f=FORMS_BY_ID[id];
    const spec=($("tplSpec").value||"").trim();
    if(!spec){ $("tplSpec").focus(); $("tplSpec").style.borderColor="#cf4631"; setTimeout(()=>$("tplSpec").style.borderColor="",1200); return; }
    const payload={spec};
    if(f && !f.builtin){ payload.name=($("tplName").value||"").trim()||f.name; payload.mode=$("tplMode").value; }
    const btn=$("tplSave"); btn.disabled=true;
    try{
      await saveTemplate(id, payload);
      await refreshFormsUI();
      currentTpl=id; renderTplList(); showTemplate(id);
      toast("Template saved");
    }catch(err){ btn.disabled=false; toast((err&&err.message)||"Couldn’t save the template."); }
  }

  async function doDuplicate(id){
    try{
      const created=await duplicateTemplate(id);
      await refreshFormsUI();
      currentTpl=created.id; renderTplList(); showTemplate(created.id);
      toast('Duplicated as “'+created.name+'”');
    }catch(err){ toast("Couldn’t duplicate the template."); }
  }

  function doReset(id){
    const actions=$("tplDetail").querySelector(".tpl-actions"); if(!actions) return;
    actions.innerHTML='<span class="confirm-inline">Discard your edits and restore the original outline? <button class="btn btn-danger btn-sm" id="tplResetYes">Reset</button> <button class="btn btn-ghost btn-sm" id="tplResetNo">Cancel</button></span>';
    $("tplResetNo").addEventListener("click", ()=>showTemplate(id));
    $("tplResetYes").addEventListener("click", async ()=>{
      try{ await resetTemplate(id); await refreshFormsUI(); currentTpl=id; renderTplList(); showTemplate(id); toast("Reset to the shipped default"); }
      catch(err){ toast("Couldn’t reset the template."); }
    });
  }

  function confirmDeleteTemplate(id){
    const f=FORMS_BY_ID[id];
    const actions=$("tplDetail").querySelector(".tpl-actions"); if(!actions||!f) return;
    actions.innerHTML='<span class="confirm-inline">Delete “'+esc(f.name)+'” permanently? <button class="btn btn-danger btn-sm" id="tplDelYes">Delete</button> <button class="btn btn-ghost btn-sm" id="tplDelNo">Cancel</button></span>';
    $("tplDelNo").addEventListener("click", ()=>showTemplate(id));
    $("tplDelYes").addEventListener("click", async ()=>{
      try{
        await deleteTemplate(id);
        await refreshFormsUI();
        currentTpl = (currentForm && FORMS_BY_ID[currentForm]) ? currentForm : (FORMS_LIST[0] && FORMS_LIST[0].id) || null;
        renderTplList(); if(currentTpl) showTemplate(currentTpl);
        toast("Template deleted");
      }catch(err){ toast("Couldn’t delete the template."); }
    });
  }

  function openNewTemplate(){
    openOverlay("New template");
    modalBody.innerHTML=
      '<div class="mfield"><label>Template name</label><input id="ntName" placeholder="e.g. Telehealth Follow-Up" autocomplete="off"></div>'+
      '<div class="mfield"><label>Completeness mode</label><select id="ntMode"><option value="require">Require — flag missing fields (clinical / billing notes)</option><option value="omit">Omit — include only what’s mentioned</option></select></div>'+
      '<div class="mfield"><label>Outline</label><textarea id="ntSpec" rows="10" spellcheck="false" placeholder="List the sections the note should contain — e.g.&#10;Sections in order: Subjective; Objective; Assessment; Plan."></textarea><p class="mic-help-sm">This outline is what the model fills; refine it anytime in the Templates tab. Custom templates don’t carry forward from prior visits (yet).</p></div>'+
      '<div class="modal-actions"><button class="btn btn-ghost" id="ntCancel">Cancel</button><button class="btn btn-primary" style="width:auto;margin:0" id="ntSave">Create template</button></div>';
    $("ntName").focus();
    $("ntCancel").addEventListener("click", closeOverlay);
    $("ntSave").addEventListener("click", async ()=>{
      const name=($("ntName").value||"").trim(), spec=($("ntSpec").value||"").trim();
      if(!name){ $("ntName").focus(); $("ntName").style.borderColor="#cf4631"; setTimeout(()=>$("ntName").style.borderColor="",1200); return; }
      if(!spec){ $("ntSpec").focus(); $("ntSpec").style.borderColor="#cf4631"; setTimeout(()=>$("ntSpec").style.borderColor="",1200); return; }
      const b=$("ntSave"); b.disabled=true;
      try{
        const created=await createTemplate({name, mode:$("ntMode").value, spec});
        await refreshFormsUI();
        currentTpl=created.id;
        closeOverlay();
        showPage("templates");
        toast('Created “'+created.name+'”');
      }catch(err){ b.disabled=false; toast((err&&err.message)||"Couldn’t create the template."); }
    });
  }

  // ---------- Evals page ----------
  // Two-step by design: "Generate samples" is instant and shows the gold labels, so you can see
  // what the generator produced BEFORE committing tens of minutes of CPU to sweeping it.
  // Progress is POLLED rather than streamed — a sweep must survive a page reload, and a small
  // status object every 2s is resumable for free.
  const evalsMount=$("evalsMount");
  let evalOpts=null, evalSamples=[], evalPoll=null, evalRunId=null;

  function renderEvals(){
    if(evalPoll){ clearInterval(evalPoll); evalPoll=null; }
    evalsMount.innerHTML='<div class="loadwrap"><span class="spin"></span></div>';
    fetch("/api/evals/options").then(r=>{
      if(!r.ok) throw new Error();
      return r.json();
    }).then(o=>{ evalOpts=o; drawEvalForm(); }).catch(()=>{
      evalsMount.innerHTML='<div class="files-empty">The evals tools aren\'t available in this install.</div>';
    });
  }

  function sel(id,label,values,current){
    let h='<div class="field"><label for="'+id+'">'+esc(label)+'</label><select id="'+id+'">';
    values.forEach(v=>{ h+='<option value="'+esc(v)+'"'+(v===current?" selected":"")+">"+esc(v)+"</option>"; });
    return h+"</select></div>";
  }

  function drawEvalForm(){
    let h='<div class="controls">'
      +sel("evBodyPart","Body part",evalOpts.body_parts,evalOpts.body_parts[0])
      +sel("evNoteType","Note type",evalOpts.note_types,"followup")
      +sel("evComplexity","Complexity",evalOpts.complexities,"medium")
      +'<div class="field"><label for="evCount">Samples</label><input id="evCount" type="number" min="1" max="200" value="10"></div>'
      +'<div class="field"><label for="evSeed">Seed</label><input id="evSeed" type="number" value="1234"></div>'
      +'</div>';
    const unver=evalOpts.unverified_body_parts||[];
    if(unver.length){
      h+='<div class="needs"><h3>ICD tables not yet verified</h3><p style="margin:0;font-size:13px">The ICD-10 tables for <b>'+esc(unver.join(", "))+'</b> in <code>app/generate/coding_tables.py</code> have not been signed off by a clinician or certified coder (ICD-10-CM '+esc(evalOpts.icd10cm_year)+'). ICD scores below are still meaningful as a measure of <em>detection</em>, but the codes themselves must be reviewed before any of this is used on a real claim. Regions are independent — sign off the ones the practice actually sees first.</p></div>';
    }
    h+='<div class="savebar"><button class="btn btn-ghost" id="evGenBtn">Generate samples</button>'
      +'<button class="btn btn-primary" id="evRunBtn">Run sweep</button>'
      +'<label class="evchk"><input type="checkbox" id="evControl" checked> include hand-written control set</label>'
      +'<span class="savehint" id="evHint">Generate samples first to see what will be tested.</span></div>'
      +'<div id="evBody"></div>';
    evalsMount.innerHTML=h;
    $("evGenBtn").addEventListener("click", genEvalSamples);
    $("evRunBtn").addEventListener("click", startEvalRun);
  }

  function evalConfig(){
    return {
      body_part:$("evBodyPart").value, note_type:$("evNoteType").value,
      complexity:$("evComplexity").value,
      count:Math.max(1,parseInt($("evCount").value,10)||10),
      seed:parseInt($("evSeed").value,10)||1234,
    };
  }

  async function genEvalSamples(){
    $("evHint").textContent="Generating…";
    const r=await fetch("/api/evals/samples",{method:"POST",headers:{"Content-Type":"application/json"},
      body:JSON.stringify(evalConfig())});
    if(!r.ok){ $("evHint").textContent="Couldn't generate samples."; return; }
    const data=await r.json();
    evalSamples=data.samples||[];
    $("evHint").textContent=evalSamples.length+" samples ready — review, then Run sweep.";
    let h='<div class="billing"><h3>Generated samples <span class="bhint">— fake sessions with their correct answers</span></h3>';
    evalSamples.forEach(s=>{
      h+='<div class="evsample"><p class="evtx">'+esc(s.transcript)+'</p><p class="evgold">'
        +'<b>Should find:</b> '+esc((s.icd_codes||[]).join(", ")||"no ICD")+' · '
        +esc((s.interventions||[]).map(i=>i.code+(i.minutes!=null?" "+i.minutes+"m":"")).join(", "))
        +' · <b>'+s.total_timed_minutes+' timed min = '+s.expected_units+' units</b>'
        +(s.expected_units_ama!==s.expected_units?' (AMA: '+s.expected_units_ama+')':'')
        +'<br><b>Should NOT bill:</b> '+esc((s.distractors||[]).map(d=>d.code+" ("+d.reason+")").join(", ")||"—")
        +'</p></div>';
    });
    $("evBody").innerHTML=h+"</div>";
  }

  async function startEvalRun(){
    const cfg=evalConfig();
    cfg.include_handwritten=$("evControl").checked;
    const r=await fetch("/api/evals/runs",{method:"POST",headers:{"Content-Type":"application/json"},
      body:JSON.stringify(cfg)});
    if(r.status===409){ $("evHint").textContent="A sweep is already running — one at a time."; return; }
    if(!r.ok){ $("evHint").textContent="Couldn't start the sweep."; return; }
    const job=await r.json();
    evalRunId=job.run_id;
    if(evalPoll) clearInterval(evalPoll);
    evalPoll=setInterval(pollEvalRun, 2000);
    pollEvalRun();
  }

  function fmtEta(s){
    if(!s) return "";
    const m=Math.round(s/60);
    return m>=1 ? ("~"+m+" min left") : ("~"+Math.round(s)+"s left");
  }

  async function pollEvalRun(){
    if(!evalRunId) return;
    const r=await fetch("/api/evals/runs/"+encodeURIComponent(evalRunId));
    if(!r.ok) return;
    const j=await r.json();
    const a=j.partial_aggregate||{};
    let h='<div class="billing"><h3>Sweep '+esc(j.run_id)+' <span class="bhint">— '+esc(j.status)+'</span>'
      +(j.status==="running"?' <button class="btn btn-ghost btn-sm" id="evCancel">Stop</button>':'')+'</h3>'
      +'<p class="bunits"><b>'+j.done+' / '+j.total+'</b> generations · '+esc(j.current_record||"")
      +' · '+fmtEta(j.eta_seconds)+'</p>';
    if(j.error) h+='<p class="bmissing">⌖ '+esc(j.error)+'</p>';
    if(a.records){
      // Safety numbers first: a leak is a wrong claim, an accuracy dip is only an incomplete draft.
      const unsafe=(a.distractor_leaks||0)+(a.untimed_leaks||0)+(a.laterality_errors||0)+(a.minutes_fabricated||0);
      h+='<p class="bsub">Wrong claims (must be zero)</p><p class="'+(unsafe?"bmissing":"bunits")+'">'
        +(a.distractor_leaks||0)+' billed something the therapist said was not done today · '
        +(a.untimed_leaks||0)+' untimed minutes counted · '
        +(a.laterality_errors||0)+' wrong-side diagnosis · '
        +(a.minutes_fabricated||0)+' invented durations</p>';
      const pct=v=>v==null?"n/a":Math.round(v*100)+"%";
      h+='<p class="bsub">Accuracy</p><ul>'
        +'<li>Treatment codes: '+pct(a.cpt_detection_recall)+' found, '+pct(a.cpt_detection_precision)+' correct</li>'
        +'<li>Diagnosis codes: '+pct(a.icd_recall)+' found, '+pct(a.icd_precision)+' correct</li>'
        +'<li>Minutes: '+pct(a.minutes_exact)+' exact ('+pct(a.minutes_within_2)+' within 2 min), '
        +(a.minutes_not_extracted||0)+' left as a gap for the clinician</li>'
        +'<li>Units: '+pct(a.units_exact)+' exact · CMS and AMA disagreed on '+(a.method_disagreements||0)+'</li>'
        +'</ul>';
    }
    if(j.results_file) h+='<p class="bnote">Saved to evals/results/'+esc(j.results_file)+'</p>';
    h+='</div>';
    $("evBody").innerHTML=h;
    const c=$("evCancel");
    if(c) c.addEventListener("click", ()=>fetch("/api/evals/runs/"+encodeURIComponent(evalRunId)+"/cancel",{method:"POST"}));
    if(j.status!=="running"){ clearInterval(evalPoll); evalPoll=null; }
  }

  // ---------- Nav ----------
  const PAGES={home:$("page-home"), patients:$("page-patients"), templates:$("page-templates"), evals:$("page-evals"), status:$("page-status")};
  let currentPage="home";
  function showPage(name){
    if(!PAGES[name]) return;
    currentPage=name;
    Object.keys(PAGES).forEach(k=>PAGES[k].classList.toggle("hidden", k!==name));
    Array.prototype.forEach.call(document.querySelectorAll(".nav-tab"), t=>{
      t.classList.toggle("active", t.getAttribute("data-page")===name);
    });
    if(name==="patients") renderRoster();
    else if(name==="templates") renderTemplates();
    else if(name==="evals") renderEvals();
    else if(name==="status") renderStatus();
  }
  Array.prototype.forEach.call(document.querySelectorAll(".nav-tab"), t=>{
    t.addEventListener("click", ()=>showPage(t.getAttribute("data-page")));
  });

  // ---------- Init ----------
  async function init(){
    await Promise.all([loadForms(), loadPatients()]);
    const ids=Object.keys(PATIENTS_BY_ID);
    currentPatient = ids.length ? ids[0] : null;
    currentForm = FORMS_LIST.length ? FORMS_LIST[0].id : null;
    populatePatientSelect();
    populateFormSelect();
    if(currentPatient){ await onPatientChange(); }
    else { setHasPatient(false); $("pName").textContent="No patients yet"; $("pSub").textContent="Click + New to add one"; }
    if(currentForm) onFormChange();
    // Reattach to anything the server is still writing. This is what makes a reload (or a closed
    // and reopened browser) a non-event rather than seven lost minutes.
    const rows=await refreshTray();
    if(rows.length) ensureTrayPolling();
    const live=rows.find(r=>r.status==="running"||r.status==="queued");
    if(live && live.patient_id===currentPatient){
      startGenLive({name: live.form_name}, live.elapsed_seconds);
      attachJob(live.id);
    }
  }
  init();
})();
