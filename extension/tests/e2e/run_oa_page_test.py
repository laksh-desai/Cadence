"""End-to-end test of the Cadence → Office Ally extension against a REAL saved Office Ally page.

Unit tests prove the routing logic; this proves the extension works on Office Ally's actual page:
the real, unmodified content.js / oaroute.js / mapping.js run in headless Chrome against a page
saved from Office Ally, and the test reads back exactly what landed in each Office Ally box.

How it works:
  * The saved page's own <script> tags are removed — they would call Office Ally's servers (its
    session keep-alive redirects to a login page when it can't reach them). Its markup, field ids,
    labels, date boxes, layout dropdown and inline onclick/onkeyup handlers are kept.
  * Office Ally's own CheckMaxLength (which TRUNCATES a box at its limit) is re-created, so a box
    over 2,000 characters would be visibly cut and the test would catch it.
  * `chrome.runtime` is replaced by a fake Cadence answering with the scenario's patient and note.
  * Each scenario opens the panel, waits for the checks, clicks Fill until it finishes, and
    reports the panel status, the checks, every box's value, the encounter date, and whether
    Office Ally's Apply (save draft) was clicked.

The saved page holds real patient details and session tokens, so it is NEVER committed: it lives
in the git-ignored evals/Ingestion/ folder, and this test is skipped when it isn't there.

    .venv/Scripts/python.exe extension/tests/e2e/run_oa_page_test.py
"""

from __future__ import annotations

import functools
import http.server
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
EXT = ROOT / "extension"
INGEST = ROOT / "evals" / "Ingestion"          # private, git-ignored pages saved from Office Ally
FIXTURES = EXT / "tests" / "fixtures"          # clean templates made by scripts/make_oa_template.py
# Real Office Ally note forms. The private saved pages are used when present (full fidelity); the
# committed templates otherwise, or always with E2E_FIXTURES=1.
PAGES = {
    "progress": [INGEST / "OfficeAlly_ProgressNotes.html", FIXTURES / "oa_progress_notes.html"],
    "init_eval": [INGEST / "OfficeAlly_Initial_Eval.html", FIXTURES / "oa_cadence_init_eval.html"],
}


def page_file(kind):
    paths = PAGES[kind][1:] if os.environ.get("E2E_FIXTURES") else PAGES[kind]
    return next((p for p in paths if p.exists()), None)


CHROME_CANDIDATES = [
    Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
    Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
]
PREFIX = "ctl00_phFolderContent_ucSOAPNote_"
def _page_pid() -> str:
    f = page_file("progress")
    m = f and re.search(r'lblPatientID"[^>]*>(\d+)', f.read_text(encoding="utf-8", errors="replace"))
    return m.group(1) if m else "100000001"


PAGE_PID = _page_pid()   # the Patient ID on the page under test


# ---- Notes the fake Cadence hands to the extension (made-up clinical content, not a real visit) --

FOLLOWUP_SECTIONS = [
    ("Summary of Daily Skilled Services", "Skilled PT for left knee strength and gait deficits following left total knee arthroplasty."),
    ("Precautions", "Weight-bearing as tolerated on the left leg."),
    ("Therapeutic Exercise", "Minutes: 20. Quad sets, straight leg raises and mini-squats, 3 x 10, verbal cues for knee extension."),
    ("Gait Training", "Minutes: 15. Rolling walker, 150 ft x 2, cues for heel strike and step length."),
    ("Pain - At Rest", "2/10."),
    ("Pain - With Movement", "4/10 with stairs."),
    ("Vitals", "BP 128/76, HR 72."),
    ("Response to Treatment", "Good; tolerated the full session without increased swelling."),
    ("Functional Status", "Ambulates 150 ft with rolling walker, contact guard assist; 4 steps with rail."),
    ("Short-Term Goals", "Walk 200 ft with rolling walker at supervision within 2 weeks — progressing."),
    ("Long-Term Goals", "Independent household ambulation without a device within 6 weeks — in progress."),
    ("Plan", "Continue 2x/week; progress strengthening and reduce assist level."),
]

