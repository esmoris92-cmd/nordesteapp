"""Esquemas de entrada y salida de la API (validación con Pydantic).

Los nombres de campo están en inglés (identificadores de código); los mensajes
para la persona usuaria están en español.
"""

import re
import uuid
from datetime import date, datetime, time
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import (
    AfterValidator,
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)

from app.models import (
    AccessLevel,
    AffiliationType,
    GoalStatus,
    InstitutionLevel,
    AppointmentStatus,
    NoteKind,
    PatientStatus,
    ReportStatus,
    Role,
    Sex,
)

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_PHONE_RE = re.compile(r"^[0-9+()\-\s]{6,40}$")


def _email(value: str) -> str:
    value = value.strip().lower()
    if not _EMAIL_RE.match(value):
        raise ValueError("El correo electrónico no tiene un formato válido.")
    return value


def _phone(value: str | None) -> str | None:
    if value is None or value.strip() == "":
        return None
    if not _PHONE_RE.match(value.strip()):
        raise ValueError("El teléfono debe tener entre 6 y 40 caracteres: números, espacios, +, - o paréntesis.")
    return value.strip()


_DOCUMENT_RE = re.compile(r"^[0-9A-Za-z.\-/ ]{3,30}$")


def _document(value: str | None) -> str | None:
    if value is None or value.strip() == "":
        return None
    value = " ".join(value.split())
    if not _DOCUMENT_RE.match(value):
        raise ValueError("El documento solo puede tener letras, números, puntos, guiones y barras (3 a 30).")
    return value.upper()


def _optional_name(value: str | None) -> str | None:
    if value is None or value.strip() == "":
        return None
    value = value.strip()
    if len(value) > 100:
        raise ValueError("El texto es demasiado largo (máximo 100 caracteres).")
    return value


def _short(max_len: int):
    """Texto opcional: vacío = None; con espacios recortados y un largo máximo."""
    def check(value: str | None) -> str | None:
        if value is None or value.strip() == "":
            return None
        value = " ".join(value.split())
        if len(value) > max_len:
            raise ValueError(f"El texto es demasiado largo (máximo {max_len} caracteres).")
        return value
    return check


def _not_future(value: date | None) -> date | None:
    if value is not None and value > date.today():
        raise ValueError("La fecha no puede estar en el futuro.")
    if value is not None and value.year < 1900:
        raise ValueError("La fecha no es válida.")
    return value


def _expiry(value: date | None) -> date | None:
    # Puede estar vencida (se registra igual para avisar), pero dentro de un rango sensato.
    if value is not None and not (2000 <= value.year <= 2100):
        raise ValueError("La fecha de vencimiento no es válida.")
    return value


Email = Annotated[str, StringConstraints(max_length=254), AfterValidator(_email)]
OptionalEmail = Annotated[
    str | None,
    AfterValidator(lambda v: None if v is None or v.strip() == "" else _email(v)),
]
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
FullName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=200)]
Phone = Annotated[str | None, AfterValidator(_phone)]
Short20 = Annotated[str | None, AfterValidator(_short(20))]
Short30 = Annotated[str | None, AfterValidator(_short(30))]
Short40 = Annotated[str | None, AfterValidator(_short(40))]
Short80 = Annotated[str | None, AfterValidator(_short(80))]
Short120 = Annotated[str | None, AfterValidator(_short(120))]


def _in_list(options: list[str], what: str):
    def check(value: str | None) -> str | None:
        if value is None or value.strip() == "":
            return None
        if value not in options:
            raise ValueError(f"Elegí {what} de la lista del BPS.")
        return value
    return check


def _bps():
    from app import bps  # import local: evita dependencias circulares al cargar
    return bps


BpsTraining = Annotated[str | None, AfterValidator(lambda v: _in_list(_bps().TRAININGS, "la formación")(v))]
BpsIssuer = Annotated[str | None, AfterValidator(lambda v: _in_list(_bps().DEGREE_ISSUERS, "quién expidió el título")(v))]
BpsActivity = Annotated[str | None, AfterValidator(lambda v: _in_list(_bps().ACTIVITIES, "la actividad")(v))]


