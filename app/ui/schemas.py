from pydantic import BaseModel


class FormStep(BaseModel):
    label: str
    example: str
    optional: bool = False


class FormOut(BaseModel):
    id: str
    name: str
    mode: str
    carry: bool
    spec: str = ""          # the outline the model fills — shown/edited in the Templates tab
    builtin: bool = True    # a shipped form (fixed identity) vs a user-created template
    customized: bool = False  # a built-in whose outline the user has overridden (resettable)
    steps: list[FormStep] = []


class TemplateCreate(BaseModel):
    name: str
    mode: str = "require"
    spec: str


class TemplateUpdate(BaseModel):
    spec: str
    name: str | None = None   # applied to custom templates only (built-in identity is fixed)
    mode: str | None = None   # applied to custom templates only


class PatientOut(BaseModel):
    id: str
    name: str
    dob: str | None = None
    mrn: str | None = None
    condition: str | None = None
    scheduling_notes: str | None = None
    has_prior: bool
    note_count: int


class PatientCreate(BaseModel):
    name: str
    dob: str | None = None
    mrn: str | None = None
    condition: str | None = None
    scheduling_notes: str | None = None


class PatientUpdate(BaseModel):
    name: str | None = None
    dob: str | None = None
    mrn: str | None = None
    condition: str | None = None
    scheduling_notes: str | None = None


class SyncResult(BaseModel):
    pushed: int
    pulled: int
    conflicts_resolved: int
    new_from_sheet: int
    errors: list[str]


class TranscribeResponse(BaseModel):
    text: str


class IntegrationStatus(BaseModel):
    name: str
    ready: bool
    detail: str


class StatusResponse(BaseModel):
    integrations: list[IntegrationStatus]


class SectionModel(BaseModel):
    heading: str
    body: str
    carried_forward: bool


class NoteListItem(BaseModel):
    id: str
    form_id: str
    form_name: str
    created_at: str
    missing_count: int
    snippet: str


class NoteOut(BaseModel):
    id: str
    form_id: str
    form_name: str
    created_at: str
    sections: list[SectionModel]
    missing_info: list[str]


class GenerateRequest(BaseModel):
    patient_id: str
    form_id: str
    summary: str
    use_prior: bool = True
    extra_info: str | None = None
    fast: bool = False  # use the smaller fast-draft model instead of the 4B quality model


class ReviseRequest(BaseModel):
    patient_id: str
    form_id: str
    note_text: str      # the current note as plain text (## headings + bodies)
    instruction: str    # the clinician's plain-language change request
    fast: bool = False  # use the smaller fast-draft model instead of the 4B quality model


class BillingLineModel(BaseModel):
    """One detected intervention. Non-billable ones are INCLUDED, carrying the reason they were
    excluded, so the clinician sees what Cadence chose not to bill and can override it."""
    code: str
    label: str
    timed: bool
    status: str          # performed | negated | prior_visit | planned | home_program | uncertain
    cue: str             # the phrase matched in the dictation
    cue_strength: str    # strong | weak
    clause: str          # the dictation clause it came from — the evidence for the line
    minutes: int | None = None
    minutes_basis: str = "not_stated"


class IcdCandidateModel(BaseModel):
    code: str
    label: str
    cue: str
    clause: str
    laterality: str | None = None
    laterality_stated: bool = False
    caution: str = ""


class UnitAllocationModel(BaseModel):
    """Units under ONE named method. Two are always returned — see BillingModel.units_alt."""
    method: str
    total_timed_minutes: int
    total_units: int
    per_code: list[tuple[str, int]] = []
    ambiguous: bool = False
    note: str = ""


class ConflictModel(BaseModel):
    kind: str       # dictation_only | note_only | minutes_mismatch
    severity: str   # high | low
    code: str
    detail: str


class BillingModel(BaseModel):
    """The deterministic billing draft derived from the DICTATION (app/generate/billing.py).

    Response metadata, deliberately NOT a note section: keeping it out of `sections` is what lets
    postprocess's CPT/ICD stripping and rule 12's "the model never authors a code" stay intact.
    """
    body_part: str | None = None
    interventions: list[BillingLineModel] = []
    icd_candidates: list[IcdCandidateModel] = []
    total_timed_minutes: int = 0
    untimed_codes: list[str] = []
    units: UnitAllocationModel | None = None       # CMS substitution
    units_alt: UnitAllocationModel | None = None   # AMA rule of eights
    #: Units if the clinician also accepts every `uncertain` timed line. None when there are none
    #: to accept. Computed server-side so the 8-minute rule is never reimplemented in JavaScript.
    units_if_confirmed: UnitAllocationModel | None = None
    missing: list[str] = []
    conflicts: list[ConflictModel] = []
    #: Always True. Cadence drafts billing; the clinician bills.
    confirm_required: bool = True


class GenerateResponse(BaseModel):
    sections: list[SectionModel]
    missing_info: list[str]
    form_id: str
    form_name: str
    used_prior: bool
    raw_text: str | None = None
    #: None when billing doesn't apply: a patient-facing/auxiliary form, or the revise path, which
    #: has only the NOTE's prose to work from and must never bill off model-written text (rule 12).
    billing: BillingModel | None = None
    # Provenance, produced by the SERVER and echoed back by the client on save. The client must
    # not be the authority on which model ran, and `template_spec_sha` has to be the spec as of
    # GENERATION time — the clinician can edit a template between generating and saving.
    model_id: str | None = None
    fast: bool = False
    template_spec_sha: str | None = None
    template_customized: bool = False


class ReviseInstruction(BaseModel):
    """One plain-language change request the clinician typed into "Ask for changes".

    Captured because it is the highest-signal correction data the app sees — the clinician saying
    in their own words what was wrong — and it used to be discarded the moment the stream ended.
    """
    text: str
    applied: bool = True     # False = the model failed to produce a revision; still signal
    at: str | None = None


class SaveNoteRequest(BaseModel):
    form_id: str
    form_name: str
    sections: list[SectionModel]
    missing_info: list[str]
    dictation_raw: str
    used_prior: bool
    # Correction capture. All defaulted, so an older client (or a test that omits them) saves
    # exactly as before.
    original_sections: list[SectionModel] = []
    revise_instructions: list[ReviseInstruction] = []
    model_id: str | None = None
    fast: bool = False
    template_spec_sha: str | None = None
    template_customized: bool = False
    synthetic: bool = False


class SaveNoteResponse(BaseModel):
    id: str
    created_at: str
