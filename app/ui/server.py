import asyncio
import contextlib
import json
import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from app import version as app_version
from app.generate import billing_section, compliance, note_audit
from app.generate import (
    billing, chunked, cpt, forms as forms_store, jobs, ollama_client, postprocess, traceability,
)
from app.generate.forms import FORMS, VALID_MODES
from app.generate.ollama_client import OllamaUnavailableError, generate_note
from app.generate.parser import parse_plain
from app.generate.prompt import (
    PatientContext, build_prompt, build_revise_prompt, build_scoped_revise_prompt, static_prefix,
    is_structural_instruction, render_prior_block, select_revise_sections,
)
from app.integrations import sheets_sync
from app.integrations.sheets_client import SheetsClient, load_sheets_config
from app.storage import carry_forward, db, repository
from app.transcribe import medasr_client
from app.ui.schemas import (
    BillingLineModel,
    BillingModel,
    ConflictModel,
    FormOut,
    FormStep,
    GenerateRequest,
    GenerateResponse,
    IcdCandidateModel,
    IntegrationStatus,
    JobDetail,
    JobSummary,
    NoteListItem,
    NoteOut,
    PatientCreate,
    PatientOut,
    PatientUpdate,
    SaveNoteRequest,
    SaveNoteResponse,
    ReviseRequest,
    SectionModel,
    StatusResponse,
    SyncResult,
    TemplateCreate,
    TemplateUpdate,
    TranscribeResponse,
    UnitAllocationModel,
)

STATIC_DIR = Path(__file__).resolve().parent / "static"
# The form whose prompt prefix is pre-read at startup: the Daily Visit is by far the most frequent.
WARM_FORM_ID = "followup"
logger = logging.getLogger(__name__)

# Generation timing lines ("ollama: prompt N tok in Xs, output M tok in Ys") go to the server
# console. Counts and seconds only — never note or dictation text.
_gen_log = logging.getLogger("cadence.generate")
if not _gen_log.handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter("%(levelname)s:     %(message)s"))
    _gen_log.addHandler(_h)
    _gen_log.setLevel(logging.INFO)
    _gen_log.propagate = False

# Shared by the background poll loop and the manual POST /api/sync/now trigger so
# they can never run a sync cycle concurrently and double-write.
_sync_lock = asyncio.Lock()


async def _sync_loop(client: SheetsClient, interval_seconds: int):
    while True:
        try:
            async with _sync_lock:
                result = await asyncio.to_thread(sheets_sync.run_sync_cycle, client)
            if result["errors"]:
                logger.warning("sheets sync cycle had errors: %s", result["errors"])
        except asyncio.CancelledError:
            raise
        except Exception:
            # A transient failure (network blip, bad credentials right now) must
            # never kill the background task or take the rest of the app down.
            logger.exception("sheets sync cycle failed")
        await asyncio.sleep(interval_seconds)


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init()

    # MedASR load failure must never take the rest of the app down -- forms,
    # generation, storage, and Sheets sync all work regardless of transcription
    # setup status. The mic buttons surface app.state.medasr_error on click instead.
    try:
        await asyncio.to_thread(medasr_client.load_model)
        app.state.medasr_ready = True
        app.state.medasr_error = None
    except medasr_client.TranscriptionUnavailableError as e:
        logger.warning("MedASR unavailable at startup: %s", e)
        app.state.medasr_ready = False
        app.state.medasr_error = str(e)

    # Load the note model and pre-read the Daily Visit prompt prefix (template + rules) in the
    # background, so the first note of the day neither waits for the model to load nor re-reads
    # ~3k tokens of fixed instructions. Never blocks startup; a missing Ollama is simply skipped.
    warm_form = FORMS.get(WARM_FORM_ID)
    warm_task = (asyncio.create_task(ollama_client.warm_prefix(static_prefix(warm_form)))
                 if warm_form else None)

    # Intake (email / Google Form): checks the subscribed sources while the server runs. Always
    # started; it does nothing until switched on in Manage Office, so turning it on needs no restart.
    intake_task = asyncio.create_task(_intake_loop())

    sync_task = None
    config = load_sheets_config()
    if config is not None:
        client = SheetsClient(config.credentials_path, config.spreadsheet_id, config.sheet_name)
        app.state.sheets_client = client
        # Sync once immediately on startup -- so a Sheet edited overnight while the
        # app was closed is picked up right away, not up to a full poll interval later.
        async with _sync_lock:
            await asyncio.to_thread(sheets_sync.run_sync_cycle, client)
        sync_task = asyncio.create_task(_sync_loop(client, config.poll_interval_seconds))
    else:
        app.state.sheets_client = None
    try:
        yield
    finally:
        await _job_queue.stop()
        if warm_task is not None and not warm_task.done():
            warm_task.cancel()
        intake_task.cancel()
        if sync_task is not None:
            sync_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await sync_task
        db.shutdown()


app = FastAPI(title="Cadence", lifespan=lifespan)

# No-store on the app's own HTML/JS/CSS. This is a local, single-user app that we iterate on
# frequently; the browser caching an old app.js after an edit silently breaks new UI (e.g. a new
# nav tab whose handler the cached JS doesn't have). Serving the shell uncached — the files are on
# the same machine, so there's no load cost — means a plain reload always runs the current code.
_NO_CACHE = {"Cache-Control": "no-store, must-revalidate"}


class _NoCacheStaticFiles(StaticFiles):
    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        response.headers.update(_NO_CACHE)
        return response


@app.get("/")
async def index():
    return FileResponse(STATIC_DIR / "index.html", headers=_NO_CACHE)


app.mount("/static", _NoCacheStaticFiles(directory=STATIC_DIR), name="static")


try:
    from app.ui import evals_api

    app.include_router(evals_api.router)
except Exception:  # noqa: BLE001
    # The evals package is developer tooling. If it is missing or broken, the clinical app must
    # still start — same posture as the optional MedASR load in the lifespan above. The Evals tab
    # then simply 404s instead of the whole server failing to boot.
    logging.getLogger("cadence").warning("evals API unavailable; the Evals tab is disabled",
                                         exc_info=True)