BpsName = Annotated[str | None, AfterValidator(_optional_name)]


class BpsPersonData(BaseModel):
    """Datos del técnico para el Cronograma BPS (todo opcional; para profesionales se pide
    completarlos con un aviso)."""
    first_name: BpsName = None
    middle_name: BpsName = None
    last_name: BpsName = None
    second_last_name: BpsName = None
    bps_training: BpsTraining = None
    degree_issuer: BpsIssuer = None


class PatientAddress(BaseModel):
    """Domicilio del paciente (todo opcional)."""
    address_department: Short40 = None
    address_locality: Short80 = None
    address_street: Short120 = None
    address_number: Short20 = None
    address_apartment: Short20 = None
    address_solar: Short20 = None
    address_block: Short20 = None
Document = Annotated[str | None, AfterValidator(_document)]
OptionalName = Annotated[str | None, AfterValidator(_optional_name)]


def _required_document(message: str):
    def check(value: str | None) -> str:
        value = _document(value)
        if value is None:
            raise ValueError(message)
        return value
    return check


GuardianDocument = Annotated[str, AfterValidator(_required_document("Indicá la C.I. del responsable."))]
PersonDocument = Annotated[str, AfterValidator(_required_document("Indicá la C.I."))]
PastDate = Annotated[date | None, AfterValidator(_not_future)]
ExpiryDate = Annotated[date | None, AfterValidator(_expiry)]
Reason = Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=300)]
OptionalReason = Annotated[str, StringConstraints(strip_whitespace=True, max_length=300)] | None
ClinicalText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=20000)]
Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=200)]
# Los informes pueden ser largos ("Generar informe" junta antecedentes, encuadre y cada abordaje).
ReportText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=60000)]


class Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---------- Autenticación ----------


class LoginIn(BaseModel):
    email: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=254)]
    password: Annotated[str, StringConstraints(min_length=1, max_length=128)]


class ChangePasswordIn(BaseModel):
    current_password: Annotated[str, StringConstraints(min_length=1, max_length=128)]
    new_password: Annotated[str, StringConstraints(min_length=1, max_length=128)]


class ClinicOut(Out):
    id: uuid.UUID
    name: str
    timezone: str
    kind: str = "clinic"  # "clinic" o "independent" (espacio de profesional independiente)
    features: list[str] = []  # funciones habilitadas para la clínica (app/features.py)
    logo_updated_at: datetime | None = None  # None = sin logo; si no, cuándo se subió


class UserOut(Out):
    id: uuid.UUID
    email: str
    full_name: str
    role: Role
    specialty_id: uuid.UUID | None
    specialty_name: str | None = None
    is_active: bool
    archived_at: datetime | None = None
    max_concurrent_patients: int = 3
    must_change_password: bool = False
    branch_ids: list[uuid.UUID] = []
    document_number: str | None = None  # None solo en cuentas creadas antes de exigir la C.I.
    phone: str | None = None
    first_name: str | None = None
    middle_name: str | None = None
    last_name: str | None = None
    second_last_name: str | None = None
    bps_training: str | None = None
    degree_issuer: str | None = None
    # Título universitario (solo profesionales): el actual, o None si todavía no lo subió.
    degree_id: uuid.UUID | None = None
    degree_uploaded_at: datetime | None = None


class BranchOut(Out):
    id: uuid.UUID
    name: str
    is_active: bool = True


class SessionOut(BaseModel):
    user: UserOut
    clinic: ClinicOut
    csrf_token: str
    branches: list[BranchOut] = []          # sucursales a las que puede entrar
    active_branch: BranchOut | None = None  # sucursal elegida en esta sesión
    idle_minutes: int = 60  # minutos sin actividad hasta que la sesión se cierra
    expires_at: datetime | None = None  # cierre máximo de la sesión, aunque haya actividad


