"""Secciones del informe que se cargan en la ficha del paciente.

* Antecedentes, Diagnóstico y Encuadre: un texto por paciente, que cualquier profesional con
  acceso clínico actualiza.
* Abordaje: uno por profesional (con su "En suma" y sus "Sugerencias"); solo lo edita quien
  lo escribe, y en pantalla se titula por su profesión ("Abordaje de Terapia ocupacional").

Cada guardado es una versión nueva (quién y cuándo); nunca se editan ni se borran. Para no
pisar el trabajo de otra persona, al guardar se indica sobre qué versión se editó
(``base_version_id``). Mismos permisos y auditoría que la historia clínica. "Generar informe"
(pestaña Informes) junta la versión vigente de todas.
"""

import uuid
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import audit
from app.db import get_db
from app.deps import CurrentUser, get_current_user, utcnow
from app.models import (
    Clinic, Notice, NoticeRecipient, Patient, PatientAccess, ReportSectionVersion, Role, Specialty, User,
)
from app.permissions import get_clinical_patient
from app.responsibility import current_responsible

router = APIRouter(prefix="/api", tags=["secciones del informe"])

SectionName = Literal["antecedentes", "diagnostico", "encuadre", "abordaje"]
SHARED = ("antecedentes", "diagnostico", "encuadre")
FIELDS: dict[str, tuple[str, ...]] = {
    "antecedentes": ("texto",),
    "diagnostico": ("texto",),
    "encuadre": ("texto",),
    "abordaje": ("abordaje", "en_suma", "sugerencias"),
}
MAX_CHARS = 20000


class SectionIn(BaseModel):
    data: dict[str, str]
    base_version_id: uuid.UUID | None = None  # versión sobre la que se editó (None = no había)


class VersionOut(BaseModel):
    id: uuid.UUID
    section: str
    owner_id: uuid.UUID | None
    author_name: str
    created_at: datetime
    data: dict[str, str]


class VersionSummary(BaseModel):
    id: uuid.UUID
    author_name: str
    created_at: datetime


class SectionState(BaseModel):
    current: VersionOut | None
    versions: list[VersionSummary]  # de la más nueva a la más vieja


class AbordajeState(SectionState):
    owner_id: uuid.UUID
    owner_name: str
    specialty_name: str | None


class ReportSectionsOut(BaseModel):
    antecedentes: SectionState
    diagnostico: SectionState
    encuadre: SectionState
    abordajes: list[AbordajeState]  # por profesión y nombre


def _rows(db: Session, clinic_id: uuid.UUID, patient_id: uuid.UUID):
    return db.execute(
        select(ReportSectionVersion, User.full_name)
        .join(User, (User.id == ReportSectionVersion.author_id) & (User.clinic_id == ReportSectionVersion.clinic_id))
        .where(ReportSectionVersion.clinic_id == clinic_id, ReportSectionVersion.patient_id == patient_id)
        .order_by(ReportSectionVersion.created_at.desc(), ReportSectionVersion.id.desc())
    ).all()


def _out(v: ReportSectionVersion, author: str) -> VersionOut:
    return VersionOut(id=v.id, section=v.section, owner_id=v.owner_id, author_name=author,
                      created_at=v.created_at, data=v.data)


def _state(rows) -> SectionState:
    return SectionState(
        current=_out(*rows[0]) if rows else None,
        versions=[VersionSummary(id=v.id, author_name=a, created_at=v.created_at) for v, a in rows],
    )


def _sections(db: Session, user: CurrentUser, patient_id: uuid.UUID) -> ReportSectionsOut:
    rows = _rows(db, user.clinic_id, patient_id)
    shared = {name: _state([r for r in rows if r[0].section == name]) for name in SHARED}
    owners = list(dict.fromkeys(r[0].owner_id for r in rows if r[0].section == "abordaje"))
    people = {
        uid: (name, spec)
        for uid, name, spec in db.execute(
            select(User.id, User.full_name, Specialty.name)
            .outerjoin(Specialty, (Specialty.id == User.specialty_id) & (Specialty.clinic_id == User.clinic_id))
            .where(User.clinic_id == user.clinic_id, User.id.in_(owners))
        ).all()
    } if owners else {}
    abordajes = []
    for owner in owners:
        st = _state([r for r in rows if r[0].section == "abordaje" and r[0].owner_id == owner])
        name, spec = people.get(owner, ("", None))
        abordajes.append(AbordajeState(owner_id=owner, owner_name=name, specialty_name=spec, **st.model_dump()))
    abordajes.sort(key=lambda a: ((a.specialty_name or "~").lower(), a.owner_name.lower()))
    return ReportSectionsOut(**shared, abordajes=abordajes)