INITIAL_SECTIONS = [   # the 17 sections of Cadence's Initial Evaluation template
    ("Chief Complaint", "Left knee pain and weakness four weeks after left total knee replacement."),
    ("Diagnoses", "Status post left total knee arthroplasty with deconditioning."),
    ("Medications", "Tylenol up to 3 g/day; Voltaren gel PRN; lisinopril 10 mg daily; levothyroxine 88 mcg; metformin 500 mg BID."),
    ("Allergies", "Sulfa."),
    ("Referral & Relevant History", "Referred by orthopedics. Hypertension, type 2 diabetes. Weight-bearing as tolerated."),
    ("Social History & Living Environment", "Lives alone in a single-story home, one step to enter."),
    ("Objective Summary", "Reduced left knee range and quadriceps strength limit transfers and gait."),
    ("Fall Risk", "One fall last month at home; unsteady on uneven ground."),
    ("Musculoskeletal Assessment", "Left knee AROM 5 to 90 degrees; quadriceps 3+/5."),
    ("Other Systems", "Incision clean and dry. Pain 4/10 at rest."),
    ("Cardiopulmonary", "BP 130/80, HR 74, O2 97% at rest."),
    ("Functional Mobility", "Sit to stand min assist; walks 100 ft with front-wheeled walker."),
    ("Coordination / Sensation / Edema", "Mild swelling at the left knee."),
    ("Assessment Summary", "Strength and mobility deficits limiting function; skilled PT indicated."),
    ("Short-Term Goals", "In 2 weeks, walk 200 ft with rolling walker at min assist."),
    ("Long-Term Goals", "In 6 weeks, independent household walking without a device."),
    ("Plan of Treatment", "PT 2x/week for 8 weeks, 60 minutes per session."),
]


def note(form_id, sections, visit_date, created="2026-09-28T15:12:00"):
    return {"id": "n1", "form_id": form_id,
            "form_name": {"followup": "Follow-Up Visit", "initial": "Initial Evaluation"}[form_id],
            "created_at": created, "visit_date": visit_date,
            "sections": [{"heading": h, "body": b, "carried_forward": False} for h, b in sections],
            "missing_info": []}


# ---- Scenarios -----------------------------------------------------------------------------------

LONG_ASSESSMENT = " ".join(f"Finding {i}: the patient demonstrated steady progress with the prescribed exercise program and tolerated increased load." for i in range(30))

