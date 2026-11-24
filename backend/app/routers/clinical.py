"""Historia clínica (notas) e informes profesionales.

Solo profesionales con acceso activo al paciente pueden leer o escribir.
Excepción: Recepción puede LEER los informes FINALIZADOS de los pacientes de su
clínica (no los borradores ni la historia clínica). Cada lectura queda auditada.
Las notas nunca se editan ni se borran: una corrección crea una nota nueva
que reemplaza a la anterior, guarda el motivo y deja ambas visibles.
"""

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session, aliased

from app import audit
from app.clinic_time import check_not_future
from app.db import get_db
from app.deps import CurrentUser, get_current_user, utcnow
from app.models import ClinicalNote, NoteKind, Report, ReportStatus, Role, Specialty, User
from app.permissions import CLINICAL_FORBIDDEN, get_clinical_patient, get_visible_patient
from app.responsibility import current_responsible
from app.routers.report_sections import abordaje_owners, current_version_ids, participants
from app.schemas import (
    ReportParticipationIn,
    ReportPersonOut,
    ReportReadinessOut,
    NoteCorrectIn,
    NoteCreateIn,
    NoteOut,
    ReportCreateIn,
    ReportOut,
    ReportSummaryOut,
    ReportUpdateIn,
)

router = APIRouter(prefix="/api", tags=["historia clínica e informes"])


# ---------- Notas ----------


def _notes(db: Session, user: CurrentUser, patient_id: uuid.UUID, note_id: uuid.UUID | None = None):
    successor = aliased(ClinicalNote)
    query = (
        select(ClinicalNote, User.full_name, successor.id)
        .join(User, (User.id == ClinicalNote.author_id) & (User.clinic_id == ClinicalNote.clinic_id))
        .outerjoin(successor, successor.supersedes_id == ClinicalNote.id)
        .where(ClinicalNote.clinic_id == user.clinic_id, ClinicalNote.patient_id == patient_id)
        .order_by(ClinicalNote.created_at.desc())
    )
    if note_id:
        query = query.where(ClinicalNote.id == note_id)
    return [
        NoteOut(
            id=n.id, patient_id=n.patient_id, author_id=n.author_id, author_name=author,
            kind=n.kind, session_date=n.session_date, content=n.content,
            supersedes_id=n.supersedes_id, correction_reason=n.correction_reason,
            superseded_by_id=succ_id, created_at=n.created_at, institution_id=n.institution_id,
        )
        for n, author, succ_id in db.execute(query).all()
    ]