class BranchChoiceIn(BaseModel):
    branch_id: uuid.UUID


BranchName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=100)]


class BranchIn(BaseModel):
    name: BranchName


class BranchUpdateIn(BaseModel):
    name: BranchName | None = None
    is_active: bool | None = None


# ---------- Usuarios y clínica ----------


class UserCreateIn(BaseModel):
    email: Email
    full_name: FullName
    document_number: PersonDocument
    phone: Phone = None
    role: Role
    specialty_id: uuid.UUID | None = None
    max_concurrent_patients: Annotated[int, Field(ge=1, le=10)] = 3
    # Sin contraseña: Lumen genera una temporal que la persona cambia al entrar por primera vez.
    branch_ids: list[uuid.UUID] = Field(default_factory=list, max_length=50)

    @model_validator(mode="after")
    def _specialty_for_professionals(self):
        if self.role == Role.professional and self.specialty_id is None:
            raise ValueError("Indicá la especialidad del profesional.")
        if self.role != Role.professional:
            self.specialty_id = None
        return self


class UserUpdateIn(BpsPersonData):
    full_name: FullName | None = None
    document_number: PersonDocument | None = None
    phone: Phone = None
    email: Email | None = None
    role: Role | None = None
    specialty_id: uuid.UUID | None = None
    max_concurrent_patients: Annotated[int, Field(ge=1, le=10)] | None = None
    is_active: bool | None = None
    branch_ids: list[uuid.UUID] | None = Field(default=None, max_length=50)


class AccountUpdateIn(BpsPersonData):
    """Datos personales que cada persona puede cambiar en "Mi cuenta"."""
    full_name: FullName | None = None
    document_number: PersonDocument | None = None
    phone: Phone = None


class ProfessionalOut(Out):
    id: uuid.UUID
    full_name: str
    specialty_id: uuid.UUID | None
    specialty_name: str | None = None
    branch_ids: list[uuid.UUID] = []


SpecialtyName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=80)]


class SpecialtyIn(BaseModel):
    name: SpecialtyName


class SpecialtyUpdateIn(BaseModel):
    name: SpecialtyName | None = None
    is_active: bool | None = None
    bps_activity: BpsActivity = None  # "" o null: quitarla


class SpecialtyOut(Out):
    id: uuid.UUID
    name: str
    is_active: bool
    professional_count: int = 0
    bps_activity: str | None = None
    bps_activity_auto: str | None = None  # la que se usa si no se eligió una (por el nombre)


class ClinicProviderData(BaseModel):
    """Datos de la clínica como proveedor del BPS (formulario de AYEX). Todo opcional."""
    bps_provider_number: Short30 = None
    bps_company_number: Short30 = None
    phone: Phone = None
    email: OptionalEmail = None
    address_street: Short120 = None
    address_number: Short20 = None
    address_locality: Short80 = None
    address_department: Short40 = None
    address_annex: Short40 = None
    transport_included: bool | None = None
    monthly_budget: Short40 = None
    # Arancel AYEX (lo que paga el BPS por paciente y por mes). Se usa en "Pagos BPS".
    ayex_fee: Annotated[Decimal, Field(gt=0, le=Decimal("9999999.99"), decimal_places=2)] | None = None


class ClinicUpdateIn(ClinicProviderData):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=200)] | None = None


class ClinicDetailOut(ClinicOut):
    bps_provider_number: str | None = None
    bps_company_number: str | None = None
    phone: str | None = None
    email: str | None = None
    address_street: str | None = None
    address_number: str | None = None
    address_locality: str | None = None
    address_department: str | None = None
    address_annex: str | None = None
    transport_included: bool | None = None
    monthly_budget: str | None = None
    ayex_fee: float | None = None


# ---------- Pacientes ----------