SCENARIOS = [
    dict(name="1. Follow-Up into Progress Notes, same day (new encounter)",
         note=note("followup", FOLLOWUP_SECTIONS, "2026-09-28"), mrn=PAGE_PID,
         query="PageAction=AddNote&SoapLayoutID=361919&PID=" + PAGE_PID,
         expect=dict(filled=True, saved=True, date="9/28/2026",
                     boxes={"S_HOPI_Original": "Skilled PT for left knee", "P_Procedures": "Quad sets",
                            "O_FunctionalStatus": "Ambulates 150 ft", "P_GoalNotes": "Walk 200 ft",
                            "P_Plans": "Continue 2x/week", "A_Custom1": "tolerated the full session"})),
    dict(name="2. Follow-Up for ANOTHER day (09/29) into a new encounter → date set to 9/29",
         note=note("followup", FOLLOWUP_SECTIONS, "2026-09-29"), mrn=PAGE_PID,
         query="PageAction=AddNote&SoapLayoutID=361919&PID=" + PAGE_PID,
         expect=dict(filled=True, saved=True, date="9/29/2026", boxes={"P_Plans": "Continue 2x/week"})),
    dict(name="3. Another day into an EXISTING encounter → blocked, date not changed",
         note=note("followup", FOLLOWUP_SECTIONS, "2026-09-29"), mrn=PAGE_PID,
         query="PageAction=EditNote&EID=900000002&PID=" + PAGE_PID, title="Edit Note / Encounter [Encounter ID 900000002]",
         expect=dict(filled=False, saved=False, date="9/28/2026", status="Date mismatch")),
    dict(name="4. Initial Evaluation into the Progress Notes layout → blocked (template mismatch)",
         note=note("initial", INITIAL_SECTIONS, "2026-09-28"), mrn=PAGE_PID,
         query="PageAction=AddNote&SoapLayoutID=361919&PID=" + PAGE_PID,
         expect=dict(filled=False, saved=False, status="Template mismatch")),
    dict(name="5. Wrong patient (Cadence MRN differs from the chart) → blocked",
         note=note("followup", FOLLOWUP_SECTIONS, "2026-09-28"), mrn="999999999",
         query="PageAction=AddNote&SoapLayoutID=361919&PID=" + PAGE_PID,
         expect=dict(filled=False, saved=False, status="Wrong chart")),
    dict(name="6. A long assessment is split across boxes at sentence ends, never truncated",
         note=note("followup", FOLLOWUP_SECTIONS + [("Assessment Summary", LONG_ASSESSMENT)], "2026-09-28"), mrn=PAGE_PID,
         query="PageAction=AddNote&SoapLayoutID=361919&PID=" + PAGE_PID,
         expect=dict(filled=True, saved=True, all_text=LONG_ASSESSMENT)),
    dict(name="8. Initial Evaluation into the real Cadence Init Eval form → every section in its box, draft saved",
         page="init_eval", note=note("initial", INITIAL_SECTIONS, "2026-09-28"), mrn=PAGE_PID,
         query="PageAction=AddNote&SoapLayoutID=374261&PID=" + PAGE_PID,
         expect=dict(filled=True, saved=True, date="9/28/2026",
                     boxes={"S_ChiefComplaint": "Left knee pain", "S_Medications": "lisinopril",
                            "S_MedicalHistory": "Referred by orthopedics", "S_SocialHistory": "single-story",
                            "S_Custom3": "One fall last month", "O_Objective": "AROM 5 to 90",
                            "O_FunctionalStatus": "Sit to stand", "A_Custom1": "arthroplasty",
                            "A_Custom2": "skilled PT indicated", "P_GoalNotes": "200 ft", "P_Plans": "2x/week"},
                     not_boxes=["P_Custom1", "P_Custom2", "P_Custom3", "P_Custom4", "S_ROS_Custom1"])),
    dict(name="9. Initial Evaluation for ANOTHER day (09/27) into a new Cadence Init Eval → date set to 9/27",
         page="init_eval", note=note("initial", INITIAL_SECTIONS, "2026-09-27"), mrn=PAGE_PID,
         query="PageAction=AddNote&SoapLayoutID=374261&PID=" + PAGE_PID,
         expect=dict(filled=True, saved=True, date="9/27/2026", boxes={"A_Custom1": "arthroplasty"})),
    dict(name="10. Follow-Up into the Cadence Init Eval form → blocked (template mismatch)",
         page="init_eval", note=note("followup", FOLLOWUP_SECTIONS, "2026-09-28"), mrn=PAGE_PID,
         query="PageAction=AddNote&SoapLayoutID=374261&PID=" + PAGE_PID,
         expect=dict(filled=False, saved=False, status="Template mismatch")),
    dict(name="11. Initial Eval fill → every box read back → draft saved → after reload, saved boxes re-checked: all match",
         page="init_eval", note=note("initial", INITIAL_SECTIONS, "2026-09-28"), mrn=PAGE_PID, reverify=True,
         query="PageAction=AddNote&SoapLayoutID=374261&PID=" + PAGE_PID,
         expect=dict(filled=True, saved=True, status="all match the Cadence note", records_encounter=True,
                     after_reload="Saved and checked")),
    dict(name="12. After reload one box did not keep its text → the saved-note check FAILS and names the box",
         page="init_eval", note=note("initial", INITIAL_SECTIONS, "2026-09-28"), mrn=PAGE_PID, reverify=True,
         tamper="S_Medications", tamperText="",
         query="PageAction=AddNote&SoapLayoutID=374261&PID=" + PAGE_PID,
         expect=dict(filled=True, saved=True, after_reload="check FAILED")),
    dict(name="13. This note already went to another encounter → no extra warning (relaxed 2026-09-28), fills in one click",
         note=note("followup", FOLLOWUP_SECTIONS, "2026-09-28"), mrn=PAGE_PID,
         noteEncounter={"eid": "900000003", "pid": PAGE_PID, "filled": False, "at": 0},
         query="PageAction=AddNote&SoapLayoutID=361919&PID=" + PAGE_PID,
         expect=dict(filled=True, saved=True)),
    dict(name="7. Unrecognised layout (no known boxes) → nothing filled, nothing changed",
         note=note("followup", FOLLOWUP_SECTIONS, "2026-09-29"), mrn=PAGE_PID,
         query="PageAction=AddNote&SoapLayoutID=361919&PID=" + PAGE_PID, strip_boxes=True,
         expect=dict(filled=False, saved=False, date="9/28/2026", status="isn't set up")),
]


