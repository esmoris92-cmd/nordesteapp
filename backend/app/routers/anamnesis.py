"""Anamnesis estructurada (ficha de anamnesis multidisciplinaria).

Una por paciente, que se va completando entre todos los profesionales con acceso clínico:
cada guardado crea una versión nueva (quién y cuándo) y la vigente es la más reciente.
Las versiones nunca se editan ni se borran. Mismos permisos que la historia clínica.

Para no pisar el trabajo de otra persona, al guardar se indica sobre qué versión se editó
(``base_version_id``): si mientras tanto alguien guardó otra, se avisa en vez de reemplazarla.
"""

import re
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import audit
from app.db import get_db
from app.deps import CurrentUser, get_current_user
from app.models import AnamnesisVersion, User
from app.permissions import get_clinical_patient

router = APIRouter(prefix="/api", tags=["anamnesis"])

MAX_FIELDS = 300
MAX_VALUE_CHARS = 5000
_KEY = re.compile(r"^[a-z0-9_]{1,60}$")


class AnamnesisIn(BaseModel):
    data: dict[str, str]
    base_version_id: uuid.UUID | None = None  # versión sobre la que se editó (None = no había)

    @field_validator("data")
    @classmethod
    def _clean(cls, data: dict[str, str]) -> dict[str, str]:
        if len(data) > MAX_FIELDS:
            raise ValueError("La anamnesis tiene demasiados campos.")
        clean: dict[str, str] = {}
        for key, value in data.items():
            if not _KEY.match(key):
                raise ValueError("Hay un campo de la anamnesis que no es válido.")
            value = value.strip()
            if len(value) > MAX_VALUE_CHARS:
                raise ValueError(f"Cada respuesta puede tener hasta {MAX_VALUE_CHARS:,} caracteres.".replace(",", "."))
            if value:  # los campos vacíos no se guardan
                clean[key] = value
        return clean


class AnamnesisVersionOut(BaseModel):
    id: uuid.UUID
    author_id: uuid.UUID
    author_name: str
    created_at: datetime
    data: dict[str, str]


class AnamnesisVersionSummary(BaseModel):
    id: uuid.UUID
    author_name: str
    created_at: datetime
    fields: int  # cuántos campos tenía completos


class AnamnesisOut(BaseModel):
    current: AnamnesisVersionOut | None
    versions: list[AnamnesisVersionSummary]  # de la más nueva a la más vieja


def _versions(db: Session, clinic_id: uuid.UUID, patient_id: uuid.UUID):
    return db.execute(
        select(AnamnesisVersion, User.full_name)
        .join(User, (User.id == AnamnesisVersion.author_id) & (User.clinic_id == AnamnesisVersion.clinic_id))
        .where(AnamnesisVersion.clinic_id == clinic_id, AnamnesisVersion.patient_id == patient_id)
        .order_by(AnamnesisVersion.created_at.desc(), AnamnesisVersion.id.desc())
    ).all()


def _out(version: AnamnesisVersion, author: str) -> AnamnesisVersionOut:
    return AnamnesisVersionOut(id=version.id, author_id=version.author_id, author_name=author,
                               created_at=version.created_at, data=version.data)


def _anamnesis(db: Session, user: CurrentUser, patient_id: uuid.UUID) -> AnamnesisOut:
    rows = _versions(db, user.clinic_id, patient_id)
    return AnamnesisOut(
        current=_out(*rows[0]) if rows else None,
        versions=[AnamnesisVersionSummary(id=v.id, author_name=a, created_at=v.created_at, fields=len(v.data))
                  for v, a in rows],
    )


@router.get("/patients/{patient_id}/anamnesis", response_model=AnamnesisOut)
def get_anamnesis(
    patient_id: uuid.UUID,
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    patient, _ = get_clinical_patient(db, user, patient_id)
    result = _anamnesis(db, user, patient.id)
    audit.record(db, clinic_id=user.clinic_id, actor_id=user.id, action="anamnesis.view",
                 entity_type="patient", entity_id=patient.id, patient_id=patient.id,
                 details={"count": len(result.versions)}, request=request)
    db.commit()
    return result


@router.get("/patients/{patient_id}/anamnesis/{version_id}", response_model=AnamnesisVersionOut)
def get_anamnesis_version(
    patient_id: uuid.UUID,
    version_id: uuid.UUID,
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Una versión anterior (para ver cómo estaba)."""
    patient, _ = get_clinical_patient(db, user, patient_id)
    row = next((r for r in _versions(db, user.clinic_id, patient.id) if r[0].id == version_id), None)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Versión no encontrada.")
    audit.record(db, clinic_id=user.clinic_id, actor_id=user.id, action="anamnesis.view",
                 entity_type="anamnesis_version", entity_id=version_id, patient_id=patient.id,
                 request=request)
    db.commit()
    return _out(*row)


@router.post("/patients/{patient_id}/anamnesis", response_model=AnamnesisVersionOut,
             status_code=status.HTTP_201_CREATED)
def save_anamnesis(
    patient_id: uuid.UUID,
    payload: AnamnesisIn,
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    patient, _ = get_clinical_patient(db, user, patient_id)
    # Una sola a la vez por paciente: dos guardados simultáneos no se pisan.
    db.execute(select(AnamnesisVersion.id).where(
        AnamnesisVersion.clinic_id == user.clinic_id, AnamnesisVersion.patient_id == patient.id,
    ).with_for_update())
    rows = _versions(db, user.clinic_id, patient.id)
    current = rows[0][0] if rows else None
    if (current.id if current else None) != payload.base_version_id:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail=f"{rows[0][1]} guardó cambios en la anamnesis mientras la editabas. Copiá lo que "
                   "agregaste, tocá «Cancelar» para ver la versión nueva y volvé a cargarlo."
            if rows else "La anamnesis cambió mientras la editabas. Volvé a abrirla.",
        )
    if current is not None and current.data == payload.data:
        raise HTTPException(422, detail="No hay cambios para guardar.")
    if current is None and not payload.data:
        raise HTTPException(422, detail="Completá al menos un campo para guardar la anamnesis.")
    version = AnamnesisVersion(clinic_id=user.clinic_id, patient_id=patient.id, author_id=user.id,
                               data=payload.data)
    db.add(version)
    db.flush()
    audit.record(db, clinic_id=user.clinic_id, actor_id=user.id, action="anamnesis.save",
                 entity_type="anamnesis_version", entity_id=version.id, patient_id=patient.id,
                 details={"count": len(payload.data)}, request=request)
    db.commit()
    db.refresh(version)
    return _out(version, db.get(User, user.id).full_name)