class PatientCreateIn(PatientAddress):
    first_name: Name
    middle_name: OptionalName = None
    last_name: Name
    second_last_name: OptionalName = None
    document_number: Document = None
    sex: Sex | None = None
    affiliation: AffiliationType  # obligatorio: Privado, AYEX, Tutela Militar o Tutela Policial
    ayex_expires_on: ExpiryDate = None  # obligatorio si es AYEX (lo controla la ruta de alta)
    birth_date: PastDate = None
    phone: Phone = None
    email: OptionalEmail = None
    responsible_professional_id: uuid.UUID | None = None
    branch_id: uuid.UUID | None = None  # sin indicar: la sucursal activa de la sesión


class PatientUpdateIn(PatientAddress):
    first_name: Name | None = None
    middle_name: OptionalName = None
    last_name: Name | None = None
    second_last_name: OptionalName = None
    document_number: Document = None
    sex: Sex | None = None
    affiliation: AffiliationType | None = None  # no se puede dejar vacío (lo controla la ruta)
    ayex_expires_on: ExpiryDate = None
    birth_date: PastDate = None
    phone: Phone = None
    email: OptionalEmail = None
    status: PatientStatus | None = None
    branch_id: uuid.UUID | None = None


class PatientOut(Out):
    id: uuid.UUID
    first_name: str
    middle_name: str | None = None
    last_name: str
    second_last_name: str | None = None
    document_number: str | None = None
    sex: Sex | None = None
    affiliation: AffiliationType
    ayex_expires_on: date | None = None
    birth_date: date | None
    phone: str | None
    email: str | None
    status: PatientStatus
    created_at: datetime
    branch_id: uuid.UUID
    address_department: str | None = None
    address_locality: str | None = None
    address_street: str | None = None
    address_number: str | None = None
    address_apartment: str | None = None
    address_solar: str | None = None
    address_block: str | None = None


class PatientListItem(PatientOut):
    branch_name: str | None = None
    responsible_name: str | None = None
    responsible_id: uuid.UUID | None = None
    collaborator_names: list[str] = []  # otros profesionales que trabajan con el paciente
    no_shows_month: int = 0  # inasistencias en el mes en curso (se reinicia cada mes)


class PatientDetailOut(PatientOut):
    my_access_level: AccessLevel | None = None
    can_view_clinical: bool = False
    can_view_reports: bool = False
    can_edit: bool = False
    can_manage_access: bool = False
    responsible_id: uuid.UUID | None = None  # para proponerlo al dar un turno desde la ficha
    responsible_name: str | None = None
    collaborator_names: list[str] = []
    future_appointments: int = 0  # turnos programados a futuro (con cualquier profesional)
    branch_name: str | None = None


# ---------- Responsables / tutores ----------


class GuardianIn(BaseModel):
    first_name: Name  # primer nombre
    middle_name: OptionalName = None
    last_name: Name  # primer apellido
    second_last_name: OptionalName = None
    document_number: GuardianDocument
    relationship: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=60)]
    phone: Phone = None
    email: OptionalEmail = None
    is_primary: bool = False
    notes: OptionalReason = None


class GuardianUpdateIn(BaseModel):
    first_name: Name | None = None
    middle_name: OptionalName = None
    last_name: Name | None = None
    second_last_name: OptionalName = None
    document_number: GuardianDocument | None = None
    relationship: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=60)] | None = None
    phone: Phone = None
    email: OptionalEmail = None
    is_primary: bool | None = None
    notes: OptionalReason = None


class GuardianOut(Out):
    id: uuid.UUID
    full_name: str
    first_name: str | None = None  # None solo en responsables cargados antes de separarlos
    middle_name: str | None = None
    last_name: str | None = None
    second_last_name: str | None = None
    document_number: str | None = None  # None solo en responsables cargados antes de exigirla
    relationship: str
    phone: str | None
    email: str | None
    is_primary: bool
    notes: str | None


# ---------- Instituciones educativas ----------