def extension_dir() -> Path:
    """The folder the clinician loads into Chrome as the Office Ally extension.

    On an installed copy this is `<root>/current/extension` rather than the version folder,
    because `current` is repointed by every update: Chrome keeps loading from the same path and
    picks up the new version on its next reload, instead of staying pinned to an old version
    folder the clinician would have to find and re-load by hand.
    """
    from app.paths import INSTALL_DIR
    if INSTALL_DIR.parent.name.lower() == "versions":
        current = INSTALL_DIR.parent.parent / "current" / "extension"
        if current.exists():
            return current
    return INSTALL_DIR / "extension"


@app.get("/api/extension/info")
async def extension_info():
    """Setup details for the "Send to Office Ally" pop-up: where the extension folder is and
    which version is in it. Local paths only — nothing about patients."""
    folder = extension_dir()
    version = None
    try:
        version = json.loads((folder / "manifest.json").read_text(encoding="utf-8")).get("version")
    except (OSError, ValueError):
        pass
    return {"path": str(folder), "version": version, "exists": folder.exists()}


@app.get("/api/patients/{patient_id}/notes/{note_id}/audit")
async def audit_note(patient_id: str, note_id: str):
    """Pre-send billing audit for a saved note (codes, minutes, total treatment time). Read by the
    Send to Office Ally button and the Chrome extension — one implementation for both."""
    note = repository.get_note(patient_id, note_id)
    if note is None:
        raise HTTPException(404, "note not found")
    return note_audit.audit(note["form_id"], note["sections"])


@app.get("/api/office-ally/settings")
async def get_office_ally_settings():
    """Manage Office: which Office Ally SOAP layout each Cadence note type goes into. Read by the
    Manage Office tab, the Send to Office Ally button, and the Chrome extension."""
    from app.integrations import office_ally
    forms = [{"id": fid, "name": FORMS[fid].name} for fid in forms_store.ordered_form_ids()]
    return {"layouts": office_ally.load_layouts(), "forms": forms,
            "defaults": office_ally.DEFAULT_LAYOUTS, "billing": office_ally.load_billing_choice()}


@app.put("/api/office-ally/settings")
async def put_office_ally_settings(body: dict):
    from app.integrations import office_ally
    try:
        layouts = office_ally.validate_layouts(body.get("layouts"), set(FORMS.keys()))
    except office_ally.SettingsError as e:
        raise HTTPException(400, str(e))
    office_ally.save_layouts(layouts)
    if "billing" in body:
        try:
            office_ally.save_billing_choice(body["billing"])
        except office_ally.SettingsError as e:
            raise HTTPException(400, str(e))
    return {"layouts": office_ally.load_layouts(), "billing": office_ally.load_billing_choice()}


def _protection_status() -> IntegrationStatus:
    """What protects patient data on this computer, layer by layer (HIPAA safeguards)."""
    from app import secure_store
    parts = ["database encrypted at rest (Fernet)",
             "working copy EFS-encrypted" if db.working_copy_efs else
             "working copy NOT EFS-encrypted (rely on disk encryption)",
             "intake secrets DPAPI-locked to this Windows user" if secure_store.available() else
             "intake secrets not DPAPI-protected",
             "server reachable from this computer only (127.0.0.1)",
             "mail/Google over TLS",
             "confirm BitLocker/Device encryption is ON in Windows Settings"]
    return IntegrationStatus(name="Data protection", ready=bool(db.working_copy_efs),
                             detail="; ".join(parts) + ".")


def _intake_status() -> IntegrationStatus:
    from app.integrations import email_intake as ei
    from app.integrations import form_intake as fi
    es, fs = ei.load_settings(), fi.load_settings()
    on = [n for n, ok in (("email", es["enabled"] and ei.mailboxes()),
                          ("Google Form", fs["enabled"] and fs["spreadsheet_id"])) if ok]
    if not on:
        return IntegrationStatus(name="Dictation intake (email / Google Form)", ready=False,
                                 detail="Off (optional) — set up in Manage Office; see docs/Intake_Setup_Guide.md")
    last = [x for x in (ei.load_state().get("last_result"), fi.load_state().get("last_result")) if x]
    return IntegrationStatus(name="Dictation intake (email / Google Form)", ready=True,
                             detail="Checking " + " and ".join(on) + (". Last: " + " | ".join(last) if last else ""))


@app.get("/api/status", response_model=StatusResponse)
async def get_status():
    sheets_configured = load_sheets_config() is not None
    ollama_ok = await ollama_client.is_reachable()
    return StatusResponse(version=app_version(), integrations=[
        IntegrationStatus(
            name="Local note generation (Ollama / MedGemma)",
            ready=ollama_ok,
            detail="Reachable" if ollama_ok else "Could not reach Ollama on localhost:11434 — is it running?",
        ),
        _intake_status(),
        _protection_status(),
        IntegrationStatus(
            name="Local transcription (MedASR)",
            ready=app.state.medasr_ready,
            detail="Loaded and ready" if app.state.medasr_ready else (app.state.medasr_error or "Not configured"),
        ),
        IntegrationStatus(
            name="Billing code suggestions",
            ready=cpt.billing_enabled(),
            detail=cpt.billing_gate_reason() or
                   "On — every code still requires clinician confirmation before it is billed.",
        ),
        IntegrationStatus(
            name="Google Sheets roster sync",
            ready=sheets_configured,
            detail="Configured" if sheets_configured else "Not configured (optional) — see docs/google-sheets-sync-setup.md",
        ),
    ])


def _form_out(form) -> FormOut:
    return FormOut(
        id=form.id, name=form.name, mode=form.mode, carry=form.carry,
        spec=form.spec,
        builtin=forms_store.is_builtin(form.id),
        customized=forms_store.is_customized(form.id),
        steps=[FormStep(label=s.label, example=s.example, optional=s.optional) for s in form.steps],
    )


