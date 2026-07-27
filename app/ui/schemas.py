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


class GenerateResponse(BaseModel):
    sections: list[SectionModel]
    missing_info: list[str]
    form_id: str
    form_name: str
    used_prior: bool
    raw_text: str | None = None


class SaveNoteRequest(BaseModel):
    form_id: str
    form_name: str
    sections: list[SectionModel]
    missing_info: list[str]
    dictation_raw: str
    used_prior: bool


class SaveNoteResponse(BaseModel):
    id: str
    created_at: str
