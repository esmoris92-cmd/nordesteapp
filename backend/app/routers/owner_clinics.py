"""Pantalla del dueño del sistema: clínicas, alta, suspensión y acceso del administrador.

También se dan de alta los espacios de **profesionales independientes**: una "clínica" de
tipo ``independent`` con un solo consultorio y una sola cuenta, la del profesional titular.
Para el dueño, el titular ocupa el lugar del administrador (se lista y se le restablece la
contraseña igual).

Privacidad: desde acá NUNCA se ven pacientes, turnos, notas ni archivos. De cada clínica solo
se muestran cantidades (sucursales, cuentas, pacientes activos y en pausa) y las cuentas de
Administración, que son las que el dueño necesita para dar soporte. (La única excepción es la
exportación completa de datos, en ``owner_export.py``.)

Pacientes en pausa: el contrato cobra por pacientes ACTIVOS. A un paciente "En pausa" no se le
pueden dar turnos (y al pausarlo se cancelan los futuros), pero se lo puede atender en el mes y
pausarlo antes de la fecha de conteo. Por eso se muestra también cuántos pacientes en pausa
tuvieron algún turno REALIZADO en el mes corriente (en hora de la clínica).

Lo que hace el dueño queda en su propia auditoría y también en la de la clínica (como
"Soporte de Lumen"), así la clínica sabe cuándo se tocó algo de su cuenta.
"""

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, StringConstraints
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app import audit
from app.db import get_db
from app.deps import utcnow
from app.models import (
    Appointment, AppointmentStatus, AuthSession, Branch, Clinic, ClinicKind, OwnerAuditEvent, Patient,
    PatientStatus, Role, Specialty, SystemOwner, User, UserBranch,
)
from app.owner_deps import CurrentOwner, record, require_ready_owner
from app.schemas import Email, FullName, PersonDocument
from app.security import hash_password, temporary_password

router = APIRouter(prefix="/api/owner", tags=["dueño del sistema"])

DEFAULT_SPECIALTIES = ("Psicología", "Terapia ocupacional", "Fonoaudiología")
# Un espacio independiente empieza con lo básico (pacientes, agenda, historia clínica, informes)
# más Informe mensual, Objetivos y Archivos. Estas se pueden habilitar después desde Funciones.
INDEPENDENT_DISABLED_FEATURES = ("caja", "bps", "avisos")
INDEPENDENT_BRANCH_NAME = "Consultorio"

ClinicName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=200)]
BranchName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
ProfessionName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=80)]


class AdminOut(BaseModel):
    id: uuid.UUID
    full_name: str
    email: str
    is_active: bool
    locked: bool
    must_change_password: bool


class ClinicSummaryOut(BaseModel):
    id: uuid.UUID
    name: str
    kind: ClinicKind = ClinicKind.clinic
    created_at: datetime
    suspended_at: datetime | None
    purged_at: datetime | None = None  # datos borrados (queda solo el nombre)
    branches: int
    users: int
    active_patients: int
    paused_patients: int = 0
    paused_with_sessions: int = 0  # en pausa, pero con algún turno realizado este mes
    last_activity: datetime | None
    admins: list[AdminOut]  # en un espacio independiente: el profesional titular


class ClinicCreateIn(BaseModel):
    """Alta de una clínica (con su primer administrador) o de un espacio de profesional
    independiente (los datos ``admin_*`` son entonces los del profesional titular)."""
    kind: ClinicKind = ClinicKind.clinic
    name: ClinicName
    branch_name: BranchName | None = None  # por defecto "Central" (o "Consultorio")
    admin_full_name: FullName
    admin_email: Email
    admin_document: PersonDocument
    profession: ProfessionName | None = None  # obligatoria para un espacio independiente


class TemporaryAccessOut(BaseModel):
    """Contraseña temporal del administrador: se muestra UNA sola vez."""
    full_name: str
    email: str
    temporary_password: str


class ClinicCreatedOut(BaseModel):
    clinic: ClinicSummaryOut
    admin: TemporaryAccessOut


class SuspendIn(BaseModel):
    reason: Annotated[str, StringConstraints(strip_whitespace=True, max_length=300)] = ""