@app.get("/api/forms", response_model=list[FormOut])
async def list_forms():
    return [_form_out(FORMS[fid]) for fid in forms_store.ordered_form_ids()]


@app.post("/api/forms", response_model=FormOut, status_code=201)
async def create_template(body: TemplateCreate):
    if not body.name.strip():
        raise HTTPException(400, "template name is required")
    if body.mode not in VALID_MODES:
        raise HTTPException(400, f"mode must be one of {VALID_MODES}")
    if not body.spec.strip():
        raise HTTPException(400, "template outline cannot be empty")
    form = forms_store.create_custom_template(body.name.strip(), body.mode, body.spec)
    return _form_out(form)


@app.post("/api/forms/{form_id}/duplicate", response_model=FormOut, status_code=201)
async def duplicate_template(form_id: str):
    form = forms_store.duplicate_template(form_id)
    if form is None:
        raise HTTPException(404, f"unknown form_id: {form_id}")
    return _form_out(form)


@app.get("/api/forms/{form_id}/template", response_model=FormOut)
async def get_template(form_id: str):
    form = FORMS.get(form_id)
    if form is None:
        raise HTTPException(404, f"unknown form_id: {form_id}")
    return _form_out(form)


@app.put("/api/forms/{form_id}/template", response_model=FormOut)
async def edit_template(form_id: str, body: TemplateUpdate):
    if form_id not in FORMS:
        raise HTTPException(404, f"unknown form_id: {form_id}")
    if not body.spec.strip():
        raise HTTPException(400, "template outline cannot be empty")
    if body.mode is not None and body.mode not in VALID_MODES:
        raise HTTPException(400, f"mode must be one of {VALID_MODES}")
    form = forms_store.edit_template(form_id, spec=body.spec, name=body.name, mode=body.mode)
    return _form_out(form)


@app.post("/api/forms/{form_id}/template/reset", response_model=FormOut)
async def reset_template(form_id: str):
    if not forms_store.is_builtin(form_id):
        raise HTTPException(400, "only built-in templates can be reset to a default")
    form = forms_store.reset_template(form_id)
    return _form_out(form)


@app.delete("/api/forms/{form_id}", status_code=204)
async def delete_template(form_id: str):
    if forms_store.is_builtin(form_id):
        raise HTTPException(400, "built-in templates cannot be deleted")
    if not forms_store.delete_custom_template(form_id):
        raise HTTPException(404, f"unknown or non-deletable form_id: {form_id}")


@app.get("/api/patients", response_model=list[PatientOut])
async def list_patients():
    return repository.list_patients()


@app.post("/api/patients", response_model=PatientOut, status_code=201)
async def create_patient(body: PatientCreate):
    if not body.name.strip():
        raise HTTPException(400, "name is required")
    patient = repository.create_patient(
        name=body.name.strip(), dob=body.dob, mrn=body.mrn, condition=body.condition,
        scheduling_notes=body.scheduling_notes,
    )
    db.persist()
    return patient


@app.get("/api/patients/{patient_id}", response_model=PatientOut)
async def get_patient(patient_id: str):
    patient = repository.get_patient(patient_id)
    if patient is None:
        raise HTTPException(404, "patient not found")
    return patient


@app.patch("/api/patients/{patient_id}", response_model=PatientOut)
async def update_patient(patient_id: str, body: PatientUpdate):
    fields = body.model_dump(exclude_unset=True)
    if "name" in fields and not (fields["name"] or "").strip():
        raise HTTPException(400, "name cannot be blank")
    patient = repository.update_patient(patient_id, **fields)
    if patient is None:
        raise HTTPException(404, "patient not found")
    db.persist()
    return patient


@app.delete("/api/patients/{patient_id}", status_code=204)
async def delete_patient(patient_id: str):
    # Permanently removes the patient and all their saved notes. Local-only by
    # design: if Sheets sync is configured the matching sheet row is left as an
    # inert orphan (see app/integrations/sheets_sync.py) rather than risking a
    # sync path that could ever turn a spreadsheet edit into data loss.
    if not repository.delete_patient(patient_id):
        raise HTTPException(404, "patient not found")
    db.persist()


@app.post("/api/sync/now", response_model=SyncResult)
async def sync_now():
    config = load_sheets_config()
    if config is None:
        raise HTTPException(503, "Google Sheets sync is not configured")
    client = app.state.sheets_client or SheetsClient(
        config.credentials_path, config.spreadsheet_id, config.sheet_name
    )
    try:
        async with _sync_lock:
            result = await asyncio.to_thread(sheets_sync.run_sync_cycle, client)
    except Exception as e:
        raise HTTPException(503, f"sync failed: {e}") from e
    return result


# Cap the audio a single request will load into memory, so an accidental huge upload can't
# exhaust RAM on the target 16 GB machine (the models already hold a few GB). ~200 MB comfortably
# fits a full-session upload — a 60-minute 16 kHz mono WAV is ~115 MB — while rejecting gigabyte
# files. The read itself is capped, so an over-size upload is never fully buffered.
MAX_AUDIO_BYTES = 200 * 1024 * 1024


@app.post("/api/transcribe", response_model=TranscribeResponse)
async def transcribe_audio(audio: UploadFile = File(...)):
    if not app.state.medasr_ready:
        raise HTTPException(503, app.state.medasr_error or "MedASR is not available.")
    data = await audio.read(MAX_AUDIO_BYTES + 1)
    if not data:
        raise HTTPException(400, "No audio received.")
    if len(data) > MAX_AUDIO_BYTES:
        raise HTTPException(413, "That recording is too large — upload a shorter clip or split the session.")
    try:
        text = await asyncio.to_thread(medasr_client.transcribe, data)
    except medasr_client.AudioUnreadableError as e:
        raise HTTPException(400, str(e)) from e
    except medasr_client.TranscriptionUnavailableError as e:
        raise HTTPException(503, str(e)) from e
    return TranscribeResponse(text=text)