# ---------- Para cerrar el informe (los usa la pestaña Informes) ----------


def current_version_ids(db: Session, clinic_id: uuid.UUID, patient_id: uuid.UUID) -> set[str]:
    """Versión vigente de cada sección (y de cada abordaje) del paciente."""
    seen: set[tuple[str, uuid.UUID | None]] = set()
    ids: set[str] = set()
    for v in db.scalars(select(ReportSectionVersion).where(
            ReportSectionVersion.clinic_id == clinic_id, ReportSectionVersion.patient_id == patient_id,
    ).order_by(ReportSectionVersion.created_at.desc(), ReportSectionVersion.id.desc())):
        if (v.section, v.owner_id) not in seen:
            seen.add((v.section, v.owner_id))
            ids.add(str(v.id))
    return ids


def participants(db: Session, clinic_id: uuid.UUID, patient_id: uuid.UUID) -> list[tuple[uuid.UUID, str, str | None]]:
    """Profesionales activos con acceso vigente al paciente: (id, nombre, profesión)."""
    return list(db.execute(
        select(User.id, User.full_name, Specialty.name)
        .join(PatientAccess, (PatientAccess.user_id == User.id) & (PatientAccess.clinic_id == User.clinic_id))
        .outerjoin(Specialty, (Specialty.id == User.specialty_id) & (Specialty.clinic_id == User.clinic_id))
        .where(PatientAccess.clinic_id == clinic_id, PatientAccess.patient_id == patient_id,
               PatientAccess.revoked_at.is_(None), User.role == Role.professional.value,
               User.is_active.is_(True), User.archived_at.is_(None))
        .order_by(User.full_name)
    ).all())


def abordaje_owners(db: Session, clinic_id: uuid.UUID, patient_id: uuid.UUID) -> set[uuid.UUID]:
    """Profesionales cuyo abordaje vigente tiene algo escrito."""
    latest: dict[uuid.UUID, dict] = {}
    for v in db.scalars(select(ReportSectionVersion).where(
            ReportSectionVersion.clinic_id == clinic_id, ReportSectionVersion.patient_id == patient_id,
            ReportSectionVersion.section == "abordaje",
    ).order_by(ReportSectionVersion.created_at.desc(), ReportSectionVersion.id.desc())):
        latest.setdefault(v.owner_id, v.data)
    return {owner for owner, data in latest.items() if data}


def _person(name: str, spec: str | None) -> str:
    return f"{name} ({spec})" if spec else name


def _notify_responsible(db: Session, user: CurrentUser, patient: Patient) -> None:
    """Aviso al responsable del paciente cuando otro profesional guarda su abordaje. Reemplaza
    el aviso anterior del mismo profesional sobre el mismo paciente si todavía no lo leyó."""
    resp = current_responsible(db, user.clinic_id, patient.id)
    if resp is None or resp.user_id == user.id:
        return
    if "avisos" in (db.scalar(select(Clinic.disabled_features).where(Clinic.id == user.clinic_id)) or []):
        return
    people = {uid: (name, spec) for uid, name, spec in participants(db, user.clinic_id, patient.id)}
    name, spec = people.get(user.id) or (db.get(User, user.id).full_name, None)
    first = f"{_person(name, spec)} completó su abordaje de {patient.first_name} {patient.last_name}."
    owners = abordaje_owners(db, user.clinic_id, patient.id)
    missing = [_person(n, s) for uid, (n, s) in people.items() if uid not in owners and uid != resp.user_id]
    if resp.user_id in people and resp.user_id not in owners:
        missing.append("el tuyo")
    rest = (" Por favor, generá y finalizá el informe." if not missing else
            f" Todavía falta el abordaje de: {', '.join(missing)}. Cuando estén todos, generá y finalizá el informe.")
    for old in db.scalars(
        select(Notice).join(NoticeRecipient, (NoticeRecipient.notice_id == Notice.id)
                            & (NoticeRecipient.clinic_id == Notice.clinic_id))
        .where(Notice.clinic_id == user.clinic_id, Notice.author_id == user.id,
               NoticeRecipient.user_id == resp.user_id, NoticeRecipient.read_at.is_(None),
               Notice.withdrawn_at.is_(None), Notice.message.startswith(first, autoescape=True))
    ):
        old.withdrawn_at = utcnow()
    notice = Notice(clinic_id=user.clinic_id, author_id=user.id, branch_id=None, to_all=False,
                    message=(first + rest)[:500])
    db.add(notice)
    db.flush()
    db.add(NoticeRecipient(notice_id=notice.id, user_id=resp.user_id, clinic_id=user.clinic_id))
    audit.record(db, clinic_id=user.clinic_id, actor_id=user.id, action="notice.create",
                 entity_type="notice", entity_id=notice.id, patient_id=patient.id, details={"count": 1})