InstitutionName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=200)]


class InstitutionIn(BaseModel):
    name: InstitutionName
    level: InstitutionLevel
    phone: Phone = None
    email: OptionalEmail = None
    is_current: bool = True


class InstitutionUpdateIn(BaseModel):
    name: InstitutionName | None = None
    level: InstitutionLevel | None = None
    phone: Phone = None
    email: OptionalEmail = None
    is_current: bool | None = None


class InstitutionOut(Out):
    id: uuid.UUID
    name: str
    level: InstitutionLevel
    phone: str | None
    email: str | None
    is_current: bool


# ---------- Accesos ----------


class AccessGrantIn(BaseModel):
    professional_id: uuid.UUID
    level: AccessLevel = AccessLevel.collaborator
    reason: OptionalReason = None


class AccessRevokeIn(BaseModel):
    reason: Reason


class AccessOut(Out):
    id: uuid.UUID
    user_id: uuid.UUID
    user_name: str
    level: AccessLevel
    reason: str | None
    granted_by_name: str
    granted_at: datetime
    revoked_by_name: str | None
    revoked_at: datetime | None
    revoke_reason: str | None
    future_appointments: int = 0  # turnos programados a futuro de ese profesional con el paciente


class ResponsibleChangeIn(BaseModel):
    professional_id: uuid.UUID
    # Obligatorio al CAMBIAR un responsable; opcional al asignar a un paciente sin responsable.
    reason: OptionalReason = None
    # Turnos futuros del responsable anterior con el paciente: pasarlos al nuevo o cancelarlos.
    move_appointments: bool = True


class AppointmentDecisionIn(BaseModel):
    appointment_id: uuid.UUID
    action: Literal["cancel", "move"]
    professional_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def _move_needs_professional(self):
        if self.action == "move" and self.professional_id is None:
            raise ValueError("Indicá a qué profesional pasar el turno.")
        return self


class ReassignmentIn(BaseModel):
    patient_id: uuid.UUID
    professional_id: uuid.UUID


class UserArchiveIn(BaseModel):
    """Al eliminar a un profesional responsable: nuevo responsable para cada paciente."""
    reassignments: list[ReassignmentIn] = Field(default_factory=list, max_length=2000)
    appointments: list[AppointmentDecisionIn] = Field(default_factory=list, max_length=5000)
    cancel_reason: OptionalReason = None


class ResponsiblePatientOut(BaseModel):
    id: uuid.UUID
    full_name: str
    document_number: str | None
    status: PatientStatus


# ---------- Agenda ----------


class AvailabilityIn(BaseModel):
    professional_id: uuid.UUID
    weekday: Annotated[int, Field(ge=0, le=6)]
    start_time: time
    end_time: time

    @model_validator(mode="after")
    def _range(self):
        if self.end_time <= self.start_time:
            raise ValueError("La hora de fin debe ser posterior a la de inicio.")
        return self


class AvailabilityOut(Out):
    id: uuid.UUID
    professional_id: uuid.UUID
    branch_id: uuid.UUID
    branch_name: str | None = None
    weekday: int
    start_time: time
    end_time: time


class _TimeRange(BaseModel):
    starts_at: AwareDatetime
    ends_at: AwareDatetime

    @model_validator(mode="after")
    def _range(self):
        if self.ends_at <= self.starts_at:
            raise ValueError("La hora de fin debe ser posterior a la de inicio.")
        if (self.ends_at - self.starts_at).total_seconds() > 4 * 3600:
            raise ValueError("Un turno no puede durar más de 4 horas.")
        return self


class AppointmentCreateIn(_TimeRange):
    patient_id: uuid.UUID
    professional_id: uuid.UUID
    confirm_past: bool = False  # true: la persona confirmó que el turno es en una fecha pasada


class AppointmentRescheduleIn(_TimeRange):
    reason: Reason  # por qué se reprograma: queda en la ficha del paciente (pestaña Turnos)
    confirm_past: bool = False


