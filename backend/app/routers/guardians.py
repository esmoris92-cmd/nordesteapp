"""Responsables / tutores de un paciente (datos de contacto, no clínicos).

* Ver: quien puede ver la ficha del paciente.
* Crear, editar y quitar: Administración, Recepción y el profesional responsable
  (las mismas personas que pueden editar los datos del paciente).
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app import audit
from app.db import get_db
from app.deps import CurrentUser, get_current_user
from app.models import AccessLevel, Patient, PatientGuardian
from app.permissions import active_access, get_visible_patient
from app.schemas import GuardianIn, GuardianOut, GuardianUpdateIn

router = APIRouter(prefix="/api/patients", tags=["responsables"])


def _editable_patient(db: Session, user: CurrentUser, patient_id: uuid.UUID) -> Patient:
    patient = get_visible_patient(db, user, patient_id)
    if user.is_professional:
        access = active_access(db, user.clinic_id, user.id, patient.id)
        if access is None or access.level != AccessLevel.responsible.value:
            raise HTTPException(status.HTTP_403_FORBIDDEN,
                                detail="Solo el profesional responsable puede editar estos datos.")
    return patient


def _get_guardian(db: Session, user: CurrentUser, patient: Patient, guardian_id: uuid.UUID):
    guardian = db.scalar(select(PatientGuardian).where(
        PatientGuardian.id == guardian_id, PatientGuardian.patient_id == patient.id,
        PatientGuardian.clinic_id == user.clinic_id,
    ))
    if guardian is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Responsable no encontrado.")
    return guardian


def _unset_other_primaries(db: Session, patient: Patient, keep_id: uuid.UUID) -> None:
    db.execute(update(PatientGuardian).where(
        PatientGuardian.patient_id == patient.id, PatientGuardian.clinic_id == patient.clinic_id,
        PatientGuardian.id != keep_id,
    ).values(is_primary=False))


def _full_name(g: PatientGuardian) -> str:
    return " ".join(p for p in (g.first_name, g.middle_name, g.last_name, g.second_last_name) if p)


@router.get("/{patient_id}/guardians", response_model=list[GuardianOut])
def list_guardians(patient_id: uuid.UUID, user: CurrentUser = Depends(get_current_user),
                   db: Session = Depends(get_db)):
    patient = get_visible_patient(db, user, patient_id)
    return db.scalars(
        select(PatientGuardian)
        .where(PatientGuardian.patient_id == patient.id, PatientGuardian.clinic_id == user.clinic_id)
        .order_by(PatientGuardian.is_primary.desc(), PatientGuardian.full_name)
    ).all()


@router.post("/{patient_id}/guardians", response_model=GuardianOut, status_code=status.HTTP_201_CREATED)
def create_guardian(patient_id: uuid.UUID, payload: GuardianIn, request: Request,
                    user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    patient = _editable_patient(db, user, patient_id)
    guardian = PatientGuardian(clinic_id=user.clinic_id, patient_id=patient.id,
                               created_by=user.id, full_name="", **payload.model_dump())
    guardian.full_name = _full_name(guardian)
    db.add(guardian)
    db.flush()
    if guardian.is_primary:
        _unset_other_primaries(db, patient, guardian.id)
    audit.record(db, clinic_id=user.clinic_id, actor_id=user.id, action="guardian.create",
                 entity_type="guardian", entity_id=guardian.id, patient_id=patient.id, request=request)
    db.commit()
    return guardian


@router.patch("/{patient_id}/guardians/{guardian_id}", response_model=GuardianOut)
def update_guardian(patient_id: uuid.UUID, guardian_id: uuid.UUID, payload: GuardianUpdateIn,
                    request: Request, user: CurrentUser = Depends(get_current_user),
                    db: Session = Depends(get_db)):
    patient = _editable_patient(db, user, patient_id)
    guardian = _get_guardian(db, user, patient, guardian_id)
    changes = payload.model_dump(exclude_unset=True)
    for field in ("first_name", "last_name", "relationship", "is_primary"):
        if field in changes and changes[field] is None:
            del changes[field]
    if "document_number" in changes and changes["document_number"] is None:
        raise HTTPException(422, detail="Indicá la C.I. del responsable.")
    # Los responsables cargados antes de exigir la C.I. deben completarla al editarlos.
    if guardian.document_number is None and "document_number" not in changes:
        raise HTTPException(422, detail="Indicá la C.I. del responsable.")
    # Ídem con el primer nombre y el primer apellido por separado.
    if (guardian.first_name is None and "first_name" not in changes) or (
            guardian.last_name is None and "last_name" not in changes):
        raise HTTPException(422, detail="Indicá el primer nombre y el primer apellido del responsable.")
    for field, value in changes.items():
        setattr(guardian, field, value)
    guardian.full_name = _full_name(guardian)
    if changes.get("is_primary"):
        _unset_other_primaries(db, patient, guardian.id)
    audit.record(db, clinic_id=user.clinic_id, actor_id=user.id, action="guardian.update",
                 entity_type="guardian", entity_id=guardian.id, patient_id=patient.id,
                 details={"fields": sorted(changes.keys())}, request=request)
    db.commit()
    return guardian


@router.delete("/{patient_id}/guardians/{guardian_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_guardian(patient_id: uuid.UUID, guardian_id: uuid.UUID, request: Request,
                    user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    patient = _editable_patient(db, user, patient_id)
    guardian = _get_guardian(db, user, patient, guardian_id)
    audit.record(db, clinic_id=user.clinic_id, actor_id=user.id, action="guardian.delete",
                 entity_type="guardian", entity_id=guardian.id, patient_id=patient.id, request=request)
    db.delete(guardian)
    db.commit()