@router.get("/patients/{patient_id}/report-sections", response_model=ReportSectionsOut)
def get_sections(
    patient_id: uuid.UUID,
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    patient, _ = get_clinical_patient(db, user, patient_id)
    result = _sections(db, user, patient.id)
    audit.record(db, clinic_id=user.clinic_id, actor_id=user.id, action="report_section.view",
                 entity_type="patient", entity_id=patient.id, patient_id=patient.id, request=request)
    db.commit()
    return result


@router.get("/patients/{patient_id}/report-sections/versions/{version_id}", response_model=VersionOut)
def get_version(
    patient_id: uuid.UUID,
    version_id: uuid.UUID,
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Una versión anterior (para ver cómo estaba)."""
    patient, _ = get_clinical_patient(db, user, patient_id)
    row = next((r for r in _rows(db, user.clinic_id, patient.id) if r[0].id == version_id), None)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Versión no encontrada.")
    audit.record(db, clinic_id=user.clinic_id, actor_id=user.id, action="report_section.view",
                 entity_type="report_section_version", entity_id=version_id, patient_id=patient.id,
                 details={"kind": row[0].section}, request=request)
    db.commit()
    return _out(*row)


@router.post("/patients/{patient_id}/report-sections/{section}", response_model=VersionOut,
             status_code=status.HTTP_201_CREATED)
def save_section(
    patient_id: uuid.UUID,
    section: SectionName,
    payload: SectionIn,
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    patient, _ = get_clinical_patient(db, user, patient_id)
    allowed = FIELDS[section]
    data: dict[str, str] = {}
    for key, value in payload.data.items():
        if key not in allowed:
            raise HTTPException(422, detail="Hay un campo que no corresponde a esta sección.")
        value = value.strip()
        if len(value) > MAX_CHARS:
            raise HTTPException(422, detail="Cada cuadro puede tener hasta 20.000 caracteres.")
        if value:
            data[key] = value
    # El abordaje es de quien lo escribe; las demás secciones son una por paciente.
    owner_id = user.id if section == "abordaje" else None
    same = (ReportSectionVersion.clinic_id == user.clinic_id, ReportSectionVersion.patient_id == patient.id,
            ReportSectionVersion.section == section,
            ReportSectionVersion.owner_id == owner_id if owner_id else ReportSectionVersion.owner_id.is_(None))
    db.execute(select(ReportSectionVersion.id).where(*same).with_for_update())  # guardados simultáneos
    current = db.execute(
        select(ReportSectionVersion, User.full_name)
        .join(User, (User.id == ReportSectionVersion.author_id) & (User.clinic_id == ReportSectionVersion.clinic_id))
        .where(*same).order_by(ReportSectionVersion.created_at.desc(), ReportSectionVersion.id.desc()).limit(1)
    ).first()
    if (current[0].id if current else None) != payload.base_version_id:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail=f"{current[1]} guardó cambios en esta sección mientras la editabas. Copiá lo que "
                   "agregaste, tocá «Cancelar» para ver la versión nueva y volvé a cargarlo."
            if current else "La sección cambió mientras la editabas. Volvé a abrirla.",
        )
    if current is not None and current[0].data == data:
        raise HTTPException(422, detail="No hay cambios para guardar.")
    if current is None and not data:
        raise HTTPException(422, detail="Escribí algo antes de guardar.")
    version = ReportSectionVersion(clinic_id=user.clinic_id, patient_id=patient.id, section=section,
                                   owner_id=owner_id, author_id=user.id, data=data)
    db.add(version)
    db.flush()
    audit.record(db, clinic_id=user.clinic_id, actor_id=user.id, action="report_section.save",
                 entity_type="report_section_version", entity_id=version.id, patient_id=patient.id,
                 details={"kind": section}, request=request)
    if section == "abordaje" and data:
        _notify_responsible(db, user, patient)
    db.commit()
    db.refresh(version)
    return _out(version, db.get(User, user.id).full_name)