class OwnerAuditOut(BaseModel):
    id: int
    created_at: datetime
    owner_name: str | None
    action: str
    clinic_name: str | None
    target_name: str | None
    details: dict
    ip: str | None


def _counts(db: Session, query) -> dict[uuid.UUID, int]:
    return dict(db.execute(query).all())


def _summaries(db: Session, clinic_ids: list[uuid.UUID] | None = None) -> list[ClinicSummaryOut]:
    query = select(Clinic).order_by(func.lower(Clinic.name))
    if clinic_ids is not None:
        query = query.where(Clinic.id.in_(clinic_ids))
    clinics = db.scalars(query).all()
    branches = _counts(db, select(Branch.clinic_id, func.count()).where(Branch.is_active.is_(True))
                       .group_by(Branch.clinic_id))
    users = _counts(db, select(User.clinic_id, func.count()).where(
        User.is_active.is_(True), User.archived_at.is_(None)).group_by(User.clinic_id))
    patients = _counts(db, select(Patient.clinic_id, func.count()).where(
        Patient.status == PatientStatus.active.value).group_by(Patient.clinic_id))
    paused = _counts(db, select(Patient.clinic_id, func.count()).where(
        Patient.status == PatientStatus.paused.value).group_by(Patient.clinic_id))
    month = lambda value: func.to_char(func.timezone(Clinic.timezone, value), "YYYY-MM")  # noqa: E731
    paused_seen = _counts(db, (
        select(Patient.clinic_id, func.count(func.distinct(Patient.id)))
        .join(Appointment, (Appointment.patient_id == Patient.id) & (Appointment.clinic_id == Patient.clinic_id))
        .join(Clinic, Clinic.id == Patient.clinic_id)
        .where(Patient.status == PatientStatus.paused.value,
               Appointment.status == AppointmentStatus.completed.value,
               month(Appointment.starts_at) == month(func.now()))
        .group_by(Patient.clinic_id)))
    activity = dict(db.execute(select(AuthSession.clinic_id, func.max(AuthSession.last_seen_at))
                               .group_by(AuthSession.clinic_id)).all())
    now = utcnow()
    independent = {c.id for c in clinics if c.kind == ClinicKind.independent.value}
    admins: dict[uuid.UUID, list[AdminOut]] = {}
    for u in db.scalars(select(User).where(User.role.in_([Role.admin.value, Role.professional.value]),
                                           User.archived_at.is_(None)).order_by(User.full_name)):
        if not _is_support_account(u, independent):
            continue
        admins.setdefault(u.clinic_id, []).append(AdminOut(
            id=u.id, full_name=u.full_name, email=u.email, is_active=u.is_active,
            locked=u.locked_until is not None and u.locked_until > now,
            must_change_password=u.must_change_password,
        ))
    return [
        ClinicSummaryOut(
            id=c.id, name=c.name, kind=c.kind, created_at=c.created_at, suspended_at=c.suspended_at,
            purged_at=c.purged_at,
            branches=branches.get(c.id, 0), users=users.get(c.id, 0),
            active_patients=patients.get(c.id, 0), paused_patients=paused.get(c.id, 0),
            paused_with_sessions=paused_seen.get(c.id, 0), last_activity=activity.get(c.id),
            admins=admins.get(c.id, []),
        )
        for c in clinics
    ]


def _is_support_account(user: User, independent_clinics: set[uuid.UUID]) -> bool:
    """Cuentas a las que el dueño da soporte: Administración y, en un espacio independiente,
    el profesional titular (nunca los profesionales de una clínica)."""
    if user.role == Role.admin.value:
        return True
    return user.role == Role.professional.value and user.clinic_id in independent_clinics


def _get_clinic(db: Session, clinic_id: uuid.UUID) -> Clinic:
    clinic = db.get(Clinic, clinic_id)
    if clinic is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="No existe esa clínica.")
    return clinic


@router.get("/clinics", response_model=list[ClinicSummaryOut])
def list_clinics(_: CurrentOwner = Depends(require_ready_owner), db: Session = Depends(get_db)):
    return _summaries(db)


