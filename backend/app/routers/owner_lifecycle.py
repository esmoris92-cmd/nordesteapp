"""Cambios de fondo en una clínica, desde /sistema (solo el dueño del sistema).

* **Convertir un espacio independiente en clínica**: cuando el profesional suma gente. Se crea la
  primera cuenta de Administración (con contraseña temporal) y el espacio pasa a ser una clínica
  común. Los pacientes, la historia clínica y la cuenta del profesional quedan como estaban (el
  profesional sigue siendo profesional y responsable de sus pacientes). No tiene vuelta atrás
  desde la pantalla.

* **Borrar todos los datos de una clínica** que dejó de usar Lumen (ver ``app/clinic_purge.py``).
  Candados, todos obligatorios:
    1. La clínica está suspendida hace al menos ``PURGE_MIN_DAYS`` días.
    2. Se generó una exportación completa DESPUÉS de suspenderla, o se escribe el motivo de por
       qué no (por ejemplo, la clínica dijo que no quiere sus datos).
    3. Se escribe "BORRAR" y el nombre de la clínica.
    4. Se pone otra vez el código del celular.
  Antes de borrar se hace una copia de seguridad completa. Queda en la auditoría del dueño (la de
  la clínica se borra con sus datos) y hay una constancia para imprimir y entregar.
"""

import math
import uuid
from datetime import datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, StringConstraints
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import audit, totp
from app.clinic_purge import LABELS, PurgeError, delete_files, purge_clinic
from app.db import get_db
from app.deps import utcnow
from app.models import Clinic, ClinicKind, OwnerAuditEvent, Patient, Role, SystemOwner, User
from app.owner_deps import CurrentOwner, record, require_ready_owner
from app.routers.owner_clinics import (
    ClinicCreatedOut, TemporaryAccessOut, _get_clinic, _summaries,
)
from app.schemas import Email, FullName, PersonDocument
from app.security import hash_password, temporary_password

router = APIRouter(prefix="/api/owner", tags=["dueño del sistema"])

PURGE_MIN_DAYS = 30
BACKUPS_KEPT_DAYS = 30  # las copias se renuevan solas: 14 en el servidor y 30 en la Mac de casa

Confirm = Annotated[str, StringConstraints(strip_whitespace=True, max_length=220)]


def _norm(text: str) -> str:
    return " ".join(text.split()).casefold()


def _not_purged(clinic: Clinic) -> None:
    if clinic.purged_at is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Los datos de esta clínica ya se borraron.")


# ---------- Convertir un espacio independiente en clínica ----------


class ConvertIn(BaseModel):
    admin_full_name: FullName
    admin_email: Email
    admin_document: PersonDocument
    enable_features: bool = False  # prender Caja, Avisos, BPS y AYEX (las demás ya estaban)
    confirm_name: Confirm


@router.post("/clinics/{clinic_id}/convert-to-clinic", response_model=ClinicCreatedOut)
def convert_to_clinic(clinic_id: uuid.UUID, payload: ConvertIn, request: Request,
                      owner: CurrentOwner = Depends(require_ready_owner), db: Session = Depends(get_db)):
    clinic = _get_clinic(db, clinic_id)
    _not_purged(clinic)
    if clinic.kind != ClinicKind.independent.value:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Esta ya es una clínica.")
    if _norm(payload.confirm_name) != _norm(clinic.name):
        raise HTTPException(422, detail="Para confirmar, escribí el nombre del consultorio tal como aparece arriba.")
    if db.scalar(select(User.id).where(User.email == payload.admin_email)):
        raise HTTPException(status.HTTP_409_CONFLICT,
                            detail="Ese correo ya se usa en otra cuenta de Lumen (también la del profesional). "
                                   "Usá otro correo para Administración.")
    temporary = temporary_password()
    admin = User(clinic_id=clinic.id, email=payload.admin_email, full_name=payload.admin_full_name,
                 document_number=payload.admin_document, role=Role.admin.value,
                 password_hash=hash_password(temporary), must_change_password=True)
    db.add(admin)
    clinic.kind = ClinicKind.clinic.value
    if payload.enable_features:
        clinic.disabled_features = []
    db.flush()
    audit.record(db, clinic_id=clinic.id, actor_id=None, action="system.clinic_converted", entity_type="clinic",
                 entity_id=clinic.id, details={"kind": clinic.kind}, request=request)
    audit.record(db, clinic_id=clinic.id, actor_id=None, action="system.user_create", entity_type="user",
                 entity_id=admin.id, details={"role": admin.role}, request=request)
    record(db, owner_id=owner.id, action="owner.clinic_convert", clinic_id=clinic.id, target_user_id=admin.id,
           details={"feature": "todas" if payload.enable_features else None}, request=request)
    db.commit()
    return ClinicCreatedOut(
        clinic=_summaries(db, [clinic.id])[0],
        admin=TemporaryAccessOut(full_name=admin.full_name, email=admin.email, temporary_password=temporary),
    )


# ---------- Borrar todos los datos de una clínica ----------


class PurgeStatusOut(BaseModel):
    purged_at: datetime | None
    suspended_at: datetime | None
    min_days: int
    can_purge_from: datetime | None  # desde cuándo se puede (30 días después de suspenderla)
    days_left: int | None
    export_after_suspension: bool
    patients: int
    blockers: list[str]  # qué falta (vacío = se puede borrar)


