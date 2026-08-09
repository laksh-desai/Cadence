import asyncio
import contextlib
import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from app.generate import (
    billing, chunked, cpt, forms as forms_store, ollama_client, postprocess, traceability,
)
from app.generate.forms import FORMS, VALID_MODES
from app.generate.ollama_client import OllamaUnavailableError, generate_note
from app.generate.parser import parse_plain
from app.generate.prompt import PatientContext, build_prompt, build_revise_prompt, render_prior_block
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
logger = logging.getLogger(__name__)

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


@app.get("/api/status", response_model=StatusResponse)
async def get_status():
    sheets_configured = load_sheets_config() is not None
    ollama_ok = await ollama_client.is_reachable()
    return StatusResponse(integrations=[
        IntegrationStatus(
            name="Local note generation (Ollama / MedGemma)",
            ready=ollama_ok,
            detail="Reachable" if ollama_ok else "Could not reach Ollama on localhost:11434 — is it running?",
        ),
        IntegrationStatus(
            name="Local transcription (MedASR)",
            ready=app.state.medasr_ready,
            detail="Loaded and ready" if app.state.medasr_ready else (app.state.medasr_error or "Not configured"),
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
    if not bill_from or form.id in cpt._NON_BILLING_FORMS:
        return None
    draft = billing.extract(bill_from)
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
    sections, code_flags = cpt.suggest_codes(sections, form.id)
    missing = list(parsed["missing_info"]) + code_flags
    if was_condensed:
        missing.append(
            "This dictation was very long and had to be condensed to fit the model even after "
            "cleanup — verify the note captured the whole session, or split the dictation into shorter parts."
            if still_over else
            "This dictation was long and was automatically condensed to fit the model — verify the "
            "note captured the whole session."
        )
    return GenerateResponse(
        sections=[SectionModel(**s) for s in sections],
        missing_info=missing,
        form_id=form.id, form_name=form.name, used_prior=used_prior, raw_text=None,
        billing=_billing_draft(form, bill_from, sections), **prov,
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
            result = _finalize_note(form, "".join(parts), False, False, transcript, False,
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
    )
    carry_forward.update_snapshot_after_save(
        patient_id=patient_id, note_id=created["id"], form_id=body.form_id, sections=sections
    )
    db.persist()
    return SaveNoteResponse(**created)