@app.get("/api/patients/{patient_id}/notes", response_model=list[NoteListItem])
async def list_patient_notes(patient_id: str):
    if repository.get_patient(patient_id) is None:
        raise HTTPException(404, "patient not found")
    return repository.list_notes(patient_id)


@app.get("/api/patients/{patient_id}/notes/{note_id}", response_model=NoteOut)
async def get_patient_note(patient_id: str, note_id: str):
    note = repository.get_note(patient_id, note_id)
    if note is None:
        raise HTTPException(404, "note not found")
    return note


@app.delete("/api/patients/{patient_id}/notes/{note_id}", status_code=204)
async def delete_note(patient_id: str, note_id: str):
    if repository.get_patient(patient_id) is None:
        raise HTTPException(404, "patient not found")
    if not repository.delete_note(patient_id, note_id):
        raise HTTPException(404, "note not found")
    # The deleted note may have been the source of this patient's carry-forward
    # snapshot; rebuild it from the most recent remaining carry-eligible note (or
    # clear it if none remains) so a later visit never carries values from a note
    # that no longer exists.
    carry_forward.rebuild_snapshot_after_delete(patient_id)
    db.persist()


def _generation_setup(body: GenerateRequest):
    """Shared front of the generate path (both streaming and not): validate form/patient, build the
    prior-note block and patient context. Raises HTTPException (400/404) so it runs BEFORE any
    streaming response starts, where errors can still be a normal HTTP status."""
    form = FORMS.get(body.form_id)
    if form is None:
        raise HTTPException(400, f"unknown form_id: {body.form_id}")
    patient = repository.get_patient(body.patient_id)
    if patient is None:
        raise HTTPException(404, "patient not found")
    snapshot = repository.get_carry_snapshot(body.patient_id) if form.carry else None
    used_prior = bool(form.carry and body.use_prior and snapshot)
    prior_block = render_prior_block(form, snapshot, body.use_prior)
    sub = " · ".join(filter(None, [
        f"MRN {patient['mrn']}" if patient.get("mrn") else None,
        f"DOB {patient['dob']}" if patient.get("dob") else None,
        patient.get("condition"),
    ])) or "—"
    patient_ctx = PatientContext(name=patient["name"], sub=sub)
    return form, prior_block, used_prior, patient_ctx


def _billing_draft(form, bill_from: str | None, sections: list[dict] | None):
    """The dictation-derived billing draft, or None when billing doesn't apply.

    `bill_from` must be the raw DICTATION, never the generated note. The revise path passes None
    for exactly this reason: its "transcript" is the note's own prose, and scanning model-written
    prose for interventions is the misfire CLAUDE.md rule 12 forbids.
    """
    if not bill_from or form.id in cpt._NON_BILLING_FORMS or not cpt.billing_enabled():
        return None
    draft = billing.extract(bill_from, eval_form=cpt.is_eval_form(form.id))
    if sections:
        draft = billing.reconcile(draft, sections)
    return BillingModel(
        body_part=draft.body_part,
        interventions=[
            BillingLineModel(
                code=h.code, label=h.label, timed=h.timed, status=h.status, cue=h.cue,
                cue_strength=h.cue_strength, clause=h.clause, minutes=h.minutes,
                minutes_basis=h.minutes_basis,
            ) for h in draft.interventions
        ],
        icd_candidates=[
            IcdCandidateModel(
                code=c.code, label=c.label, cue=c.cue, clause=c.clause, laterality=c.laterality,
                laterality_stated=c.laterality_stated, caution=c.caution,
            ) for c in draft.icd_candidates
        ],
        total_timed_minutes=draft.total_timed_minutes,
        untimed_codes=list(draft.untimed_codes),
        units=UnitAllocationModel(**vars(draft.units)) if draft.units else None,
        units_alt=UnitAllocationModel(**vars(draft.units_alt)) if draft.units_alt else None,
        units_if_confirmed=(UnitAllocationModel(**vars(draft.units_if_confirmed))
                            if draft.units_if_confirmed else None),
        missing=list(draft.missing),
        conflicts=[ConflictModel(kind=c.kind, severity=c.severity, code=c.code, detail=c.detail)
                   for c in draft.conflicts],
    )