class PurgeIn(BaseModel):
    confirm_text: Confirm  # "BORRAR <nombre de la clínica>"
    code: Annotated[str, StringConstraints(strip_whitespace=True, max_length=12)]
    reason: Annotated[str, StringConstraints(strip_whitespace=True, max_length=300)] = ""


class CountOut(BaseModel):
    label: str
    count: int


class CertificateOut(BaseModel):
    clinic_name: str
    independent: bool
    purged_at: datetime
    purged_by: str | None
    reason: str | None
    counts: list[CountOut]
    files_deleted: int
    backup_name: str | None
    backups_gone_by: datetime  # para entonces ya no queda ninguna copia con estos datos


def _export_after_suspension(db: Session, clinic: Clinic) -> bool:
    if clinic.suspended_at is None:
        return False
    return db.scalar(select(func.count()).select_from(OwnerAuditEvent).where(
        OwnerAuditEvent.clinic_id == clinic.id, OwnerAuditEvent.action == "owner.clinic_export",
        OwnerAuditEvent.created_at >= clinic.suspended_at)) > 0


def _status(db: Session, clinic: Clinic) -> PurgeStatusOut:
    now = utcnow()
    since = clinic.suspended_at + timedelta(days=PURGE_MIN_DAYS) if clinic.suspended_at else None
    blockers = []
    if clinic.purged_at is not None:
        blockers.append("Los datos de esta clínica ya se borraron.")
    elif clinic.suspended_at is None:
        blockers.append("Primero suspendé la clínica (pestaña Acceso).")
    elif since and since > now:
        blockers.append(f"Tiene que estar suspendida al menos {PURGE_MIN_DAYS} días.")
    days_left = None
    if since is not None:
        days_left = max(math.ceil((since - now).total_seconds() / 86400), 0)
    return PurgeStatusOut(
        purged_at=clinic.purged_at, suspended_at=clinic.suspended_at, min_days=PURGE_MIN_DAYS,
        can_purge_from=since, days_left=days_left,
        export_after_suspension=_export_after_suspension(db, clinic),
        patients=db.scalar(select(func.count()).select_from(Patient).where(Patient.clinic_id == clinic.id)) or 0,
        blockers=blockers,
    )


@router.get("/clinics/{clinic_id}/purge-status", response_model=PurgeStatusOut)
def purge_status(clinic_id: uuid.UUID, _: CurrentOwner = Depends(require_ready_owner),
                 db: Session = Depends(get_db)):
    return _status(db, _get_clinic(db, clinic_id))


@router.post("/clinics/{clinic_id}/purge", response_model=CertificateOut)
def purge(clinic_id: uuid.UUID, payload: PurgeIn, request: Request,
          owner: CurrentOwner = Depends(require_ready_owner), db: Session = Depends(get_db)):
    clinic = _get_clinic(db, clinic_id)
    state = _status(db, clinic)
    if state.blockers:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=" ".join(state.blockers))
    if not state.export_after_suspension and len(payload.reason) < 3:
        raise HTTPException(422, detail="No hay una exportación generada después de suspenderla: escribí el "
                                        "motivo por el que se borra sin entregar los datos.")
    if _norm(payload.confirm_text) != _norm(f"BORRAR {clinic.name}"):
        raise HTTPException(422, detail=f"Para confirmar, escribí exactamente: BORRAR {clinic.name}")
    me = db.get(SystemOwner, owner.id)
    step = totp.verify(me.totp_secret, payload.code, me.totp_last_step) if me.totp_enabled else None
    if step is None:
        raise HTTPException(422, detail="El código del celular no es correcto (o ya se usó). Esperá el próximo.")
    me.totp_last_step = step
    db.commit()  # el código queda usado aunque después algo falle
    try:
        result = purge_clinic(db, clinic)
        record(db, owner_id=owner.id, action="owner.clinic_purge", clinic_id=clinic.id, details={
            "reason": payload.reason or None, "patients": result.counts.get("patients", 0),
            "files": len(result.pending_keys), "counts": result.counts, "backup": result.backup_name,
        }, request=request)
        db.commit()
    except PurgeError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc))
    delete_files(result)
    return _certificate(db, clinic)


def _certificate(db: Session, clinic: Clinic) -> CertificateOut:
    event = db.scalar(select(OwnerAuditEvent).where(
        OwnerAuditEvent.clinic_id == clinic.id, OwnerAuditEvent.action == "owner.clinic_purge")
        .order_by(OwnerAuditEvent.id.desc()).limit(1))
    if clinic.purged_at is None or event is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Los datos de esta clínica no se borraron.")
    who = db.get(SystemOwner, event.owner_id) if event.owner_id else None
    counts = event.details.get("counts") or {}
    return CertificateOut(
        clinic_name=clinic.name, independent=clinic.kind == ClinicKind.independent.value,
        purged_at=clinic.purged_at, purged_by=who.full_name if who else None,
        reason=event.details.get("reason"),
        counts=[CountOut(label=LABELS.get(k, k), count=int(v)) for k, v in counts.items()],
        files_deleted=int(event.details.get("files") or 0), backup_name=event.details.get("backup"),
        backups_gone_by=clinic.purged_at + timedelta(days=BACKUPS_KEPT_DAYS + 1),
    )


@router.get("/clinics/{clinic_id}/purge-certificate", response_model=CertificateOut)
def purge_certificate(clinic_id: uuid.UUID, _: CurrentOwner = Depends(require_ready_owner),
                      db: Session = Depends(get_db)):
    return _certificate(db, _get_clinic(db, clinic_id))