# ---- Harness page ----------------------------------------------------------------------------------

STUB = r"""
<script>
// Office Ally's own handlers that the saved page's markup calls (its scripts were removed).
function CheckMaxLength(obj, maxlen, labelname, mode) {           // same truncation as Office Ally
  if (mode == 0) return;
  if (obj.value.length >= maxlen) obj.value = obj.value.substring(0, maxlen);
}
window.__apply = 0;
function Apply_Click() { window.__apply++; }
function Update_Click() { window.__update = (window.__update || 0) + 1; }
function CheckIsDirty() {} function dateControlKeyCheck() { return true; } function dateControlAutoTab() { return true; }
// Fake Cadence behind chrome.runtime.
var SCEN = __SCENARIO__;
var PATIENT = { id: "p1", name: "Kushang Desai", mrn: SCEN.mrn };
window.chrome = {
  runtime: {
    lastError: undefined,
    getManifest: function () { return { version: "test" }; },
    sendMessage: function (msg, cb) {
      var data = null;
      if (msg.action === "patients") data = [PATIENT];
      else if (msg.action === "patient") data = PATIENT;
      else if (msg.action === "handoff") data = { patientId: "p1", noteId: "n1", at: Date.now() };
      else if (msg.action === "notes") data = [{ id: "n1", form_id: SCEN.note.form_id, form_name: SCEN.note.form_name, created_at: SCEN.note.created_at, visit_date: SCEN.note.visit_date }];
      else if (msg.action === "note") data = SCEN.note;
      else if (msg.action === "noteEncounterGet") data = SCEN.noteEncounter || null;
      else if (msg.action === "noteEncounterSet") window.__noteEncounterSet = msg;
      else if (msg.action === "verifyAfterSave") window.__verifyAsked = msg;
      else if (msg.action === "verifyPending") { data = window.__verifyPending || null; window.__verifyPending = null; }
      else if (msg.action === "officeSettings") data = { layouts: {
        initial: { id: "374261", name: "Cadence Init Eval" }, initial_updated: { id: "374261", name: "Cadence Init Eval" },
        followup: { id: "361919", name: "Progress Notes" } } };
      setTimeout(function () { cb({ ok: true, data: data }); }, 0);
    }
  },
  storage: { local: { get: function (k, cb) { cb({}); }, set: function (o, cb) { if (cb) cb(); } } }
};
</script>
"""