def _finalize_note(form, text, was_condensed, still_over, transcript, used_prior, *,
                   bill_from: str | None = None, model_id: str | None = None) -> GenerateResponse:
    """Shared back of the generate path: parse the raw note, then the deterministic post-generation
    pipeline — postprocess safeguards, the verification/anti-hallucination flags (anchored against the
    RAW dictation), CPT suggestion, and the billing draft. Identical whether the note was streamed
    or not."""
    # Provenance stamped server-side: the client must not be the authority on which model ran,
    # and the spec hash has to be the outline as of GENERATION time (templates are editable, so
    # it can change between generating and saving).
    prov = dict(model_id=model_id, template_spec_sha=forms_store.spec_sha(form.id),
                template_customized=forms_store.is_customized(form.id),
                fast=bool(model_id and model_id == ollama_client.FAST_MODEL))
    parsed = parse_plain(text)
    if parsed is None:
        # The billing draft comes from the DICTATION, so it survives a model that ignored the
        # output contract entirely — a failed generation still leaves the clinician usable codes.
        return GenerateResponse(
            sections=[], missing_info=[], form_id=form.id, form_name=form.name,
            used_prior=used_prior, raw_text=text,
            billing=_billing_draft(form, bill_from, None), **prov,
        )
    sections = postprocess.apply(form.id, parsed["sections"])
    sections = traceability.add_verification_flags(sections, transcript)
    # Whether the therapist STATED the evaluation complexity, asked directly rather than by
    # building the whole draft first. Reordering `_billing_draft` above `suggest_codes` would
    # break `reconcile`, which compares the draft against the note's [[CPT: ...]] chips — and
    # those chips do not exist until `suggest_codes` has run.
    stated_eval = bool(
        bill_from and cpt.is_eval_form(form.id)
        and billing.detect_eval_complexity(billing.split_clauses(bill_from)) is not None
    )
    if cpt.billing_enabled():
        sections, code_flags = cpt.suggest_codes(sections, form.id,
                                                 eval_complexity_stated=stated_eval)
    else:
        code_flags = []
    missing = list(parsed["missing_info"]) + code_flags
    if was_condensed:
        missing.append(
            "This dictation was very long and had to be condensed to fit the model even after "
            "cleanup — verify the note captured the whole session, or split the dictation into shorter parts."
            if still_over else
            "This dictation was long and was automatically condensed to fit the model — verify the "
            "note captured the whole session."
        )
    elif still_over:
        # Over budget with condensing off (the default — see chunked.CONDENSE_ENABLED). The model
        # did NOT see all of this dictation. Silent truncation is what rule 16 was written about,
        # so the one thing that must not happen is saying nothing.
        missing.append(
            "This dictation was too long for the model to read in one pass, so part of it was not "
            "seen — check every section against what you said, especially the beginning and end, "
            "or split the visit into two shorter dictations."
        )
    # A note the model abandoned — headings with nothing under them, or a stop after the treatment
    # sections — must say so at the top instead of looking finished (measured 2026-10: a 445-char
    # "note" that was only the outline's headings).
    declared = forms_store.spec_section_labels(form.id)
    if declared:
        filled = {(s.get("heading") or "").strip().lower() for s in sections
                  if (s.get("body") or "").replace("[[", "").strip()
                  and not (s.get("body") or "").strip().startswith("[[")}
        missing_count = sum(1 for l in declared if l.lower() not in filled)
        if missing_count * 2 > len(declared):
            missing.insert(0, f"INCOMPLETE NOTE: the model left {missing_count} of {len(declared)} "
                              "sections empty or missing. Click Regenerate (or Generate again) before "
                              "reviewing — do not save this draft as it is.")
    # Medicare documentation checklist: what a medical reviewer would deny or question as written,
    # shown in the review list so it is fixed BEFORE saving rather than discovered at Send.
    for f in compliance.check(form.id, sections):
        if f["level"] == "fix":
            missing.append(f"Medicare checklist — {f['element']}: {f['text']}")
    billing_model = _billing_draft(form, bill_from, sections)
    if billing_model is not None:
        # Saved WITH the note (the draft above is response-only and vanished on Save), so the
        # codes, minutes and total time reach Office Ally and the pre-send audit can check them.
        raw_draft = billing.reconcile(
            billing.extract(bill_from, eval_form=cpt.is_eval_form(form.id)), sections)
        sections = billing_section.flag_undictated_treatments(sections, raw_draft)
        sections = sections + [billing_section.build(raw_draft, bill_from, form.id)]
    return GenerateResponse(
        sections=[SectionModel(**s) for s in sections],
        missing_info=missing,
        form_id=form.id, form_name=form.name, used_prior=used_prior, raw_text=None,
        billing=billing_model, **prov,
    )


@app.post("/api/generate", response_model=GenerateResponse)
async def generate(body: GenerateRequest):
    form, prior_block, used_prior, patient_ctx = _generation_setup(body)
    # Fit an over-long dictation into the model's context (rule 16) — condenses only a genuinely huge
    # one, else unchanged. Then one blocking model call. (The UI uses /api/generate/stream; this
    # non-streaming endpoint stays for tooling/tests and as a fallback.)
    overhead = chunked.estimate_tokens(build_prompt(form, patient_ctx, "", prior_block, body.extra_info))
    try:
        summary, was_condensed, still_over = await chunked.fit_dictation(body.summary, overhead, generate_note)
        prompt = build_prompt(form, patient_ctx, summary, prior_block, body.extra_info)
        text = await generate_note(prompt, model=ollama_client.model_for(body.fast))
    except OllamaUnavailableError as e:
        raise HTTPException(502, str(e)) from e
    transcript = " ".join(filter(None, [body.summary, body.extra_info]))
    return _finalize_note(form, text, was_condensed, still_over, transcript, used_prior,
                          bill_from=transcript, model_id=ollama_client.model_for(body.fast))


@app.post("/api/generate/stream")
async def generate_stream(body: GenerateRequest):
    """Streaming generate: emits newline-delimited JSON events — {"type":"token"} as the model writes,
    an optional {"type":"status"} while a huge dictation is condensed, then a single {"type":"done",
    "result": <same shape as /api/generate>} once the full post-processing pipeline has run, or
    {"type":"error"}. The clinician watches the note write live and a long generation is never lost to
    a timeout. Validation happens up front (real 400/404) before the stream starts."""
    form, prior_block, used_prior, patient_ctx = _generation_setup(body)
    transcript = " ".join(filter(None, [body.summary, body.extra_info]))
    model = ollama_client.model_for(body.fast)

    def _event(obj) -> str:
        return json.dumps(obj) + "\n"

    async def events():
        try:
            overhead = chunked.estimate_tokens(build_prompt(form, patient_ctx, "", prior_block, body.extra_info))
            summary, was_condensed, still_over = await chunked.fit_dictation(body.summary, overhead, generate_note)
            if was_condensed:
                yield _event({"type": "status", "text": "Condensing a very long dictation before writing…"})
            prompt = build_prompt(form, patient_ctx, summary, prior_block, body.extra_info)
            parts: list[str] = []
            async for chunk in ollama_client.stream_note(prompt, model=model):
                parts.append(chunk)
                yield _event({"type": "token", "text": chunk})
            result = _finalize_note(form, "".join(parts), was_condensed, still_over, transcript,
                                    used_prior, bill_from=transcript, model_id=model)
            yield _event({"type": "done", "result": result.model_dump()})
        except OllamaUnavailableError as e:
            yield _event({"type": "error", "detail": str(e)})
        except Exception:  # noqa: BLE001 - never leak a stack trace to the client mid-stream
            logger.exception("streaming generation failed")
            yield _event({"type": "error", "detail": "Generation failed unexpectedly — please try again."})

    return StreamingResponse(
        events(),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )


