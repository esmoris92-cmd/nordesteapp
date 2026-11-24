"""Modelos de la base de datos.

Decisión de aislamiento entre clínicas
--------------------------------------
Cada tabla con datos de una clínica tiene la columna ``clinic_id``. Además, las
referencias entre tablas usan claves foráneas *compuestas* ``(clinic_id, id)``:
por ejemplo, un turno apunta a ``(clinic_id, patient_id)`` del paciente. Así la
propia base de datos impide guardar un turno, nota o acceso que mezcle una clínica
con un paciente o profesional de otra, aunque el código tuviera un error.

Las tablas ``clinical_notes`` y ``audit_log`` son de solo-agregar: un disparador
(trigger) de PostgreSQL rechaza cualquier UPDATE o DELETE (ver la migración inicial).
"""

import enum
import uuid
from datetime import date, datetime, time

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    LargeBinary,
    Numeric,
    SmallInteger,
    String,
    Text,
    Time,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


# ---------- Valores permitidos ----------


class Role(str, enum.Enum):
    admin = "admin"  # administra clínica, usuarios y accesos; no lee historia clínica
    reception = "reception"  # gestiona pacientes (datos de contacto) y agenda
    professional = "professional"  # atiende pacientes autorizados; historia e informes


class ClinicKind(str, enum.Enum):
    clinic = "clinic"  # clínica o centro: varias cuentas, roles y sucursales
    independent = "independent"  # profesional independiente: una sola cuenta (el titular)


class PatientStatus(str, enum.Enum):
    active = "active"
    paused = "paused"
    discharged = "discharged"
    inactive = "inactive"


class Sex(str, enum.Enum):
    male = "male"
    female = "female"
    unspecified = "unspecified"


class AffiliationType(str, enum.Enum):
    """Tipo de afiliación (cobertura) del paciente."""

    private = "private"    # Privado
    ayex = "ayex"          # AYEX
    military = "military"  # Tutela Militar
    police = "police"      # Tutela Policial


class GoalStatus(str, enum.Enum):
    """Estado de un objetivo del plan de tratamiento."""

    active = "active"              # En curso
    achieved = "achieved"          # Logrado
    discontinued = "discontinued"  # Discontinuado


class AccessLevel(str, enum.Enum):
    responsible = "responsible"  # profesional a cargo del paciente
    collaborator = "collaborator"  # acceso compartido autorizado expresamente


class AppointmentStatus(str, enum.Enum):
    scheduled = "scheduled"
    completed = "completed"
    no_show = "no_show"
    cancelled = "cancelled"
    rescheduled = "rescheduled"


class NoteKind(str, enum.Enum):
    session = "session"  # nota de sesión
    background = "background"  # antecedentes pertinentes
    progress = "progress"  # evolución
    anamnesis = "anamnesis"  # anamnesis
    interview = "interview"  # entrevista
    evaluation = "evaluation"  # evaluación
    institution = "institution"  # reporte sobre/para la institución educativa (lleva institution_id)


class InstitutionLevel(str, enum.Enum):
    inicial = "inicial"  # educación inicial (jardín)
    primaria = "primaria"
    secundaria = "secundaria"
    utu = "utu"  # educación técnica (UTU)
    universidad = "universidad"
    otra = "otra"


class CashMovementKind(str, enum.Enum):
    income = "income"  # entrada de dinero
    expense = "expense"  # salida de dinero


class ReportStatus(str, enum.Enum):
    draft = "draft"
    final = "final"


def _in(column: str, enum_cls: type[enum.Enum]) -> str:
    values = ", ".join(f"'{e.value}'" for e in enum_cls)
    return f"{column} IN ({values})"


def _created_at() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )


# ---------- Tablas ----------