@router.get("/patients/{patient_id}/notes", response_model=list[NoteOut])
def list_notes(
    patient_id: uuid.UUID,
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    patient, _ = get_clinical_patient(db, user, patient_id)
    result = _notes(db, user, patient.id)
    audit.record(db, clinic_id=user.clinic_id, actor_id=user.id, action="clinical_record.view",
                 entity_type="patient", entity_id=patient.id, patient_id=patient.id,
                 details={"count": len(result)}, request=request)
    db.commit()
    return result


@router.post("/patients/{patient_id}/notes", response_model=NoteOut,
             status_code=status.HTTP_201_CREATED)
def create_note(
    patient_id: uuid.UUID,
    payload: NoteCreateIn,
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    patient, _ = get_clinical_patient(db, user, patient_id)
    check_not_future(db, user.clinic_id, payload.session_date)
    # Los reportes de institución van atados a una institución de ESTE paciente; el resto, a ninguna.
    if payload.kind == NoteKind.institution:
        if payload.institution_id is None:
            raise HTTPException(422, detail="Indicá a qué institución corresponde el reporte.")
        from app.routers.institutions import get_institution  # evita una importación circular
        get_institution(db, user.clinic_id, patient.id, payload.institution_id)
    elif payload.institution_id is not None:
        raise HTTPException(422, detail="Solo los reportes de institución llevan una institución.")
    note = ClinicalNote(
        clinic_id=user.clinic_id, patient_id=patient.id, author_id=user.id,
        kind=payload.kind.value, session_date=payload.session_date, content=payload.content,
        institution_id=payload.institution_id,
    )
    db.add(note)
    db.flush()
    audit.record(db, clinic_id=user.clinic_id, actor_id=user.id, action="clinical_note.create",
                 entity_type="clinical_note", entity_id=note.id, patient_id=patient.id,
                 details={"kind": payload.kind.value}, request=request)
    db.commit()
    return _notes(db, user, patient.id, note.id)[0]


@router.post("/notes/{note_id}/corrections", response_model=NoteOut,
             status_code=status.HTTP_201_CREATED)
def correct_note(
    note_id: uuid.UUID,
    payload: NoteCorrectIn,
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not user.is_professional:
        raise CLINICAL_FORBIDDEN
    original = db.scalar(
        select(ClinicalNote).where(ClinicalNote.id == note_id,
                                   ClinicalNote.clinic_id == user.clinic_id)
    )
    if original is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Nota no encontrada.")
    # Debe seguir teniendo acceso al paciente (si no, 404 sin revelar nada).
    try:
        get_clinical_patient(db, user, original.patient_id)
    except HTTPException:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Nota no encontrada.") from None
    if original.author_id != user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            detail="Solo quien escribió la nota puede corregirla.")
    if db.scalar(select(ClinicalNote.id).where(ClinicalNote.supersedes_id == original.id)):
        raise HTTPException(status.HTTP_409_CONFLICT,
                            detail="Esta nota ya fue corregida. Corregí la versión más reciente.")
    # La fecha se puede corregir (si no se manda, queda la de la versión anterior).
    session_date = (payload.session_date if "session_date" in payload.model_fields_set
                    else original.session_date)
    check_not_future(db, user.clinic_id, session_date)
    if payload.content.strip() == original.content.strip() and session_date == original.session_date:
        raise HTTPException(422, detail="La corrección no cambia nada: el texto y la fecha son iguales "
                                        "a la versión actual.")
    correction = ClinicalNote(
        clinic_id=user.clinic_id, patient_id=original.patient_id, author_id=user.id,
        kind=original.kind, session_date=session_date, content=payload.content,
        supersedes_id=original.id, correction_reason=payload.reason,
        institution_id=original.institution_id,
    )
    db.add(correction)
    db.flush()
    audit.record(db, clinic_id=user.clinic_id, actor_id=user.id, action="clinical_note.correct",
                 entity_type="clinical_note", entity_id=correction.id,
                 patient_id=original.patient_id,
                 details={"supersedes_id": str(original.id)}, request=request)
    db.commit()
    return _notes(db, user, original.patient_id, correction.id)[0]


# ---------- Informes ----------


def _report_query(user: CurrentUser):
    return (
        select(Report, User.full_name)
        .join(User, (User.id == Report.author_id) & (User.clinic_id == Report.clinic_id))
        .where(Report.clinic_id == user.clinic_id)
    )


def _report_out(report: Report, author: str, with_content: bool):
    data: dict[str, Any] = dict(
        id=report.id, patient_id=report.patient_id, author_id=report.author_id, author_name=author,
        title=report.title, status=report.status, created_at=report.created_at,
        updated_at=report.updated_at, finalized_at=report.finalized_at,
        generated=report.section_version_ids is not None,
    )
    if not with_content:
        return ReportSummaryOut(**data)
    return ReportOut(**data, content=report.content, signers=report.signers or [])


def _signers(db: Session, user: CurrentUser, signer_ids: list[uuid.UUID]) -> list[dict] | None:
    """Firmantes del informe: los profesionales indicados (de esta clínica) y el autor al final si
    no está entre ellos. Se guarda nombre y profesión tal como son hoy."""
    if not signer_ids:
        return None
    ids = list(dict.fromkeys([*signer_ids, user.id]))
    rows = {
        uid: (name, spec)
        for uid, name, spec in db.execute(
            select(User.id, User.full_name, Specialty.name)
            .outerjoin(Specialty, (Specialty.id == User.specialty_id) & (Specialty.clinic_id == User.clinic_id))
            .where(User.clinic_id == user.clinic_id, User.id.in_(ids),
                   User.role == Role.professional.value)
        ).all()
    }
    if any(uid not in rows for uid in ids):
        raise HTTPException(422, detail="Alguno de los profesionales que firman no es válido.")
    return [{"user_id": str(uid), "name": rows[uid][0], "specialty": rows[uid][1]} for uid in ids]


_REPORT_NOT_FOUND = HTTPException(status.HTTP_404_NOT_FOUND, detail="Informe no encontrado.")
ONLY_RESPONSIBLE = HTTPException(
    status.HTTP_403_FORBIDDEN,
    detail="Solo el profesional responsable del paciente puede generar y finalizar el informe conjunto.")


def _is_responsible(db: Session, user: CurrentUser, patient_id: uuid.UUID) -> bool:
    resp = current_responsible(db, user.clinic_id, patient_id)
    return resp is not None and resp.user_id == user.id


def _check_versions(db: Session, user: CurrentUser, patient_id: uuid.UUID, ids: list[uuid.UUID]) -> list[str]:
    """El informe se arma con lo vigente: si algo cambió mientras se generaba, hay que regenerarlo."""
    given = {str(i) for i in ids}
    if given != current_version_ids(db, user.clinic_id, patient_id):
        raise HTTPException(status.HTTP_409_CONFLICT,
                            detail="Alguien guardó cambios en las secciones mientras se armaba el informe. "
                                   "Volvé a intentarlo.")
    return sorted(given)


def _readiness(db: Session, user: CurrentUser, report: Report) -> ReportReadinessOut:
    """Para finalizar un informe generado: nada cambió desde que se armó y todos los profesionales
    con acceso escribieron su abordaje (salvo los marcados como "no participa")."""
    people = participants(db, user.clinic_id, report.patient_id)
    owners = abordaje_owners(db, user.clinic_id, report.patient_id)
    excluded = set(report.excluded_ids or [])
    resp = current_responsible(db, user.clinic_id, report.patient_id)
    resp_name = db.scalar(select(User.full_name).where(User.id == resp.user_id)) if resp else None
    return ReportReadinessOut(
        stale=set(report.section_version_ids or []) != current_version_ids(db, user.clinic_id, report.patient_id),
        missing=[ReportPersonOut(user_id=uid, name=n, specialty=s) for uid, n, s in people
                 if uid not in owners and str(uid) not in excluded],
        excluded=[ReportPersonOut(user_id=uid, name=n, specialty=s) for uid, n, s in people
                  if uid not in owners and str(uid) in excluded],
        can_close=report.author_id == user.id and resp is not None and resp.user_id == user.id,
        responsible_name=resp_name,
    )


def _reports_patient_for_reading(db: Session, user: CurrentUser, patient_id: uuid.UUID):
    """Paciente cuyos informes puede LEER el usuario, y si solo ve los finalizados.

    * Profesional con acceso al paciente: todos los informes (borradores y finalizados).
    * Recepción: solo los informes finalizados, en modo lectura, de los pacientes que ve.
    * Administración: solo los informes finalizados, en modo lectura, de los pacientes de su
      clínica (todas las sucursales).
    """
    if user.is_reception or user.is_admin:
        return get_visible_patient(db, user, patient_id), True
    patient, _ = get_clinical_patient(db, user, patient_id)
    return patient, False


def _get_report_for_reading(db: Session, user: CurrentUser, report_id: uuid.UUID) -> tuple[Report, str]:
    if not (user.is_professional or user.is_reception or user.is_admin):
        raise CLINICAL_FORBIDDEN
    row = db.execute(_report_query(user).where(Report.id == report_id)).first()
    if row is None:
        raise _REPORT_NOT_FOUND
    try:
        _, only_final = _reports_patient_for_reading(db, user, row[0].patient_id)
    except HTTPException:
        raise _REPORT_NOT_FOUND from None
    if only_final and row[0].status != ReportStatus.final.value:
        raise _REPORT_NOT_FOUND  # recepción y administración no ven borradores
    return row[0], row[1]


def _get_report(db: Session, user: CurrentUser, report_id: uuid.UUID) -> tuple[Report, str]:
    """Informe que el usuario puede MODIFICAR (solo profesionales con acceso)."""
    if not user.is_professional:
        raise CLINICAL_FORBIDDEN
    row = db.execute(_report_query(user).where(Report.id == report_id)).first()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Informe no encontrado.")
    try:
        get_clinical_patient(db, user, row[0].patient_id)
    except HTTPException:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Informe no encontrado.") from None
    return row[0], row[1]


@router.get("/patients/{patient_id}/reports", response_model=list[ReportSummaryOut])
def list_reports(
    patient_id: uuid.UUID,
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    patient, only_final = _reports_patient_for_reading(db, user, patient_id)
    query = _report_query(user).where(Report.patient_id == patient.id)
    if only_final:
        query = query.where(Report.status == ReportStatus.final.value)
    rows = db.execute(query.order_by(Report.created_at.desc())).all()
    audit.record(db, clinic_id=user.clinic_id, actor_id=user.id, action="report.list",
                 entity_type="patient", entity_id=patient.id, patient_id=patient.id,
                 details={"count": len(rows)}, request=request)
    db.commit()
    return [_report_out(r, a, with_content=False) for r, a in rows]


@router.post("/patients/{patient_id}/reports", response_model=ReportOut,
             status_code=status.HTTP_201_CREATED)
def create_report(
    patient_id: uuid.UUID,
    payload: ReportCreateIn,
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    patient, _ = get_clinical_patient(db, user, patient_id)
    version_ids = None
    if payload.section_version_ids is not None:  # "Generar informe"
        if not _is_responsible(db, user, patient.id):
            raise ONLY_RESPONSIBLE
        version_ids = _check_versions(db, user, patient.id, payload.section_version_ids)
    report = Report(
        clinic_id=user.clinic_id, patient_id=patient.id, author_id=user.id,
        title=payload.title, content=payload.content, status=ReportStatus.draft.value,
        signers=_signers(db, user, payload.signer_ids), section_version_ids=version_ids,
    )
    db.add(report)
    db.flush()
    audit.record(db, clinic_id=user.clinic_id, actor_id=user.id, action="report.create",
                 entity_type="report", entity_id=report.id, patient_id=patient.id, request=request)
    db.commit()
    db.refresh(report)
    return _report_out(report, user.full_name, with_content=True)


@router.get("/reports/{report_id}", response_model=ReportOut)
def get_report(
    report_id: uuid.UUID,
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    report, author = _get_report_for_reading(db, user, report_id)
    audit.record(db, clinic_id=user.clinic_id, actor_id=user.id, action="report.view",
                 entity_type="report", entity_id=report.id, patient_id=report.patient_id,
                 request=request)
    db.commit()
    return _report_out(report, author, with_content=True)


@router.patch("/reports/{report_id}", response_model=ReportOut)
def update_report(
    report_id: uuid.UUID,
    payload: ReportUpdateIn,
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    report, author = _get_report(db, user, report_id)
    if report.author_id != user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Solo el autor puede editar el informe.")
    if report.status != ReportStatus.draft.value:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            detail="El informe ya está finalizado y no puede modificarse.")
    changes = payload.model_dump(exclude_unset=True, exclude_none=True,
                                 include={"title", "content"})
    for field, value in changes.items():
        setattr(report, field, value)
    if payload.section_version_ids is not None:  # "Actualizar con lo último"
        if report.section_version_ids is None:
            raise HTTPException(422, detail="Este informe no se generó desde las secciones.")
        if not _is_responsible(db, user, report.patient_id):
            raise ONLY_RESPONSIBLE
        report.section_version_ids = _check_versions(db, user, report.patient_id, payload.section_version_ids)
        report.signers = _signers(db, user, payload.signer_ids or [])
        changes["sections"] = True
    audit.record(db, clinic_id=user.clinic_id, actor_id=user.id, action="report.update",
                 entity_type="report", entity_id=report.id, patient_id=report.patient_id,
                 details={"fields": sorted(changes.keys())}, request=request)
    db.commit()
    db.refresh(report)
    return _report_out(report, author, with_content=True)


@router.post("/reports/{report_id}/finalize", response_model=ReportOut)
def finalize_report(
    report_id: uuid.UUID,
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    report, author = _get_report(db, user, report_id)
    if report.author_id != user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Solo el autor puede finalizar el informe.")
    if report.status != ReportStatus.draft.value:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="El informe ya estaba finalizado.")
    if report.section_version_ids is not None:  # informe generado: reglas de cierre
        ready = _readiness(db, user, report)
        if not ready.can_close:
            raise ONLY_RESPONSIBLE
        if ready.stale:
            raise HTTPException(status.HTTP_409_CONFLICT,
                                detail="Hubo cambios en las secciones después de generar el borrador. "
                                       "Tocá «Actualizar con lo último» antes de finalizar.")
        if ready.missing:
            who = ", ".join(f"{p.name} ({p.specialty})" if p.specialty else p.name for p in ready.missing)
            raise HTTPException(status.HTTP_409_CONFLICT,
                                detail=f"Falta el abordaje de: {who}. Si no participa en este informe, "
                                       "marcalo como «No participa».")
    report.status = ReportStatus.final.value
    report.finalized_at = utcnow()
    audit.record(db, clinic_id=user.clinic_id, actor_id=user.id, action="report.finalize",
                 entity_type="report", entity_id=report.id, patient_id=report.patient_id,
                 request=request)
    db.commit()
    db.refresh(report)
    return _report_out(report, author, with_content=True)


@router.get("/reports/{report_id}/readiness", response_model=ReportReadinessOut)
def report_readiness(
    report_id: uuid.UUID,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Qué falta para finalizar un informe generado (borrador)."""
    report, _ = _get_report(db, user, report_id)
    if report.section_version_ids is None:
        raise HTTPException(422, detail="Este informe no se generó desde las secciones.")
    return _readiness(db, user, report)


@router.post("/reports/{report_id}/participation", response_model=ReportReadinessOut)
def set_participation(
    report_id: uuid.UUID,
    payload: ReportParticipationIn,
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """El responsable marca a un profesional con acceso como "no participa en este informe"
    (o lo vuelve a incluir). Queda en la auditoría."""
    report, _ = _get_report(db, user, report_id)
    if report.section_version_ids is None:
        raise HTTPException(422, detail="Este informe no se generó desde las secciones.")
    if report.status != ReportStatus.draft.value:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="El informe ya está finalizado.")
    if not _readiness(db, user, report).can_close:
        raise ONLY_RESPONSIBLE
    if payload.user_id not in {uid for uid, _, _ in participants(db, user.clinic_id, report.patient_id)}:
        raise HTTPException(422, detail="Ese profesional no tiene acceso a este paciente.")
    excluded = set(report.excluded_ids or [])
    if payload.participates:
        excluded.discard(str(payload.user_id))
    else:
        excluded.add(str(payload.user_id))
    report.excluded_ids = sorted(excluded)
    audit.record(db, clinic_id=user.clinic_id, actor_id=user.id, action="report.participation",
                 entity_type="report", entity_id=report.id, patient_id=report.patient_id,
                 details={"target_user_id": str(payload.user_id),
                          "status": "included" if payload.participates else "excluded"},
                 request=request)
    db.commit()
    return _readiness(db, user, report)