# ---------------------------------------------------------------------------------
# Background generation queue
#
# Measured on the dev box: median 7.0 min per note, 21 of 21 over the stated 1-2 min budget, with
# the floor set by a 91-word follow-up — so the cost is output length, not input length, and no
# amount of prompt trimming reaches the budget on CPU-only hardware. The fix is to stop making the
# wait blocking. /api/generate/stream above still exists and is unchanged for tooling and for a
# clinician who wants to watch one note write; the queue is what lets them start a note and walk
# to the next patient. See app/generate/jobs.py for why one serialized worker rather than N.
# ---------------------------------------------------------------------------------

async def _run_generation_job(job: jobs.Job, emit) -> dict:
    """The queue's unit of work — the same pipeline /api/generate/stream runs, with `emit` in place
    of the HTTP yield. Deliberately reuses `_generation_setup`/`_finalize_note` so the queued path
    can never drift from the direct one."""
    body = GenerateRequest(**job.payload)
    form, prior_block, used_prior, patient_ctx = _generation_setup(body)
    transcript = " ".join(filter(None, [body.summary, body.extra_info]))
    model = ollama_client.model_for(body.fast)
    overhead = chunked.estimate_tokens(build_prompt(form, patient_ctx, "", prior_block, body.extra_info))
    job.detail = "Checking the dictation length…"
    summary, was_condensed, still_over = await chunked.fit_dictation(body.summary, overhead, generate_note)
    if was_condensed:
        job.detail = "Condensed a very long dictation; writing the note…"
    else:
        job.detail = "Writing the note…"
    prompt = build_prompt(form, patient_ctx, summary, prior_block, body.extra_info)
    parts: list[str] = []
    async for chunk in ollama_client.stream_note(prompt, model=model):
        parts.append(chunk)
        emit(chunk)
    result = _finalize_note(form, "".join(parts), was_condensed, still_over, transcript,
                            used_prior, bill_from=transcript, model_id=model)
    out = result.model_dump()
    out["visit_date"] = body.visit_date
    return out


_job_queue = jobs.JobQueue(_run_generation_job)


# ---------------------------------------------------------------------------------
# Intake: dictation that arrives from OUTSIDE the app — emailed to a subscribed practice mailbox
# (app/integrations/email_intake.py) or submitted through the practice's Google Form
# (app/integrations/form_intake.py). Both feed ONE path here: a new "Unknown patient" with the
# visit date in the DOB column, and the note queued in "Notes in progress" for review. Nothing is
# saved until the clinician saves it; an item whose draft was never saved (server restarted) is
# picked up again on the next check.
# ---------------------------------------------------------------------------------

_intake_lock = asyncio.Lock()


def _intake_job_alive(job_id: str | None) -> bool:
    job = _job_queue.get(job_id) if job_id else None
    return job is not None and job.status not in (jobs.CANCELLED, jobs.ERROR)


def _intake_needs_resend(entry: dict) -> bool:
    pid = entry.get("patient_id")
    return bool(pid and repository.get_patient(pid) and not repository.list_notes(pid)
                and not _intake_job_alive(entry.get("job_id")))


async def _queue_intake_item(*, text: str, visit, form_id: str, existing_pid: str | None) -> tuple[str, str]:
    """Create (or reuse) the Unknown patient and queue the note. Returns (patient_id, job_id)."""
    from app.integrations import email_intake as ei
    pid = existing_pid if existing_pid and repository.get_patient(existing_pid) else None
    if pid is None:
        pid = repository.create_patient(
            name=ei.PATIENT_NAME, dob=ei.dob_display(visit), mrn=None,
            condition="Dictation received" + (f" — visit {ei.dob_display(visit)}" if visit else ""),
        )["id"]
        await asyncio.to_thread(db.persist)
    form = FORMS.get(form_id) or FORMS["followup"]
    body = GenerateRequest(patient_id=pid, form_id=form.id, summary=text, use_prior=False,
                           visit_date=visit.isoformat() if visit else None)
    job = _job_queue.submit(patient_id=pid, patient_name=ei.PATIENT_NAME, form_id=form.id,
                            form_name=form.name, fast=False, payload=body.model_dump())
    return pid, job.id


async def _email_check_once() -> dict:
    from app.integrations import email_intake as ei
    state = ei.load_state()
    processed = state["processed"]
    queued, skipped, errors = 0, [], []
    for mb in ei.mailboxes():
        known = {mid for mid, v in processed.items() if v.get("mailbox") == mb.address}
        resend = {mid for mid in known if _intake_needs_resend(processed[mid])}
        try:
            emails, skip = await asyncio.to_thread(ei.fetch_new, mb, known_ids=known, resend_ids=resend)
        except Exception as e:  # noqa: BLE001 - one bad mailbox must not stop the others
            errors.append(f"{mb.address}: {await asyncio.to_thread(ei.test_login, mb) or e.__class__.__name__}")
            continue
        skipped += [f"{mb.address}: sender not allowed ({s})" for s in skip]
        seen = []
        for em in emails:
            seen.append(em.uid)
            if not em.body.strip():
                skipped.append(f"{em.mailbox}: empty email")
                continue
            visit, _ = ei.parse_visit_date(em.subject, em.body, em.sent)
            pid, job_id = await _queue_intake_item(
                text=em.body, visit=visit, form_id=ei.form_for_subject(em.subject),
                existing_pid=(processed.get(em.message_id) or {}).get("patient_id"))
            processed[em.message_id] = {"mailbox": mb.address, "patient_id": pid, "job_id": job_id,
                                        "at": time.time()}
            queued += 1
        try:
            await asyncio.to_thread(ei.mark_seen, mb, seen)
        except Exception:  # noqa: BLE001 - the Message-ID record already prevents a re-queue
            pass
    state["last_check"] = ei.now_iso()
    state["last_result"] = _intake_summary(queued, skipped, errors)
    ei.save_state(state)
    return {"queued": queued, "skipped": skipped, "errors": errors, "result": state["last_result"]}