@router.post("/clinics", response_model=ClinicCreatedOut, status_code=status.HTTP_201_CREATED)
def create_clinic(payload: ClinicCreateIn, request: Request,
                  owner: CurrentOwner = Depends(require_ready_owner), db: Session = Depends(get_db)):
    """Crea la clínica con su primera sucursal, las especialidades habituales y su primer
    administrador, con una contraseña temporal que debe cambiar al entrar.

    Si es un espacio de profesional independiente: un solo consultorio, su profesión como
    única especialidad y la cuenta del profesional titular (con ese consultorio asignado)."""
    independent = payload.kind == ClinicKind.independent
    if independent and not payload.profession:
        raise HTTPException(422, detail="Indicá la profesión del profesional independiente.")
    if db.scalar(select(Clinic.id).where(func.lower(Clinic.name) == payload.name.lower(),
                                         Clinic.purged_at.is_(None))):
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Ya existe una clínica con ese nombre.")
    if db.scalar(select(User.id).where(User.email == payload.admin_email)):
        raise HTTPException(status.HTTP_409_CONFLICT,
                            detail="Ese correo ya se usa en otra cuenta de Lumen. Usá otro correo.")
    clinic = Clinic(name=payload.name, timezone="America/Montevideo", kind=payload.kind.value,
                    disabled_features=list(INDEPENDENT_DISABLED_FEATURES) if independent else [])
    db.add(clinic)
    db.flush()
    branch = Branch(clinic_id=clinic.id,
                    name=payload.branch_name or (INDEPENDENT_BRANCH_NAME if independent else "Central"))
    db.add(branch)
    specialty = None
    if independent:
        specialty = Specialty(clinic_id=clinic.id, name=payload.profession, is_active=True)
        db.add(specialty)
    else:
        for name in DEFAULT_SPECIALTIES:
            db.add(Specialty(clinic_id=clinic.id, name=name, is_active=True))
    db.flush()
    temporary = temporary_password()
    admin = User(
        clinic_id=clinic.id, email=payload.admin_email, full_name=payload.admin_full_name,
        document_number=payload.admin_document,
        role=Role.professional.value if independent else Role.admin.value,
        specialty_id=specialty.id if specialty else None,
        password_hash=hash_password(temporary), must_change_password=True,
    )
    db.add(admin)
    db.flush()
    if independent:
        db.add(UserBranch(user_id=admin.id, branch_id=branch.id, clinic_id=clinic.id))
    audit.record(db, clinic_id=clinic.id, actor_id=None, action="system.clinic_create",
                 entity_type="clinic", entity_id=clinic.id,
                 details={"kind": clinic.kind} if independent else None, request=request)
    audit.record(db, clinic_id=clinic.id, actor_id=None, action="system.user_create",
                 entity_type="user", entity_id=admin.id, details={"role": admin.role}, request=request)
    record(db, owner_id=owner.id, action="owner.clinic_create", clinic_id=clinic.id,
           target_user_id=admin.id, details={"kind": clinic.kind} if independent else None,
           request=request)
    db.commit()
    return ClinicCreatedOut(
        clinic=_summaries(db, [clinic.id])[0],
        admin=TemporaryAccessOut(full_name=admin.full_name, email=admin.email, temporary_password=temporary),
    )


@router.post("/clinics/{clinic_id}/suspend", response_model=ClinicSummaryOut)
def suspend_clinic(clinic_id: uuid.UUID, payload: SuspendIn, request: Request,
                   owner: CurrentOwner = Depends(require_ready_owner), db: Session = Depends(get_db)):
    """Nadie de la clínica puede entrar (se cierran las sesiones abiertas). No se borra nada."""
    clinic = _get_clinic(db, clinic_id)
    if clinic.suspended_at is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="La clínica ya está suspendida.")
    now = utcnow()
    clinic.suspended_at = now
    closed = db.execute(update(AuthSession).where(
        AuthSession.clinic_id == clinic.id, AuthSession.revoked_at.is_(None)).values(revoked_at=now)).rowcount
    audit.record(db, clinic_id=clinic.id, actor_id=None, action="system.clinic_suspended",
                 entity_type="clinic", entity_id=clinic.id, request=request)
    record(db, owner_id=owner.id, action="owner.clinic_suspend", clinic_id=clinic.id,
           details={"reason": payload.reason or None, "count": closed}, request=request)
    db.commit()
    return _summaries(db, [clinic.id])[0]


