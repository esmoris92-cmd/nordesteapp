"""Instituciones educativas de un paciente (escuela, liceo, UTU, universidad…).

* Ver la lista (nombre, nivel, teléfono, correo): quien puede ver la ficha del paciente.
* Crear, editar y quitar: Administración, Recepción y el profesional responsable
  (las mismas personas que editan los datos del paciente; ver ``guardians``).
* Los reportes y archivos de cada institución son información clínica: se escriben y se
  leen con las notas (``kind="institution"``) y los archivos del paciente.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import exists, select, update
from sqlalchemy.orm import Session

from app import audit
from app.db import get_db
from app.deps import CurrentUser, get_current_user
from app.models import ClinicalNote, Patient, PatientFile, PatientInstitution
from app.permissions import get_visible_patient
from app.routers.guardians import _editable_patient
from app.schemas import InstitutionIn, InstitutionOut, InstitutionUpdateIn

router = APIRouter(prefix="/api/patients", tags=["instituciones"])

_NOT_FOUND = HTTPException(status.HTTP_404_NOT_FOUND, detail="Institución no encontrada.")


def get_institution(db: Session, clinic_id: uuid.UUID, patient_id: uuid.UUID,
                    institution_id: uuid.UUID) -> PatientInstitution:
    """La institución de ESE paciente (y de esa clínica), o 404."""
    inst = db.scalar(select(PatientInstitution).where(
        PatientInstitution.id == institution_id, PatientInstitution.patient_id == patient_id,
        PatientInstitution.clinic_id == clinic_id,
    ))
    if inst is None:
        raise _NOT_FOUND
    return inst


def _unset_other_current(db: Session, patient: Patient, keep_id: uuid.UUID) -> None:
    db.execute(update(PatientInstitution).where(
        PatientInstitution.patient_id == patient.id, PatientInstitution.clinic_id == patient.clinic_id,
        PatientInstitution.id != keep_id,
    ).values(is_current=False))


@router.get("/{patient_id}/institutions", response_model=list[InstitutionOut])
def list_institutions(patient_id: uuid.UUID, user: CurrentUser = Depends(get_current_user),
                      db: Session = Depends(get_db)):
    patient = get_visible_patient(db, user, patient_id)
    return db.scalars(
        select(PatientInstitution)
        .where(PatientInstitution.patient_id == patient.id, PatientInstitution.clinic_id == user.clinic_id)
        .order_by(PatientInstitution.is_current.desc(), PatientInstitution.created_at.desc())
    ).all()


@router.post("/{patient_id}/institutions", response_model=InstitutionOut,
             status_code=status.HTTP_201_CREATED)
def create_institution(patient_id: uuid.UUID, payload: InstitutionIn, request: Request,
                       user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    patient = _editable_patient(db, user, patient_id)
    data = payload.model_dump()
    data["level"] = payload.level.value
    inst = PatientInstitution(clinic_id=user.clinic_id, patient_id=patient.id, created_by=user.id, **data)
    db.add(inst)
    db.flush()
    if inst.is_current:  # una sola institución actual: la nueva reemplaza a la anterior
        _unset_other_current(db, patient, inst.id)
    audit.record(db, clinic_id=user.clinic_id, actor_id=user.id, action="institution.create",
                 entity_type="institution", entity_id=inst.id, patient_id=patient.id, request=request)
    db.commit()
    return inst


@router.patch("/{patient_id}/institutions/{institution_id}", response_model=InstitutionOut)
def update_institution(patient_id: uuid.UUID, institution_id: uuid.UUID, payload: InstitutionUpdateIn,
                       request: Request, user: CurrentUser = Depends(get_current_user),
                       db: Session = Depends(get_db)):
    patient = _editable_patient(db, user, patient_id)
    inst = get_institution(db, user.clinic_id, patient.id, institution_id)
    changes = payload.model_dump(exclude_unset=True)
    for field in ("name", "level", "is_current"):
        if field in changes and changes[field] is None:
            del changes[field]
    if "level" in changes:
        changes["level"] = changes["level"].value
    for field, value in changes.items():
        setattr(inst, field, value)
    if changes.get("is_current"):
        _unset_other_current(db, patient, inst.id)
    audit.record(db, clinic_id=user.clinic_id, actor_id=user.id, action="institution.update",
                 entity_type="institution", entity_id=inst.id, patient_id=patient.id,
                 details={"fields": sorted(changes.keys())}, request=request)
    db.commit()
    return inst


@router.delete("/{patient_id}/institutions/{institution_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_institution(patient_id: uuid.UUID, institution_id: uuid.UUID, request: Request,
                       user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    patient = _editable_patient(db, user, patient_id)
    inst = get_institution(db, user.clinic_id, patient.id, institution_id)
    # Los reportes y archivos no se borran nunca: una institución con alguno no se puede quitar.
    used = db.scalar(select(
        exists().where(ClinicalNote.institution_id == inst.id, ClinicalNote.clinic_id == user.clinic_id)
        | exists().where(PatientFile.institution_id == inst.id, PatientFile.clinic_id == user.clinic_id)
    ))
    if used:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            detail="Esta institución tiene reportes o archivos, que no se borran. "
                                   "En lugar de quitarla, desmarcala como institución actual.")
    audit.record(db, clinic_id=user.clinic_id, actor_id=user.id, action="institution.delete",
                 entity_type="institution", entity_id=inst.id, patient_id=patient.id, request=request)
    db.delete(inst)
    db.commit()