async def _form_check_once() -> dict:
    from app.integrations import email_intake as ei
    from app.integrations import form_intake as fi
    state = fi.load_state()
    processed = state["processed"]
    queued, skipped, errors = 0, [], []
    try:
        rows = await asyncio.to_thread(fi.fetch_rows)
    except Exception as e:  # noqa: BLE001
        errors.append(fi.explain_error(e))
        rows = []
    marks = {}
    for row in rows:
        entry = processed.get(row.item_id)
        if entry and not _intake_needs_resend(entry):
            continue
        if not fi.sender_ok(row):
            skipped.append(f"row {row.row_number}: submitted by a non-practice account")
            marks[row.row_number] = "Skipped — not a practice account"
            continue
        if not row.dictation.strip():
            marks[row.row_number] = "Skipped — empty dictation"
            continue
        visit, _ = ei.parse_visit_date(row.visit_date_text, row.dictation, row.submitted)
        pid, job_id = await _queue_intake_item(
            text=row.dictation, visit=visit, form_id=fi.form_for_choice(row.note_type),
            existing_pid=(entry or {}).get("patient_id"))
        processed[row.item_id] = {"patient_id": pid, "job_id": job_id, "at": time.time()}
        marks[row.row_number] = f"Queued in Cadence {ei.now_iso()}"
        queued += 1
    if marks:
        try:
            await asyncio.to_thread(fi.write_status, marks)
        except Exception as e:  # noqa: BLE001 - the local record already prevents a re-queue
            errors.append("could not write the status column: " + fi.explain_error(e))
    state["last_check"] = ei.now_iso()
    state["last_result"] = _intake_summary(queued, skipped, errors)
    fi.save_state(state)
    return {"queued": queued, "skipped": skipped, "errors": errors, "result": state["last_result"]}


def _intake_summary(queued, skipped, errors) -> str:
    out = f"{queued} note(s) queued"
    if skipped:
        out += f"; {len(skipped)} skipped"
    if errors:
        out += "; " + "; ".join(errors)
    return out


async def _intake_loop():
    from app.integrations import email_intake as ei
    from app.integrations import form_intake as fi
    while True:
        interval = ei.DEFAULT_POLL_SECONDS
        try:
            es, fs = ei.load_settings(), fi.load_settings()
            interval = min(es["poll_seconds"], fs["poll_seconds"])
            async with _intake_lock:
                if es["enabled"] and ei.mailboxes():
                    await _email_check_once()
                if fs["enabled"] and fs["spreadsheet_id"]:
                    await _form_check_once()
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - never let an intake problem take the server down
            logger.exception("intake check failed")
        await asyncio.sleep(interval)


@app.get("/api/intake/settings")
async def get_intake_settings():
    from app.integrations import email_intake as ei
    from app.integrations import form_intake as fi
    es, fs = ei.load_state(), fi.load_state()
    return {
        "email": {**ei.public_settings(), "last_check": es.get("last_check"),
                  "last_result": es.get("last_result")},
        "form": {**fi.public_settings(), "last_check": fs.get("last_check"),
                 "last_result": fs.get("last_result")},
    }


@app.put("/api/intake/settings")
async def put_intake_settings(body: dict):
    from app.integrations import email_intake as ei
    from app.integrations import form_intake as fi
    try:
        if "email" in body:
            ei.save_settings(body["email"])
        if "form" in body:
            fi.save_settings(body["form"])
    except (ei.SettingsError, fi.SettingsError) as e:
        raise HTTPException(400, str(e))
    return await get_intake_settings()


@app.post("/api/intake/test")
async def test_intake(body: dict | None = None):
    """Check each configured source can be reached — mailboxes sign in, the form Sheet opens."""
    from app.integrations import email_intake as ei
    from app.integrations import form_intake as fi
    results = []
    for mb in ei.mailboxes():
        reason = await asyncio.to_thread(ei.test_login, mb)
        results.append({"source": mb.address, "ok": not reason, "detail": reason or "Connected."})
    if fi.load_settings()["spreadsheet_id"]:
        reason = await asyncio.to_thread(fi.test_access)
        results.append({"source": "Google Form responses Sheet", "ok": not reason,
                        "detail": reason or "Connected."})
    if not results:
        raise HTTPException(400, "Set up a mailbox or the Google Form first.")
    return {"results": results}


@app.post("/api/intake/check")
async def check_intake_now():
    from app.integrations import email_intake as ei
    from app.integrations import form_intake as fi
    out = {}
    async with _intake_lock:
        if ei.mailboxes():
            out["email"] = await _email_check_once()
        if fi.load_settings()["spreadsheet_id"]:
            out["form"] = await _form_check_once()
    if not out:
        raise HTTPException(400, "Set up a mailbox or the Google Form first.")
    return out


@app.post("/api/generate/jobs", response_model=JobSummary, status_code=202)
async def enqueue_generation(body: GenerateRequest):
    """Queue a note and return immediately. Validation still runs up front, so an unknown form or
    a missing patient is a real 400/404 rather than a job that fails minutes later."""
    _generation_setup(body)
    patient = repository.get_patient(body.patient_id)
    form = FORMS[body.form_id]
    job = _job_queue.submit(
        patient_id=body.patient_id, patient_name=(patient or {}).get("name", "—"),
        form_id=form.id, form_name=form.name, fast=body.fast,
        payload=body.model_dump(),
    )
    return JobSummary(**job.summary(_job_queue.position(job.id)))


@app.get("/api/generate/jobs", response_model=list[JobSummary])
async def list_generation_jobs():
    return [JobSummary(**s) for s in _job_queue.list()]


@app.get("/api/generate/jobs/{job_id}", response_model=JobDetail)
async def get_generation_job(job_id: str, cursor: int = 0):
    """Status plus the text written since `cursor`. Polling with the cursor the previous call
    returned reattaches to a running note after a reload — the buffer is append-only and owned by
    the server, so nothing is lost when the browser goes away."""
    tail = _job_queue.tail(job_id, cursor)
    if tail is None:
        raise HTTPException(404, "job not found")
    return JobDetail(**tail)