@router.post("/clinics/{clinic_id}/reactivate", response_model=ClinicSummaryOut)
def reactivate_clinic(clinic_id: uuid.UUID, request: Request,
                      owner: CurrentOwner = Depends(require_ready_owner), db: Session = Depends(get_db)):
    clinic = _get_clinic(db, clinic_id)
    if clinic.purged_at is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Los datos de esta clínica se borraron: no se puede reactivar.")
    if clinic.suspended_at is None:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="La clínica no está suspendida.")
    clinic.suspended_at = None
    audit.record(db, clinic_id=clinic.id, actor_id=None, action="system.clinic_reactivated",
                 entity_type="clinic", entity_id=clinic.id, request=request)
    record(db, owner_id=owner.id, action="owner.clinic_reactivate", clinic_id=clinic.id, request=request)
    db.commit()
    return _summaries(db, [clinic.id])[0]


@router.post("/clinics/{clinic_id}/admins/{user_id}/reset-password", response_model=TemporaryAccessOut)
def reset_admin_password(clinic_id: uuid.UUID, user_id: uuid.UUID, request: Request,
                         owner: CurrentOwner = Depends(require_ready_owner), db: Session = Depends(get_db)):
    """Recupera el acceso de un administrador de la clínica: contraseña temporal, sin bloqueo
    por intentos y cuenta activa. Solo cuentas de Administración, o el titular de un espacio
    independiente (nunca los profesionales de una clínica)."""
    clinic = _get_clinic(db, clinic_id)
    target = db.scalar(select(User).where(User.id == user_id, User.clinic_id == clinic.id))
    independent = {clinic.id} if clinic.kind == ClinicKind.independent.value else set()
    if target is None or not _is_support_account(target, independent):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="No existe ese administrador en la clínica.")
    if target.archived_at is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Esa cuenta está eliminada.")
    was_active = target.is_active
    temporary = temporary_password()
    target.password_hash = hash_password(temporary)
    target.must_change_password = True
    target.failed_login_count = 0
    target.locked_until = None
    target.is_active = True
    db.execute(update(AuthSession).where(AuthSession.user_id == target.id, AuthSession.revoked_at.is_(None))
               .values(revoked_at=utcnow()))
    audit.record(db, clinic_id=clinic.id, actor_id=None, action="system.admin_password_reset",
                 entity_type="user", entity_id=target.id, details={"role": target.role}, request=request)
    record(db, owner_id=owner.id, action="owner.admin_password_reset", clinic_id=clinic.id,
           target_user_id=target.id, details={"is_active": True} if not was_active else None,
           request=request)
    db.commit()
    return TemporaryAccessOut(full_name=target.full_name, email=target.email, temporary_password=temporary)


@router.get("/audit", response_model=list[OwnerAuditOut])
def owner_audit(_: CurrentOwner = Depends(require_ready_owner), db: Session = Depends(get_db),
                limit: int = Query(default=200, ge=1, le=500)):
    rows = db.execute(
        select(OwnerAuditEvent, SystemOwner.full_name, Clinic.name, User.full_name)
        .outerjoin(SystemOwner, SystemOwner.id == OwnerAuditEvent.owner_id)
        .outerjoin(Clinic, Clinic.id == OwnerAuditEvent.clinic_id)
        .outerjoin(User, (User.id == OwnerAuditEvent.target_user_id) & (User.clinic_id == OwnerAuditEvent.clinic_id))
        .order_by(OwnerAuditEvent.id.desc()).limit(limit)
    ).all()
    return [
        OwnerAuditOut(id=e.id, created_at=e.created_at, owner_name=owner_name, action=e.action,
                      clinic_name=clinic_name, target_name=target_name, details=e.details, ip=e.ip)
        for e, owner_name, clinic_name, target_name in rows
    ]