DRIVER = r"""
<script>
(async function () {
 let payload = null;
 try {
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const shadow = () => document.getElementById("cadence-oa-host").shadowRoot;
  const status = () => shadow().getElementById("coStatus").textContent;
  // Wait for the panel to load the patient + note and run its checks.
  for (let i = 0; i < 60 && !/Check where each section|Wrong chart|Template mismatch|Date mismatch|isn't set up|No Office Ally|not logged/i.test(status()); i++) await sleep(100);
  const before = status();
  // Click Fill until it finishes (the "?" encounter-list check and gaps each take one extra click).
  for (let i = 0; i < 4; i++) {
    shadow().getElementById("coFill").click();
    await sleep(700);
    if (/Filled|Nothing was filled|mismatch|Wrong chart|isn't set up/i.test(status())) break;
  }
  await sleep(1600); // the draft save fires 1.2 s after a clean fill
  const boxes = {};
  document.querySelectorAll('textarea[id*="ucSOAPNote_"]').forEach((t) => { if (t.value.trim()) boxes[t.id.replace(/^.*ucSOAPNote_/, "")] = t.value; });
  const g = (id) => (document.getElementById("__PREFIX__EncounterDate_" + id) || {}).value;
  const checks = Array.from(shadow().querySelectorAll(".co-check span")).map((s) => s.textContent.trim());
  const out = { before: before, status: status(), checks: checks, boxes: boxes,
    date: g("Month") + "/" + g("Day") + "/" + g("Year"), apply: window.__apply,
    encounterRecorded: window.__noteEncounterSet || null, verifyAsked: !!window.__verifyAsked };
  // Simulate the reload after Office Ally's Apply: the saved text is still in the boxes (or, with
  // SCEN.tamper, one box came back different), and the panel reopens on the same note.
  if (SCEN.reverify && window.__verifyAsked) {
    if (SCEN.tamper) {
      const t = document.querySelector('textarea[id$="ucSOAPNote_' + SCEN.tamper + '"]');
      if (t) t.value = SCEN.tamperText || "";
    }
    window.__cadenceOA.close();
    window.__verifyPending = { patientId: "p1", noteId: "n1", at: Date.now() };
    (0, eval)(window.__contentSrc);
    for (let i = 0; i < 60 && !/Saved and checked|check FAILED/i.test(status()); i++) await sleep(100);
    out.statusAfterReload = status();
    out.checksAfterReload = Array.from(shadow().querySelectorAll(".co-check span")).map((s) => s.textContent.trim());
  }
  payload = { result: out };
 } catch (err) {
  payload = { error: String(err && err.stack || err) };
 }
 // Report straight to the test server; the runner then closes Chrome itself.
 await fetch("/result?id=" + encodeURIComponent(location.pathname), { method: "POST", body: JSON.stringify(payload) }).catch(() => {});
})();
</script>
"""


def build_page(src_html: str, scen: dict) -> str:
    html = re.sub(r"<script\b[^>]*>.*?</script>", "", src_html, flags=re.S | re.I)   # Office Ally's JS
    html = re.sub(r"<script\b[^>]*/>", "", html, flags=re.I)
    html = re.sub(r"<link\b[^>]*>", "", html, flags=re.I)                             # external CSS
    html = re.sub(r'(<iframe\b[^>]*?)\ssrc="[^"]*"', r'\1 src="about:blank"', html, flags=re.I)
    if scen.get("title"):
        html = re.sub(r'(id="' + PREFIX + r'lblTitle"[^>]*>)[^<]*', r"\g<1>" + scen["title"], html)
    if scen.get("strip_boxes"):
        html = re.sub(r'<textarea\b[^>]*id="[^"]*ucSOAPNote_[SOAP]_[^"]*"[^>]*>.*?</textarea>', "", html, flags=re.S | re.I)
    libs = "".join("<script>\n" + (EXT / p).read_text(encoding="utf-8") + "\n</script>\n"
                   for p in ("lib/mapping.js", "lib/oaroute.js", "content.js"))
    content_src = json.dumps((EXT / "content.js").read_text(encoding="utf-8")).replace("</", "<\\/")
    keep = "<script>window.__contentSrc = " + content_src + ";</script>\n"   # re-run for the simulated reload
    inject = STUB.replace("__SCENARIO__", json.dumps(scen)) + libs + keep + DRIVER.replace("__PREFIX__", PREFIX)
    return html.replace("</body>", inject + "</body>") if "</body>" in html else html + inject