class AppointmentCancelIn(BaseModel):
    reason: Reason


class AppointmentStatusIn(BaseModel):
    status: AppointmentStatus
    reason: OptionalReason = None  # por qué no vino (solo al marcar ausente; opcional)

    @model_validator(mode="after")
    def _only_outcomes(self):
        if self.status not in (AppointmentStatus.completed, AppointmentStatus.no_show):
            raise ValueError("Solo se puede marcar como realizado o ausente.")
        if self.reason and self.status != AppointmentStatus.no_show:
            raise ValueError("El motivo solo se escribe al marcar el turno como ausente.")
        return self


class AppointmentOut(Out):
    id: uuid.UUID
    patient_id: uuid.UUID
    patient_name: str
    professional_id: uuid.UUID
    professional_name: str
    branch_id: uuid.UUID
    branch_name: str | None = None
    starts_at: datetime
    ends_at: datetime
    status: AppointmentStatus
    cancel_reason: str | None
    rescheduled_to_id: uuid.UUID | None
    reschedule_reason: str | None = None
    rescheduled_to_starts_at: datetime | None = None  # nueva fecha y hora, si se reprogramó
    no_show_reason: str | None = None  # por qué no vino, si se marcó ausente


class AbsenceOut(BaseModel):
    """Un turno marcado como ausente, en el historial del paciente (pestaña Turnos)."""
    id: uuid.UUID
    starts_at: datetime
    professional_name: str
    branch_name: str | None
    reason: str | None
    marked_by: str | None
    marked_at: datetime | None


class RescheduleOut(BaseModel):
    """Una reprogramación en el historial del paciente (pestaña Turnos)."""
    id: uuid.UUID  # el turno original
    from_starts_at: datetime
    to_starts_at: datetime | None
    to_status: AppointmentStatus | None  # cómo quedó el turno nuevo
    professional_name: str
    to_professional_name: str | None  # si pasó a otro profesional
    reason: str | None
    rescheduled_by: str | None
    rescheduled_at: datetime | None


# ---------- Historia clínica ----------


class NoteCreateIn(BaseModel):
    kind: NoteKind
    session_date: PastDate = None
    content: ClinicalText
    institution_id: uuid.UUID | None = None  # obligatorio solo para kind="institution"


class NoteCorrectIn(BaseModel):
    content: ClinicalText
    reason: Reason
    # Opcional: fecha corregida (si no se manda, se conserva la de la versión anterior).
    session_date: PastDate = None


class NoteOut(Out):
    id: uuid.UUID
    patient_id: uuid.UUID
    author_id: uuid.UUID
    author_name: str
    kind: NoteKind
    session_date: date | None
    content: str
    supersedes_id: uuid.UUID | None
    correction_reason: str | None
    superseded_by_id: uuid.UUID | None
    institution_id: uuid.UUID | None = None
    created_at: datetime


# ---------- Informes ----------


class ReportCreateIn(BaseModel):
    title: Title
    content: ReportText
    # Profesionales que firman además del autor ("Generar informe": quienes escribieron su abordaje).
    signer_ids: list[uuid.UUID] = Field(default_factory=list, max_length=20)
    # "Generar informe": versiones de las secciones con que se armó (solo el responsable).
    section_version_ids: list[uuid.UUID] | None = Field(None, max_length=200)


class ReportUpdateIn(BaseModel):
    title: Title | None = None
    content: ReportText | None = None
    # "Actualizar con lo último" de un informe generado: se rearma con las versiones vigentes.
    signer_ids: list[uuid.UUID] | None = Field(None, max_length=20)
    section_version_ids: list[uuid.UUID] | None = Field(None, max_length=200)


class ReportSummaryOut(Out):
    generated: bool = False  # armado con "Generar informe" (lo cierra el responsable)
    id: uuid.UUID
    patient_id: uuid.UUID
    author_id: uuid.UUID
    author_name: str
    title: str
    status: ReportStatus
    created_at: datetime
    updated_at: datetime
    finalized_at: datetime | None


