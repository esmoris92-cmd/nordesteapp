"""Cambio del profesional responsable de un paciente.

Se usa en dos lugares: el botón "Cambiar responsable" de la ficha y la reasignación
obligatoria al eliminar (archivar) la cuenta de un profesional.

Nada se borra: el acceso del responsable anterior se revoca con el motivo, y queda en
el historial de accesos junto al nuevo.
"""

import uuid

from fastapi import HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import audit
from app.deps import CurrentUser, utcnow
from app.models import AccessLevel, PatientAccess, User
from app.permissions import active_access

PROMOTED_REASON = "Pasa a ser el profesional responsable"


def current_responsible(db: Session, clinic_id: uuid.UUID, patient_id: uuid.UUID) -> PatientAccess | None:
    return db.scalar(select(PatientAccess).where(
        PatientAccess.clinic_id == clinic_id, PatientAccess.patient_id == patient_id,
        PatientAccess.level == AccessLevel.responsible.value, PatientAccess.revoked_at.is_(None),
    ))


def responsible_accesses_of(db: Session, clinic_id: uuid.UUID, user_id: uuid.UUID) -> list[PatientAccess]:
    """Accesos vigentes en los que esta persona es la responsable."""
    return list(db.scalars(select(PatientAccess).where(
        PatientAccess.clinic_id == clinic_id, PatientAccess.user_id == user_id,
        PatientAccess.level == AccessLevel.responsible.value, PatientAccess.revoked_at.is_(None),
    )).all())


def _revoke(access: PatientAccess, actor: CurrentUser, reason: str) -> None:
    access.revoked_at = utcnow()
    access.revoked_by = actor.id
    access.revoke_reason = reason


def assign_responsible(
    db: Session, actor: CurrentUser, patient_id: uuid.UUID, new_prof: User, reason: str,
    request: Request | None,
) -> PatientAccess:
    """Deja a ``new_prof`` como responsable del paciente, en una sola operación.

    * Revoca el acceso del responsable anterior (si había) con el mismo motivo.
    * Si el nuevo ya era colaborador, ese acceso se cierra: pasa a ser responsable.
    No hace commit: quien llama decide cuándo confirmar.
    """
    previous = current_responsible(db, actor.clinic_id, patient_id)
    if previous is not None and previous.user_id == new_prof.id:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            detail="Ese profesional ya es el responsable del paciente.")
    if previous is not None:
        _revoke(previous, actor, reason)
    collaborator = active_access(db, actor.clinic_id, new_prof.id, patient_id)
    if collaborator is not None:
        _revoke(collaborator, actor, PROMOTED_REASON)
    db.flush()  # los índices únicos exigen cerrar los accesos antes de crear el nuevo
    access = PatientAccess(
        clinic_id=actor.clinic_id, patient_id=patient_id, user_id=new_prof.id,
        level=AccessLevel.responsible.value, reason=reason, granted_by=actor.id,
    )
    db.add(access)
    db.flush()
    details = {"target_user_id": str(new_prof.id), "reason_given": True}
    if previous is not None:
        details["professional_id"] = str(previous.user_id)  # responsable anterior
    else:
        details["level"] = AccessLevel.responsible.value
    # Sin responsable previo es una asignación; si había uno, un cambio.
    audit.record(db, clinic_id=actor.clinic_id, actor_id=actor.id,
                 action="access.transfer" if previous is not None else "access.grant",
                 entity_type="patient_access", entity_id=access.id, patient_id=patient_id,
                 details=details, request=request)
    return access