class Clinic(Base):
    __tablename__ = "clinics"
    __table_args__ = (CheckConstraint(_in("kind", ClinicKind), name="ck_clinics_kind"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    # Tipo de espacio: clínica (lo habitual) o profesional independiente. En un espacio
    # independiente la única cuenta es un profesional "titular", que además de atender
    # carga sus pacientes y los datos del consultorio (ver CurrentUser.is_titular).
    kind: Mapped[str] = mapped_column(String(20), nullable=False, default=ClinicKind.clinic.value,
                                      server_default=ClinicKind.clinic.value)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="America/Montevideo")
    # Datos de la clínica como proveedor del BPS (para el formulario de AYEX). Opcionales.
    bps_provider_number: Mapped[str | None] = mapped_column(String(30))
    bps_company_number: Mapped[str | None] = mapped_column(String(30))
    phone: Mapped[str | None] = mapped_column(String(40))
    email: Mapped[str | None] = mapped_column(String(254))
    address_street: Mapped[str | None] = mapped_column(String(120))
    address_number: Mapped[str | None] = mapped_column(String(20))
    address_locality: Mapped[str | None] = mapped_column(String(80))
    address_department: Mapped[str | None] = mapped_column(String(40))
    address_annex: Mapped[str | None] = mapped_column(String(40))
    transport_included: Mapped[bool | None] = mapped_column(Boolean)  # ¿incluye transporte?
    monthly_budget: Mapped[str | None] = mapped_column(String(40))  # solo instituciones privadas
    # Arancel AYEX: lo que paga el BPS por paciente y por mes (para controlar sus pagos).
    ayex_fee: Mapped[float | None] = mapped_column(Numeric(12, 2))
    # Suspendida por el dueño del sistema: nadie de la clínica puede entrar (no se borra nada).
    suspended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Datos borrados por el dueño del sistema (app/clinic_purge.py): la fila queda solo con el
    # nombre y las fechas, porque la auditoría del dueño la nombra.
    purged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Funciones que el dueño del sistema deshabilitó para esta clínica (ver app/features.py).
    # Vacía = todo activado. No se borra ningún dato al deshabilitar.
    disabled_features: Mapped[list[str]] = mapped_column(
        ARRAY(String(40)), nullable=False, default=list, server_default="{}")
    # Logo de la clínica (PNG o JPG, hasta 1 MB) para el encabezado de lo que se imprime.
    # Se carga solo cuando se pide (deferred), así no viaja en cada consulta de la clínica.
    logo: Mapped[bytes | None] = mapped_column(LargeBinary, deferred=True)
    logo_content_type: Mapped[str | None] = mapped_column(String(20))
    logo_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _created_at()

    @property
    def features(self) -> list[str]:
        """Funciones activas (para la sesión de la clínica)."""
        from app.features import enabled_features
        return enabled_features(self.disabled_features)


class Branch(Base):
    """Sucursal de la clínica (por ejemplo Central, Pando, Anexo). No se borra: se desactiva."""

    __tablename__ = "branches"
    __table_args__ = (
        UniqueConstraint("clinic_id", "id", name="uq_branches_clinic_id"),
        Index("uq_branches_clinic_name", "clinic_id", text("lower(name)"), unique=True),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    clinic_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("clinics.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = _created_at()


class UserBranch(Base):
    """Sucursal a la que puede entrar una cuenta (Administración entra a todas sin esta lista)."""

    __tablename__ = "user_branches"
    __table_args__ = (
        ForeignKeyConstraint(["clinic_id", "user_id"], ["users.clinic_id", "users.id"]),
        ForeignKeyConstraint(["clinic_id", "branch_id"], ["branches.clinic_id", "branches.id"]),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    branch_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    clinic_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)


class Specialty(Base):
    """Especialidad profesional (psicología, fonoaudiología...). Cada clínica tiene su lista,
    que Administración puede ampliar. No se borran: se desactivan."""

    __tablename__ = "specialties"
    __table_args__ = (
        UniqueConstraint("clinic_id", "id", name="uq_specialties_clinic_id"),
        Index("uq_specialties_clinic_name", "clinic_id", text("lower(name)"), unique=True),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    clinic_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("clinics.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    bps_activity: Mapped[str | None] = mapped_column(String(80))  # actividad del Cronograma BPS
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = _created_at()


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("clinic_id", "id", name="uq_users_clinic_id"),
        CheckConstraint(_in("role", Role), name="ck_users_role"),
        ForeignKeyConstraint(["clinic_id", "specialty_id"], ["specialties.clinic_id", "specialties.id"]),
        CheckConstraint("archived_at IS NULL OR is_active = false", name="ck_users_archived_inactive"),
        CheckConstraint("max_concurrent_patients BETWEEN 1 AND 10", name="ck_users_max_concurrent"),
        Index("uq_users_clinic_document", "clinic_id", "document_number", unique=True,
              postgresql_where=text("document_number IS NOT NULL")),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    clinic_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("clinics.id"), nullable=False, index=True)
    email: Mapped[str] = mapped_column(String(254), nullable=False, unique=True)
    full_name: Mapped[str] = mapped_column(String(200), nullable=False)
    # C.I. de la persona (obligatoria; las cuentas creadas antes la completan en "Mi cuenta").
    document_number: Mapped[str | None] = mapped_column(String(30))
    phone: Mapped[str | None] = mapped_column(String(40))
    # Para el Cronograma BPS (profesionales): nombres y apellidos como en la C.I., formación
    # académica y quién expidió el título (listas del BPS, ver app/bps.py).
    first_name: Mapped[str | None] = mapped_column(String(100))
    middle_name: Mapped[str | None] = mapped_column(String(100))
    last_name: Mapped[str | None] = mapped_column(String(100))
    second_last_name: Mapped[str | None] = mapped_column(String(100))
    bps_training: Mapped[str | None] = mapped_column(String(60))
    degree_issuer: Mapped[str | None] = mapped_column(String(60))
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    specialty_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    failed_login_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # True tras un restablecimiento: debe elegir una contraseña nueva antes de usar Nordeste.
    must_change_password: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False,
                                                       server_default=text("false"))
    # Cuántos pacientes puede atender a la vez (turnos superpuestos). Solo aplica a profesionales.
    max_concurrent_patients: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=3)
    # "Eliminar" archiva la cuenta: no se borra para conservar la trazabilidad.
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class AuthSession(Base):
    """Sesión iniciada. Solo se guarda el hash del token, nunca el token."""

    __tablename__ = "auth_sessions"
    __table_args__ = (
        ForeignKeyConstraint(["clinic_id", "user_id"], ["users.clinic_id", "users.id"]),
        ForeignKeyConstraint(["clinic_id", "branch_id"], ["branches.clinic_id", "branches.id"]),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    csrf_token: Mapped[str] = mapped_column(String(64), nullable=False)
    clinic_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    created_at: Mapped[datetime] = _created_at()
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Sucursal elegida al entrar (puede cambiarse sin volver a iniciar sesión).
    branch_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))


class Patient(Base):
    __tablename__ = "patients"
    __table_args__ = (
        UniqueConstraint("clinic_id", "id", name="uq_patients_clinic_id"),
        CheckConstraint(_in("status", PatientStatus), name="ck_patients_status"),
        ForeignKeyConstraint(["clinic_id", "created_by"], ["users.clinic_id", "users.id"]),
        Index("ix_patients_clinic_last_name", "clinic_id", "last_name"),
        CheckConstraint(f"sex IS NULL OR {_in('sex', Sex)}", name="ck_patients_sex"),
        CheckConstraint(_in("affiliation", AffiliationType), name="ck_patients_affiliation"),
        ForeignKeyConstraint(["clinic_id", "branch_id"], ["branches.clinic_id", "branches.id"]),
        Index("ix_patients_clinic_branch", "clinic_id", "branch_id"),
        Index("ix_patients_clinic_ayex_expires", "clinic_id", "ayex_expires_on"),
        # Un mismo documento no puede repetirse dentro de una clínica.
        Index("uq_patients_clinic_document", "clinic_id", "document_number", unique=True,
              postgresql_where=text("document_number IS NOT NULL")),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    clinic_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("clinics.id"), nullable=False)
    first_name: Mapped[str] = mapped_column(String(100), nullable=False)
    middle_name: Mapped[str | None] = mapped_column(String(100))
    last_name: Mapped[str] = mapped_column(String(100), nullable=False)
    second_last_name: Mapped[str | None] = mapped_column(String(100))
    # Documento de identidad: dato sensible. Nunca se copia a la auditoría ni a los registros.
    document_number: Mapped[str | None] = mapped_column(String(30))
    sex: Mapped[str | None] = mapped_column(String(20))
    affiliation: Mapped[str] = mapped_column(String(20), nullable=False)
    # Sucursal del paciente. AYEX, Tutela Militar y Tutela Policial se atienden solo aquí;
    # Privado, en cualquiera.
    branch_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    birth_date: Mapped[date | None] = mapped_column(Date)
    # Vencimiento del AYEX: obligatorio al ingresar o pasar a AYEX (lo controla la API).
    ayex_expires_on: Mapped[date | None] = mapped_column(Date)
    phone: Mapped[str | None] = mapped_column(String(40))
    email: Mapped[str | None] = mapped_column(String(254))
    # Domicilio (opcional; lo usa el formulario de AYEX del BPS).
    address_department: Mapped[str | None] = mapped_column(String(40))
    address_locality: Mapped[str | None] = mapped_column(String(80))
    address_street: Mapped[str | None] = mapped_column(String(120))
    address_number: Mapped[str | None] = mapped_column(String(20))
    address_apartment: Mapped[str | None] = mapped_column(String(20))
    address_solar: Mapped[str | None] = mapped_column(String(20))
    address_block: Mapped[str | None] = mapped_column(String(20))  # manzana
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=PatientStatus.active.value)
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class PatientGuardian(Base):
    """Responsable o tutor de un paciente (p. ej., madre de un paciente menor).
    Son datos administrativos de contacto, no clínicos."""

    __tablename__ = "patient_guardians"
    __table_args__ = (
        ForeignKeyConstraint(["clinic_id", "patient_id"], ["patients.clinic_id", "patients.id"]),
        ForeignKeyConstraint(["clinic_id", "created_by"], ["users.clinic_id", "users.id"]),
        Index("ix_patient_guardians_patient", "clinic_id", "patient_id"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    clinic_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    patient_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    full_name: Mapped[str] = mapped_column(String(200), nullable=False)
    # Primer nombre y primer apellido por separado (los pide el formulario de AYEX). El nombre
    # completo se arma con ellos; los cargados antes los completan al editarse.
    first_name: Mapped[str | None] = mapped_column(String(100))
    middle_name: Mapped[str | None] = mapped_column(String(100))
    last_name: Mapped[str | None] = mapped_column(String(100))
    second_last_name: Mapped[str | None] = mapped_column(String(100))
    # C.I. del responsable: obligatoria al crear o editar (la API la exige); los cargados antes
    # de la migración 0018 pueden no tenerla hasta que alguien edite sus datos.
    document_number: Mapped[str | None] = mapped_column(String(30))
    relationship: Mapped[str] = mapped_column(String(60), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(40))
    email: Mapped[str | None] = mapped_column(String(254))
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    notes: Mapped[str | None] = mapped_column(String(300))
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class PatientAccess(Base):
    """Autorización de un profesional sobre un paciente.

    Nunca se borra: revocar completa ``revoked_at``/``revoked_by``. Así queda
    el historial de quién concedió y quién retiró cada acceso.
    """

    __tablename__ = "patient_access"
    __table_args__ = (
        CheckConstraint(_in("level", AccessLevel), name="ck_patient_access_level"),
        ForeignKeyConstraint(["clinic_id", "patient_id"], ["patients.clinic_id", "patients.id"]),
        ForeignKeyConstraint(["clinic_id", "user_id"], ["users.clinic_id", "users.id"]),
        ForeignKeyConstraint(["clinic_id", "granted_by"], ["users.clinic_id", "users.id"]),
        ForeignKeyConstraint(["clinic_id", "revoked_by"], ["users.clinic_id", "users.id"]),
        CheckConstraint(
            "(revoked_at IS NULL) = (revoked_by IS NULL)", name="ck_patient_access_revoked_pair"
        ),
        Index(
            "uq_patient_access_active", "patient_id", "user_id", unique=True,
            postgresql_where=text("revoked_at IS NULL"),
        ),
        Index(
            "uq_patient_access_one_responsible", "patient_id", unique=True,
            postgresql_where=text("revoked_at IS NULL AND level = 'responsible'"),
        ),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    clinic_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    patient_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    level: Mapped[str] = mapped_column(String(20), nullable=False)
    reason: Mapped[str | None] = mapped_column(String(300))
    granted_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    granted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    revoked_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoke_reason: Mapped[str | None] = mapped_column(String(300))


class Availability(Base):
    """Bloque semanal de disponibilidad (0 = lunes ... 6 = domingo), en hora de la clínica."""

    __tablename__ = "availability"
    __table_args__ = (
        ForeignKeyConstraint(["clinic_id", "professional_id"], ["users.clinic_id", "users.id"]),
        ForeignKeyConstraint(["clinic_id", "branch_id"], ["branches.clinic_id", "branches.id"],
                             name="fk_availability_branch"),
        CheckConstraint("weekday BETWEEN 0 AND 6", name="ck_availability_weekday"),
        CheckConstraint("end_time > start_time", name="ck_availability_range"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    clinic_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    professional_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    branch_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    weekday: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    start_time: Mapped[time] = mapped_column(Time, nullable=False)
    end_time: Mapped[time] = mapped_column(Time, nullable=False)
    created_at: Mapped[datetime] = _created_at()


class Appointment(Base):
    __tablename__ = "appointments"
    __table_args__ = (
        ForeignKeyConstraint(["clinic_id", "patient_id"], ["patients.clinic_id", "patients.id"]),
        ForeignKeyConstraint(["clinic_id", "professional_id"], ["users.clinic_id", "users.id"]),
        ForeignKeyConstraint(["clinic_id", "created_by"], ["users.clinic_id", "users.id"]),
        ForeignKeyConstraint(["clinic_id", "branch_id"], ["branches.clinic_id", "branches.id"],
                             name="fk_appointments_branch"),
        CheckConstraint(_in("status", AppointmentStatus), name="ck_appointments_status"),
        CheckConstraint("ends_at > starts_at", name="ck_appointments_range"),
        Index("ix_appointments_prof_start", "clinic_id", "professional_id", "starts_at"),
        Index("ix_appointments_branch_start", "clinic_id", "branch_id", "starts_at"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    clinic_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    patient_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    professional_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    branch_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=AppointmentStatus.scheduled.value
    )
    cancel_reason: Mapped[str | None] = mapped_column(String(300))
    rescheduled_to_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("appointments.id"))
    # Por qué se reprogramó (en el turno original). Obligatorio al reprogramar desde la Agenda.
    reschedule_reason: Mapped[str | None] = mapped_column(String(300))
    # Por qué no vino (opcional, al marcarlo como ausente).
    no_show_reason: Mapped[str | None] = mapped_column(String(300))
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class PatientInstitution(Base):
    """Institución educativa a la que va el paciente (escuela, liceo, UTU, universidad…).
    El nombre, el nivel y el contacto son datos administrativos; los reportes y archivos
    sobre la institución son clínicos (notas de tipo "institution" y archivos con
    ``institution_id``) y solo los ven los profesionales con acceso al paciente."""

    __tablename__ = "patient_institutions"
    __table_args__ = (
        ForeignKeyConstraint(["clinic_id", "patient_id"], ["patients.clinic_id", "patients.id"]),
        ForeignKeyConstraint(["clinic_id", "created_by"], ["users.clinic_id", "users.id"]),
        UniqueConstraint("clinic_id", "id", name="uq_patient_institutions_clinic_id"),
        CheckConstraint(_in("level", InstitutionLevel), name="ck_patient_institutions_level"),
        Index("ix_patient_institutions_patient", "clinic_id", "patient_id"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    clinic_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    patient_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    level: Mapped[str] = mapped_column(String(20), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(40))
    email: Mapped[str | None] = mapped_column(String(254))
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class ClinicalNote(Base):
    """Nota de historia clínica. Solo-agregar: las correcciones son notas nuevas
    que apuntan a la anterior con ``supersedes_id`` e indican el motivo."""

    __tablename__ = "clinical_notes"
    __table_args__ = (
        ForeignKeyConstraint(["clinic_id", "patient_id"], ["patients.clinic_id", "patients.id"]),
        ForeignKeyConstraint(["clinic_id", "author_id"], ["users.clinic_id", "users.id"]),
        CheckConstraint(_in("kind", NoteKind), name="ck_clinical_notes_kind"),
        CheckConstraint(
            "(supersedes_id IS NULL) = (correction_reason IS NULL)",
            name="ck_clinical_notes_correction_reason",
        ),
        UniqueConstraint("supersedes_id", name="uq_clinical_notes_supersedes"),
        Index("ix_clinical_notes_patient", "clinic_id", "patient_id", "created_at"),
        ForeignKeyConstraint(["clinic_id", "institution_id"],
                             ["patient_institutions.clinic_id", "patient_institutions.id"],
                             name="fk_clinical_notes_institution"),
        CheckConstraint("(kind = 'institution') = (institution_id IS NOT NULL)",
                        name="ck_clinical_notes_institution"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    clinic_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    patient_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    author_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    session_date: Mapped[date | None] = mapped_column(Date)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    supersedes_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("clinical_notes.id"))
    correction_reason: Mapped[str | None] = mapped_column(String(300))
    institution_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = _created_at()


class AnamnesisVersion(Base):
    """Anamnesis estructurada de un paciente (ficha multidisciplinaria). Hay una por paciente,
    que se va completando: cada guardado es una versión nueva y la vigente es la más reciente.
    Nunca se edita ni se borra una versión (igual que las notas clínicas).

    ``data`` guarda las respuestas como {clave del campo: texto}; las preguntas y su orden
    los define la interfaz (frontend/src/pages/anamnesisForm.ts)."""

    __tablename__ = "anamnesis_versions"
    __table_args__ = (
        ForeignKeyConstraint(["clinic_id", "patient_id"], ["patients.clinic_id", "patients.id"]),
        ForeignKeyConstraint(["clinic_id", "author_id"], ["users.clinic_id", "users.id"]),
        Index("ix_anamnesis_versions_patient", "clinic_id", "patient_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    clinic_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    patient_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    author_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    data: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = _created_at()


class ReportSectionVersion(Base):
    """Secciones del informe que se cargan en la ficha del paciente: Antecedentes, Diagnóstico y
    Encuadre (un texto por paciente) y el Abordaje de cada profesional (con su "En suma" y sus
    "Sugerencias"). Cada guardado es una versión nueva; la vigente es la más reciente de cada
    (sección, profesional). Nunca se editan ni se borran. "Generar informe" las junta."""

    __tablename__ = "report_section_versions"
    __table_args__ = (
        ForeignKeyConstraint(["clinic_id", "patient_id"], ["patients.clinic_id", "patients.id"]),
        ForeignKeyConstraint(["clinic_id", "author_id"], ["users.clinic_id", "users.id"]),
        ForeignKeyConstraint(["clinic_id", "owner_id"], ["users.clinic_id", "users.id"],
                             name="fk_report_section_versions_owner"),
        CheckConstraint("section IN ('antecedentes', 'diagnostico', 'encuadre', 'abordaje')",
                        name="ck_report_section_versions_section"),
        CheckConstraint("(section = 'abordaje') = (owner_id IS NOT NULL)",
                        name="ck_report_section_versions_owner"),
        Index("ix_report_section_versions_patient", "clinic_id", "patient_id", "section", "created_at"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    clinic_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    patient_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    section: Mapped[str] = mapped_column(String(20), nullable=False)
    owner_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))  # profesional (solo abordaje)
    author_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    data: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = _created_at()


class PatientFile(Base):
    """Archivo adjunto de un paciente (PDF o imagen). Es información clínica.

    El contenido se guarda en disco con un nombre aleatorio (``storage_key``), nunca con
    el nombre original. No se borra: retirarlo completa ``withdrawn_*`` y lo oculta.
    """

    __tablename__ = "patient_files"
    __table_args__ = (
        ForeignKeyConstraint(["clinic_id", "patient_id"], ["patients.clinic_id", "patients.id"]),
        ForeignKeyConstraint(["clinic_id", "uploaded_by"], ["users.clinic_id", "users.id"]),
        ForeignKeyConstraint(["clinic_id", "withdrawn_by"], ["users.clinic_id", "users.id"]),
        CheckConstraint("(withdrawn_at IS NULL) = (withdrawn_by IS NULL)", name="ck_patient_files_withdrawn"),
        Index("ix_patient_files_patient", "clinic_id", "patient_id", "created_at"),
        ForeignKeyConstraint(["clinic_id", "institution_id"],
                             ["patient_institutions.clinic_id", "patient_institutions.id"],
                             name="fk_patient_files_institution"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    clinic_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    patient_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    uploaded_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    original_name: Mapped[str] = mapped_column(String(200), nullable=False)
    content_type: Mapped[str] = mapped_column(String(50), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(String(300))
    created_at: Mapped[datetime] = _created_at()
    withdrawn_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    withdrawn_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    withdraw_reason: Mapped[str | None] = mapped_column(String(300))
    institution_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))  # archivo de una institución


class Report(Base):
    """Informe profesional. Editable mientras es borrador; inmutable al finalizarse."""

    __tablename__ = "reports"
    __table_args__ = (
        ForeignKeyConstraint(["clinic_id", "patient_id"], ["patients.clinic_id", "patients.id"]),
        ForeignKeyConstraint(["clinic_id", "author_id"], ["users.clinic_id", "users.id"]),
        CheckConstraint(_in("status", ReportStatus), name="ck_reports_status"),
        Index("ix_reports_patient", "clinic_id", "patient_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    clinic_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    patient_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    author_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(10), nullable=False, default=ReportStatus.draft.value)
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    finalized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Quienes firman el informe ("Generar informe": cada profesional con abordaje, y el autor).
    # [{"user_id", "name", "specialty"}] tal como eran al crearlo. Vacío = firma solo el autor.
    signers: Mapped[list | None] = mapped_column(JSONB)
    # Informe generado ("Generar informe"): versiones de Antecedentes, Diagnóstico, Encuadre y de
    # cada Abordaje con que se armó (para saber si quedó desactualizado). None = informe en blanco.
    section_version_ids: Mapped[list | None] = mapped_column(JSONB)
    # Profesionales con acceso que el responsable marcó como "no participa en este informe".
    excluded_ids: Mapped[list | None] = mapped_column(JSONB)


class AuditEvent(Base):
    """Registro de auditoría. Solo metadatos: nunca contenido clínico ni secretos."""

    __tablename__ = "audit_log"
    __table_args__ = (
        ForeignKeyConstraint(["clinic_id", "actor_id"], ["users.clinic_id", "users.id"]),
        ForeignKeyConstraint(["clinic_id", "patient_id"], ["patients.clinic_id", "patients.id"]),
        Index("ix_audit_clinic_created", "clinic_id", "created_at"),
        Index("ix_audit_clinic_patient", "clinic_id", "patient_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    clinic_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("clinics.id"), nullable=False)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    action: Mapped[str] = mapped_column(String(60), nullable=False)
    entity_type: Mapped[str | None] = mapped_column(String(40))
    entity_id: Mapped[str | None] = mapped_column(String(64))
    patient_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    details: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    ip: Mapped[str | None] = mapped_column(String(45))
    created_at: Mapped[datetime] = _created_at()


class TreatmentGoal(Base):
    """Objetivo del plan de tratamiento de un paciente (información clínica).

    El texto no se edita ni se borra: si cambia, se discontinúa con motivo y se crea otro.
    Solo cambian ``status`` y ``progress`` (siempre a través de un ``GoalUpdate``).
    """

    __tablename__ = "treatment_goals"
    __table_args__ = (
        UniqueConstraint("clinic_id", "id", name="uq_treatment_goals_clinic_id"),
        ForeignKeyConstraint(["clinic_id", "patient_id"], ["patients.clinic_id", "patients.id"]),
        ForeignKeyConstraint(["clinic_id", "created_by"], ["users.clinic_id", "users.id"]),
        CheckConstraint(_in("status", GoalStatus), name="ck_treatment_goals_status"),
        CheckConstraint("progress BETWEEN 0 AND 100", name="ck_treatment_goals_progress"),
        Index("ix_treatment_goals_patient", "clinic_id", "patient_id"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    clinic_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    patient_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    area: Mapped[str] = mapped_column(String(80), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    target_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=GoalStatus.active.value)
    progress: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    created_at: Mapped[datetime] = _created_at()


class GoalUpdate(Base):
    """Registro de avance o cambio de estado de un objetivo. Solo se agrega: nunca se edita."""

    __tablename__ = "goal_updates"
    __table_args__ = (
        ForeignKeyConstraint(["clinic_id", "goal_id"], ["treatment_goals.clinic_id", "treatment_goals.id"]),
        ForeignKeyConstraint(["clinic_id", "author_id"], ["users.clinic_id", "users.id"]),
        CheckConstraint("progress BETWEEN 0 AND 100", name="ck_goal_updates_progress"),
        CheckConstraint(f"new_status IS NULL OR {_in('new_status', GoalStatus)}",
                        name="ck_goal_updates_status"),
        Index("ix_goal_updates_goal", "clinic_id", "goal_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    clinic_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    goal_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    author_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    session_date: Mapped[date | None] = mapped_column(Date)
    progress: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    new_status: Mapped[str | None] = mapped_column(String(20))
    note: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = _created_at()


class ProfessionalDegree(Base):
    """Foto o PDF del título universitario de un profesional (obligatorio: hasta subirlo, Nordeste
    muestra un aviso). Lo ven el propio profesional y Administración.

    Como los archivos de pacientes: se guarda en disco con un nombre aleatorio. Al subir uno
    nuevo, el anterior no se borra: queda marcado como reemplazado (``replaced_at``).
    """

    __tablename__ = "professional_degrees"
    __table_args__ = (
        ForeignKeyConstraint(["clinic_id", "user_id"], ["users.clinic_id", "users.id"]),
        Index("ix_professional_degrees_user", "clinic_id", "user_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    clinic_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    original_name: Mapped[str] = mapped_column(String(200), nullable=False)
    content_type: Mapped[str] = mapped_column(String(50), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    created_at: Mapped[datetime] = _created_at()
    replaced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Notice(Base):
    """Aviso que Recepción o Administración deja a uno o a todos los profesionales. Se les
    muestra en la barra amarilla de arriba hasta que tocan "Entendido". Quien lo dejó (o
    Administración) puede retirarlo; no se borra, queda marcado como retirado."""

    __tablename__ = "notices"
    __table_args__ = (
        ForeignKeyConstraint(["clinic_id", "author_id"], ["users.clinic_id", "users.id"]),
        ForeignKeyConstraint(["clinic_id", "branch_id"], ["branches.clinic_id", "branches.id"]),
        UniqueConstraint("clinic_id", "id", name="uq_notices_clinic_id"),
        Index("ix_notices_clinic_created", "clinic_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    clinic_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    author_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    branch_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))  # sucursal desde donde se dejó
    to_all: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    message: Mapped[str] = mapped_column(String(500), nullable=False)
    created_at: Mapped[datetime] = _created_at()
    withdrawn_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class NoticeRecipient(Base):
    """Cada profesional que recibe un aviso, y cuándo lo marcó como leído."""

    __tablename__ = "notice_recipients"
    __table_args__ = (
        ForeignKeyConstraint(["clinic_id", "notice_id"], ["notices.clinic_id", "notices.id"]),
        ForeignKeyConstraint(["clinic_id", "user_id"], ["users.clinic_id", "users.id"]),
        Index("ix_notice_recipients_user", "clinic_id", "user_id", "read_at"),
    )

    notice_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    clinic_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


# ---------- Caja ----------


class CashRegister(Base):
    """Caja diaria de una sucursal (una por día). Se abre con el efectivo contado al empezar
    y se cierra con el efectivo contado al terminar; Nordeste calcula lo esperado (inicial +
    entradas - salidas) y guarda la diferencia. Cerrada, solo Administración puede reabrirla.
    No se borra."""

    __tablename__ = "cash_registers"
    __table_args__ = (
        ForeignKeyConstraint(["clinic_id", "branch_id"], ["branches.clinic_id", "branches.id"]),
        ForeignKeyConstraint(["clinic_id", "opened_by"], ["users.clinic_id", "users.id"]),
        ForeignKeyConstraint(["clinic_id", "closed_by"], ["users.clinic_id", "users.id"]),
        UniqueConstraint("clinic_id", "id", name="uq_cash_registers_clinic_id"),
        UniqueConstraint("clinic_id", "branch_id", "business_date", name="uq_cash_registers_branch_day"),
        CheckConstraint("opening_amount >= 0", name="ck_cash_registers_opening"),
        CheckConstraint("counted_amount IS NULL OR counted_amount >= 0", name="ck_cash_registers_counted"),
        CheckConstraint("(closed_at IS NULL) = (counted_amount IS NULL) AND (closed_at IS NULL) = "
                        "(expected_amount IS NULL) AND (closed_at IS NULL) = (closed_by IS NULL)",
                        name="ck_cash_registers_closed"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    clinic_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    branch_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    business_date: Mapped[date] = mapped_column(Date, nullable=False)  # día de la caja (hora de la clínica)
    opening_amount: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    opened_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    opened_at: Mapped[datetime] = _created_at()
    # Cierre: lo contado, lo que debía haber según los movimientos, quién y cuándo.
    counted_amount: Mapped[float | None] = mapped_column(Numeric(12, 2))
    expected_amount: Mapped[float | None] = mapped_column(Numeric(12, 2))
    closing_note: Mapped[str | None] = mapped_column(String(300))
    closed_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reopen_count: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0,
                                              server_default=text("0"))


class CashMovement(Base):
    """Entrada o salida de dinero en una caja. No se borra: se anula (con el motivo)."""

    __tablename__ = "cash_movements"
    __table_args__ = (
        ForeignKeyConstraint(["clinic_id", "register_id"], ["cash_registers.clinic_id", "cash_registers.id"]),
        ForeignKeyConstraint(["clinic_id", "created_by"], ["users.clinic_id", "users.id"]),
        ForeignKeyConstraint(["clinic_id", "voided_by"], ["users.clinic_id", "users.id"]),
        CheckConstraint(_in("kind", CashMovementKind), name="ck_cash_movements_kind"),
        CheckConstraint("amount > 0", name="ck_cash_movements_amount"),
        CheckConstraint("(voided_at IS NULL) = (voided_by IS NULL)", name="ck_cash_movements_void"),
        Index("ix_cash_movements_register", "clinic_id", "register_id"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    clinic_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    register_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    kind: Mapped[str] = mapped_column(String(10), nullable=False)
    amount: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    concept: Mapped[str] = mapped_column(String(200), nullable=False)
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    created_at: Mapped[datetime] = _created_at()
    voided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    voided_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    void_reason: Mapped[str | None] = mapped_column(String(200))


# ---------- Dueño del sistema ----------
# Tablas aparte, SIN clinic_id: la cuenta del dueño no pertenece a ninguna clínica y no tiene
# ninguna relación con pacientes, así que no puede ver sus datos ni por un error del código.


class SystemOwner(Base):
    """Quien administra Nordeste como servicio: da de alta y suspende clínicas."""

    __tablename__ = "system_owners"
    __table_args__ = (
        CheckConstraint("NOT totp_enabled OR totp_secret IS NOT NULL", name="ck_system_owners_totp"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    email: Mapped[str] = mapped_column(String(254), nullable=False, unique=True)
    full_name: Mapped[str] = mapped_column(String(200), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    must_change_password: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True,
                                                       server_default=text("true"))
    # Segundo paso al entrar: código de 6 dígitos de una app del celular (TOTP, ver app/totp.py).
    totp_secret: Mapped[str | None] = mapped_column(String(64))
    totp_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False,
                                               server_default=text("false"))
    totp_last_step: Mapped[int | None] = mapped_column(BigInteger)  # un código sirve una sola vez
    failed_login_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = _created_at()


class OwnerSession(Base):
    """Sesión del dueño del sistema. Solo se guarda el hash del token."""

    __tablename__ = "owner_sessions"

    id: Mapped[uuid.UUID] = _uuid_pk()
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    csrf_token: Mapped[str] = mapped_column(String(64), nullable=False)
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("system_owners.id"), nullable=False, index=True)
    created_at: Mapped[datetime] = _created_at()
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class OwnerAuditEvent(Base):
    """Auditoría del dueño del sistema (solo se agregan filas). Solo metadatos."""

    __tablename__ = "owner_audit_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    owner_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("system_owners.id"))
    action: Mapped[str] = mapped_column(String(60), nullable=False)
    clinic_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("clinics.id"))
    target_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    details: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    ip: Mapped[str | None] = mapped_column(String(45))
    created_at: Mapped[datetime] = _created_at()