def run_chrome(chrome: Path, url: str, profile: Path, got: threading.Event, timeout: float = 45) -> None:
    """Open the scenario page in headless Chrome and wait until its driver POSTs the result.

    The result travels over HTTP to the test server, so the run never depends on Chrome finishing
    a page dump or shutting down cleanly (both hung intermittently on this machine). Chrome is
    killed — whole process tree — as soon as the result arrives or the wait times out.
    """
    cmd = [str(chrome), "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
           f"--user-data-dir={profile}",
           # No network except the local test server: the saved page still names Office Ally's
           # servers, and the test must never contact them.
           "--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1",
           "--disable-background-networking", "--disable-component-update", "--disable-sync",
           "--disable-default-apps", "--disable-extensions", "--no-pings", "--metrics-recording-only",
           # A hidden headless page can be treated as a background tab and left paused mid-parse,
           # so the test driver never runs. Keep the page fully awake.
           "--disable-renderer-backgrounding", "--disable-background-timer-throttling",
           "--disable-backgrounding-occluded-windows", "--disable-ipc-flooding-protection",
           "--disable-features=Translate,OptimizationHints,MediaRouter,AutofillServerCommunication",
           url]
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        got.wait(timeout=timeout)
    finally:
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True)
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            pass


def check(scen: dict, res: dict) -> list[str]:
    e, fails = scen["expect"], []
    filled_any = bool(res["boxes"])
    if e.get("filled") is not None and filled_any != e["filled"]:
        fails.append(f"expected filled={e['filled']}, got boxes={list(res['boxes'])}")
    if e.get("saved") is not None and bool(res["apply"]) != e["saved"]:
        fails.append(f"expected draft saved={e['saved']}, Apply clicked {res['apply']} time(s)")
    if e.get("date") and res["date"] != e["date"]:
        fails.append(f"expected encounter date {e['date']}, got {res['date']}")
    if e.get("status") and e["status"].lower() not in res["status"].lower():
        fails.append(f"expected status to mention '{e['status']}'")
    for key, snippet in (e.get("boxes") or {}).items():
        if snippet not in res["boxes"].get(key, ""):
            fails.append(f"box {key} should contain '{snippet}', has: {res['boxes'].get(key, '')[:80]!r}")
    for key in e.get("not_boxes") or []:
        if key in res["boxes"]:
            fails.append(f"box {key} should be empty, has: {res['boxes'][key][:80]!r}")
    for key, val in res["boxes"].items():
        if len(val) + val.count("\n") > 2000:
            fails.append(f"box {key} is over 2,000 characters ({len(val)})")
    for want in e.get("checks_include") or []:
        if not any(want.lower() in c.lower() for c in res.get("checks") or []):
            fails.append(f"expected a check mentioning '{want}', got {res.get('checks')}")
    if e.get("after_reload") and e["after_reload"].lower() not in (res.get("statusAfterReload") or "").lower():
        fails.append(f"after the save/reload expected status '{e['after_reload']}', got {(res.get('statusAfterReload') or '')[:200]!r}")
    if e.get("records_encounter") and not (res.get("encounterRecorded") or {}).get("eid"):
        fails.append("the note's Office Ally encounter was not remembered")
    if e.get("all_text"):
        joined = " ".join(res["boxes"].values())
        for sentence in re.findall(r"[^.]+\.", e["all_text"]):
            if sentence.strip() not in joined:
                fails.append(f"lost or cut: {sentence.strip()[:60]!r}")
                break
    return fails