@app.delete("/api/generate/jobs/{job_id}", status_code=204)
async def cancel_generation_job(job_id: str):
    """Cancel a queued or running note, or dismiss a finished one from the tray."""
    if not _job_queue.cancel(job_id):
        raise HTTPException(404, "job not found")
    return None


def _splice_scoped(before: list[dict], model_output: str) -> str:
    """Put the model's re-written section(s) back into the full note, as plain text.

    Sections the clinician did not ask about are carried across EXACTLY as they were — this is the
    mechanism, not a nicety. The model never saw them, so it cannot have reworded them. A body of
    [[DELETE]] removes a section, which is how a scoped prompt expresses "delete the Vitals
    section" without needing the whole note.
    """
    parsed = parse_plain(model_output)
    new_by = {(s.get("heading") or "").strip().lower(): s
              for s in (parsed["sections"] if parsed else [])}
    out: list[dict] = []
    for s in before:
        head = (s.get("heading") or "").strip().lower()
        replacement = new_by.pop(head, None)
        if replacement is None:
            out.append(s)
            continue
        if replacement.get("body", "").strip().upper().strip("[]") == "DELETE":
            continue
        out.append({**s, "body": replacement.get("body", "")})
    # A section the model invented rather than revised. Kept (never silently dropped) so the
    # clinician sees it, but appended at the end rather than guessing where it belongs.
    out.extend(new_by.values())
    return "\n\n".join(f"## {s['heading']}\n{s.get('body', '')}" for s in out)


@app.post("/api/revise/stream")
async def revise_stream(body: ReviseRequest):
    """Apply a clinician's plain-language edit to an already-generated note and stream the revised note
    back (same token/done/error events as /api/generate/stream). The model re-emits the whole note with
    only the requested change; the same post-processing/verification pipeline then runs. Nothing is
    saved — the clinician reviews and Saves as usual."""
    form = FORMS.get(body.form_id)
    if form is None:
        raise HTTPException(400, f"unknown form_id: {body.form_id}")
    if not body.instruction.strip():
        raise HTTPException(400, "no change was requested")
    if not body.note_text.strip():
        raise HTTPException(400, "no note to revise")
    # SCOPED vs WHOLE-NOTE. Measured on a real 14-section note, a whole-note rewrite asked to change
    # ONE section deleted four others and reworded four more — because the model is spending its
    # output budget copying 2,000 tokens it was never meant to touch. When the instruction names a
    # section we can identify deterministically, only that section is sent and only that section
    # comes back; the rest is spliced through byte-identical, so collateral drift is impossible
    # rather than discouraged. Anything structural (merge/reorder/move) or unidentifiable still
    # takes the whole-note path, because a splice cannot express a change in the note's shape.
    parsed_before = parse_plain(body.note_text)
    sections_before = parsed_before["sections"] if parsed_before else []
    targets = ([] if (not sections_before or is_structural_instruction(body.instruction))
               else select_revise_sections(sections_before, body.instruction))
    if targets:
        prompt = build_scoped_revise_prompt(form, sections_before, targets, body.instruction)
    else:
        prompt = build_revise_prompt(form, body.note_text, body.instruction)
    # Anchor the verification flags against the existing note + the instruction, so values already in
    # the note (and ones the clinician just asked to add) aren't false-flagged as fabricated.
    transcript = " ".join(filter(None, [body.note_text, body.instruction]))
    model = ollama_client.model_for(body.fast)

    def _event(obj) -> str:
        return json.dumps(obj) + "\n"

    async def events():
        try:
            parts: list[str] = []
            async for chunk in ollama_client.stream_note(prompt, model=model):
                parts.append(chunk)
                yield _event({"type": "token", "text": chunk})
            # bill_from=None is deliberate and load-bearing. `transcript` here is the NOTE's own
            # prose plus the instruction, not the dictation — scanning model-written prose for
            # billable interventions is precisely the misfire rule 12 forbids. The client keeps
            # showing the billing card from the original generate, which was derived from the
            # real dictation and is still the correct draft for this visit.
            written = "".join(parts)
            note_text = (_splice_scoped(sections_before, written) if targets else written)
            result = _finalize_note(form, note_text, False, False, transcript, False,
                                    bill_from=None, model_id=model)
            yield _event({"type": "done", "result": result.model_dump()})
        except OllamaUnavailableError as e:
            yield _event({"type": "error", "detail": str(e)})
        except Exception:  # noqa: BLE001
            logger.exception("revise failed")
            yield _event({"type": "error", "detail": "Revision failed — please try again."})

    return StreamingResponse(
        events(),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )


@app.post("/api/patients/{patient_id}/notes", response_model=SaveNoteResponse, status_code=201)
async def save_note(patient_id: str, body: SaveNoteRequest):
    if repository.get_patient(patient_id) is None:
        raise HTTPException(404, "patient not found")

    sections = [s.model_dump() for s in body.sections]
    created = repository.create_note(
        patient_id=patient_id, form_id=body.form_id, form_name=body.form_name,
        sections=sections, missing_info=body.missing_info,
        dictation_raw=body.dictation_raw, used_prior=body.used_prior,
        # Correction capture. NOTE: carry_forward below must keep receiving the FINAL sections,
        # never the originals, or a follow-up would carry the model's uncorrected values forward.
        original_sections=[s.model_dump() for s in body.original_sections] or None,
        revise_instructions=[r.model_dump() for r in body.revise_instructions] or None,
        model_id=body.model_id, fast=body.fast,
        template_spec_sha=body.template_spec_sha,
        template_customized=body.template_customized, synthetic=body.synthetic,
        visit_date=body.visit_date,
    )
    carry_forward.update_snapshot_after_save(
        patient_id=patient_id, note_id=created["id"], form_id=body.form_id, sections=sections
    )
    db.persist()
    return SaveNoteResponse(**created)