class ReportSignerOut(BaseModel):
    user_id: uuid.UUID
    name: str
    specialty: str | None = None


class ReportOut(ReportSummaryOut):
    content: str
    signers: list[ReportSignerOut] = []  # vacío = firma solo el autor


class ReportPersonOut(BaseModel):
    user_id: uuid.UUID
    name: str
    specialty: str | None = None


class ReportReadinessOut(BaseModel):
    """Qué falta para poder finalizar un informe generado."""
    stale: bool  # alguna sección o abordaje cambió después de generarlo
    missing: list[ReportPersonOut]  # profesionales con acceso que no escribieron su abordaje
    excluded: list[ReportPersonOut]  # marcados como "no participa en este informe"
    can_close: bool  # quien consulta es el responsable y autor del borrador
    responsible_name: str | None


class ReportParticipationIn(BaseModel):
    user_id: uuid.UUID
    participates: bool


# ---------- Plan de tratamiento ----------

GoalText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=2000)]
GoalNote = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=5000)]


class GoalIn(BaseModel):
    area: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=80)]
    description: GoalText
    target_date: date | None = None


class GoalUpdateIn(BaseModel):
    note: GoalNote
    progress: int | None = Field(default=None, ge=0, le=100)
    session_date: PastDate = None
    new_status: GoalStatus | None = None


class GoalUpdateOut(BaseModel):
    id: uuid.UUID
    author_name: str
    session_date: date | None
    progress: int
    new_status: GoalStatus | None
    note: str
    created_at: datetime


class GoalOut(BaseModel):
    id: uuid.UUID
    area: str
    description: str
    target_date: date | None
    status: GoalStatus
    progress: int
    created_by_name: str
    created_at: datetime
    updates: list[GoalUpdateOut] = []


# ---------- Archivos ----------


class FileOut(Out):
    id: uuid.UUID
    original_name: str
    content_type: str
    size_bytes: int
    description: str | None
    uploaded_by_name: str
    created_at: datetime
    withdrawn_at: datetime | None
    withdrawn_by_name: str | None
    withdraw_reason: str | None
    can_withdraw: bool = False
    institution_id: uuid.UUID | None = None
    institution_name: str | None = None


class FileWithdrawIn(BaseModel):
    reason: Reason


# ---------- Auditoría ----------


class AuditOut(Out):
    id: int
    created_at: datetime
    actor_name: str | None
    action: str
    entity_type: str | None
    entity_id: str | None
    patient_id: uuid.UUID | None
    patient_name: str | None = None  # "Apellido, Nombre"
    details: dict


# ---------- Mensajes de validación en español ----------

VALIDATION_MESSAGES = {
    "missing": "Este campo es obligatorio.",
    "string_too_short": "El texto es demasiado corto.",
    "string_too_long": "El texto es demasiado largo.",
    "enum": "El valor elegido no es válido.",
    "uuid_parsing": "El identificador no es válido.",
    "date_from_datetime_parsing": "La fecha no es válida.",
    "date_parsing": "La fecha no es válida.",
    "datetime_parsing": "La fecha y hora no son válidas.",
    "timezone_aware": "La fecha y hora deben incluir zona horaria.",
    "time_parsing": "La hora no es válida.",
    "int_parsing": "Debe ser un número entero.",
    "greater_than_equal": "El valor es demasiado bajo.",
    "less_than_equal": "El valor es demasiado alto.",
    "json_invalid": "El contenido enviado no es JSON válido.",
}


def validation_message(err: dict) -> str:
    """Texto en español para un error de pydantic, sin repetir el valor enviado."""
    if err.get("type") == "value_error":
        return str(err.get("msg", "")).removeprefix("Value error, ")
    return VALIDATION_MESSAGES.get(err.get("type", ""), "El valor no es válido.")