def main() -> int:
    if not page_file("progress"):
        print(f"SKIPPED: no saved Office Ally page in {INGEST}")
        return 0
    chrome = next((c for c in CHROME_CANDIDATES if c.exists()), None)
    if not chrome:
        print("SKIPPED: no Chrome or Edge found for headless testing")
        return 0
    sources = {k: page_file(k).read_text(encoding="utf-8", errors="replace") for k in PAGES if page_file(k)}
    work = Path(tempfile.mkdtemp(prefix="cadence_e2e_"))
    profile = work / "profile"
    results: dict[str, dict] = {}
    events: dict[str, threading.Event] = {}
    lock = threading.Lock()

    def event_for(key):
        with lock:
            return events.setdefault(key, threading.Event())

    class Quiet(http.server.SimpleHTTPRequestHandler):
        # HTTP/1.1 (keep-alive), not the default 1.0. With 1.0 every request needs a fresh
        # connection, and on this machine Chrome and Edge intermittently stalled on those: the
        # page arrived in full but never finished loading, so about half the scenarios never ran.
        # Measured: 1.0 -> 2 of 8 runs completed; 1.1 -> 8 of 8.
        protocol_version = "HTTP/1.1"
        extensions_map = {**http.server.SimpleHTTPRequestHandler.extensions_map, ".html": "text/html; charset=utf-8"}

        def log_message(self, fmt, *a):  # the page's Office Ally images 404 here; that is expected
            if os.environ.get("E2E_DEBUG"):
                sys.stderr.write("[http] " + (fmt % a) + "\n")

        def handle(self):
            try:
                super().handle()
            except ConnectionResetError:   # Chrome is killed with idle connections open: expected
                pass

        def do_POST(self):
            from urllib.parse import urlparse, parse_qs
            u = urlparse(self.path)
            key = (parse_qs(u.query).get("id") or [""])[0]
            body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
            if u.path == "/result":
                try:
                    results[key] = json.loads(body.decode("utf-8"))
                except ValueError:
                    results[key] = {"error": "unreadable result"}
                event_for(key).set()
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"ok")

    handler = functools.partial(Quiet, directory=str(work))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    port = server.server_address[1]
    failures = 0
    try:
        only = os.environ.get("E2E_ONLY")
        for i, scen in enumerate(SCENARIOS):
            if only and not scen["name"].startswith(only + "."):
                continue
            src = sources.get(scen.get("page", "progress"))
            if src is None:
                print(f"SKIP  {scen['name']} (page not saved)")
                continue
            (work / f"s{i}.html").write_text(build_page(src, scen).replace("/__FILE__", f"/s{i}.html"), encoding="utf-8")
            # A fresh profile per scenario: a Chrome still closing from the previous scenario would
            # otherwise hold the profile and swallow this one.
            url = f"http://127.0.0.1:{port}/s{i}.html?{scen['query']}"
            key = f"/s{i}.html"
            for attempt in ("", "b"):   # one retry if Chrome itself never reports (a runner problem)
                run_chrome(chrome, url, work / f"profile{i}{attempt}", event_for(key))
                if key in results:
                    break
            got = results.get(key)
            if not got or "result" not in got:
                why = "Chrome never reported" if not got else "test driver error: " + str(got.get("error"))[:300]
                print(f"FAIL  {scen['name']}\n      no result: {why}")
                failures += 1
                continue
            res = got["result"]
            fails = check(scen, res)
            print(("PASS  " if not fails else "FAIL  ") + scen["name"])
            print(f"      checks: {' | '.join(res['checks']) or '-'}")
            print(f"      status: {res['status'][:220]}")
            print(f"      boxes filled: {', '.join(res['boxes']) or 'none'} · encounter date {res['date']} · draft saved: {'yes' if res['apply'] else 'no'}")
            if res.get("statusAfterReload"):
                print(f"      after save + reload: {res['statusAfterReload'][:220]}")
            for f in fails:
                print("      ✗ " + f)
            failures += bool(fails)
    finally:
        server.shutdown()
        shutil.rmtree(work, ignore_errors=True)
    print(f"\n{len(SCENARIOS) - failures}/{len(SCENARIOS)} scenarios passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
