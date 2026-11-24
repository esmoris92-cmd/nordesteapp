"""Pacientes y autorizaciones de acceso (incluido el acceso compartido)."""

import uuid
from datetime import date, datetime, time, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, aliased

from app import audit
from app.ayex_alert import ayex_alert_before
from app.clinic_time import clinic_today
from app.db import get_db
from app.deps import CurrentUser, get_current_user, require_staff_or_titular, utcnow
from app.models import (
    AccessLevel, AffiliationType, Appointment, AppointmentStatus, Clinic, Patient, PatientAccess,
    PatientStatus, Sex, User,
)
from app.permissions import (
    active_access,
    get_clinic_professional,
    get_visible_patient,
    visible_patients,
)
from app.schemas import (
    PatientAddress,
    AccessGrantIn,
    AccessOut,
    AccessRevokeIn,
    PatientCreateIn,
    PatientDetailOut,
    PatientListItem,
    PatientOut,
    PatientUpdateIn,
    ResponsibleChangeIn,
)
from app import appointment_moves
from app.branches import branch_names, resolve_branch
from app.responsibility import assign_responsible, current_responsible

router = APIRouter(prefix="/api/patients", tags=["pacientes"])


def _responsibles(db: Session, clinic_id: uuid.UUID,
                  patient_ids: list[uuid.UUID]) -> dict[uuid.UUID, tuple[uuid.UUID, str]]:
    """Responsable vigente de cada paciente: (id del profesional, nombre para mostrar)."""
    if not patient_ids:
        return {}
    rows = db.execute(
        select(PatientAccess.patient_id, User.id, User.full_name, User.archived_at, User.is_active)
        .join(User, (User.id == PatientAccess.user_id) & (User.clinic_id == PatientAccess.clinic_id))
        .where(
            PatientAccess.clinic_id == clinic_id,
            PatientAccess.patient_id.in_(patient_ids),
            PatientAccess.level == AccessLevel.responsible.value,
            PatientAccess.revoked_at.is_(None),
        )
    ).all()
    # Si la cuenta del responsable ya no está en uso, se avisa junto al nombre.
    return {
        pid: (uid, name + (" (cuenta eliminada)" if archived_at else "" if is_active
                           else " (cuenta desactivada)"))
        for pid, uid, name, archived_at, is_active in rows
    }


def _no_shows_this_month(db: Session, clinic_id: uuid.UUID,
                         patient_ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
    """Inasistencias (turnos marcados "ausente") de cada paciente en el mes en curso, según la
    hora de la clínica. Se cuentan las de todos los profesionales y sucursales; el 1.º de cada
    mes vuelven a cero (no se guarda nada aparte: se calcula con los turnos del mes)."""
    if not patient_ids:
        return {}
    tz = ZoneInfo(db.get(Clinic, clinic_id).timezone)
    today = datetime.now(tz).date()
    month_start = datetime.combine(today.replace(day=1), time(0), tzinfo=tz)
    next_month = datetime.combine((today.replace(day=28) + timedelta(days=4)).replace(day=1), time(0), tzinfo=tz)
    rows = db.execute(
        select(Appointment.patient_id, func.count())
        .where(
            Appointment.clinic_id == clinic_id,
            Appointment.patient_id.in_(patient_ids),
            Appointment.status == AppointmentStatus.no_show.value,
            Appointment.starts_at >= month_start, Appointment.starts_at < next_month,
        )
        .group_by(Appointment.patient_id)
    ).all()
    return dict(rows)


def _collaborator_names(db: Session, clinic_id: uuid.UUID,
                        patient_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[str]]:
    """Colaboradores vigentes de cada paciente (cuentas en uso), por nombre."""
    result: dict[uuid.UUID, list[str]] = {}
    if not patient_ids:
        return result
    rows = db.execute(
        select(PatientAccess.patient_id, User.full_name)
        .join(User, (User.id == PatientAccess.user_id) & (User.clinic_id == PatientAccess.clinic_id))
        .where(
            PatientAccess.clinic_id == clinic_id,
            PatientAccess.patient_id.in_(patient_ids),
            PatientAccess.level == AccessLevel.collaborator.value,
            PatientAccess.revoked_at.is_(None),
            User.is_active.is_(True), User.archived_at.is_(None),
        )
        .order_by(User.full_name)
    ).all()
    for pid, name in rows:
        result.setdefault(pid, []).append(name)
    return result


def _responsible_names(db: Session, clinic_id: uuid.UUID, patient_ids: list[uuid.UUID]) -> dict:
    return {pid: name for pid, (_, name) in _responsibles(db, clinic_id, patient_ids).items()}


_AYEX_DATE_REQUIRED = HTTPException(422, detail="Indicá la fecha de vencimiento del AYEX.")

_DUPLICATE_DOCUMENT = HTTPException(
    status.HTTP_409_CONFLICT, detail="Ya existe un paciente con ese documento en la clínica."
)


def _check_document_free(db: Session, clinic_id: uuid.UUID, document: str | None,
                         exclude_id: uuid.UUID | None = None) -> None:
    if not document:
        return
    query = select(Patient.id).where(Patient.clinic_id == clinic_id,
                                     Patient.document_number == document)
    if exclude_id:
        query = query.where(Patient.id != exclude_id)
    if db.scalar(query):
        raise _DUPLICATE_DOCUMENT


def _can_manage_access(user: CurrentUser, access: PatientAccess | None) -> bool:
    return user.is_admin or (access is not None and access.level == AccessLevel.responsible.value)


def _grant(
    db: Session, user: CurrentUser, patient: Patient, professional_id: uuid.UUID,
    level: AccessLevel, reason: str | None, request: Request,
) -> PatientAccess:
    prof = get_clinic_professional(db, user, professional_id)
    if active_access(db, user.clinic_id, prof.id, patient.id):
        raise HTTPException(status.HTTP_409_CONFLICT,
                            detail="Ese profesional ya tiene acceso a este paciente.")
    if level == AccessLevel.responsible and db.scalar(
        select(PatientAccess.id).where(
            PatientAccess.patient_id == patient.id, PatientAccess.clinic_id == user.clinic_id,
            PatientAccess.level == AccessLevel.responsible.value, PatientAccess.revoked_at.is_(None),
        )
    ):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail="El paciente ya tiene un profesional responsable. Revoca ese acceso primero.",
        )
    access = PatientAccess(
        clinic_id=user.clinic_id, patient_id=patient.id, user_id=prof.id, level=level.value,
        reason=reason or None, granted_by=user.id,
    )
    db.add(access)
    db.flush()
    audit.record(db, clinic_id=user.clinic_id, actor_id=user.id, action="access.grant",
                 entity_type="patient_access", entity_id=access.id, patient_id=patient.id,
                 details={"level": level.value, "target_user_id": str(prof.id),
                          "reason_given": bool(reason)},
                 request=request)
    return access


# ---------- Pacientes ----------


def branch_filter_id(user: CurrentUser, branch: str | None) -> uuid.UUID | None:
    """Filtro de sucursal del listado.

    * "" (sin indicar): la sucursal activa para Administración y Recepción; todas para
      profesionales (ven a sus pacientes estén donde estén).
    * "all": todas las que el usuario puede ver.
    * "attend": los que pueden atenderse en la sucursal activa (se resuelve en
      ``filtered_patients``; aquí cuenta como "todas").
    * un id: esa sucursal.
    """
    if branch in ("all", "attend"):
        return None
    if branch:
        try:
            return uuid.UUID(branch)
        except ValueError:
            raise HTTPException(422, detail="La sucursal indicada no es válida.") from None
    return None if user.is_professional else user.branch_id


AyexFilter = Literal["due", "missing"]


def ayex_due_before(db: Session, clinic_id: uuid.UUID) -> date:
    """Los AYEX que vencen antes de esta fecha (hora de la clínica) están "vencidos o vencen
    en los próximos 3 meses", igual que en el Inicio."""
    return ayex_alert_before(clinic_today(db, clinic_id))


def filtered_patients(user: CurrentUser, q: str | None, status_filter: PatientStatus | None,
                      affiliation: AffiliationType | None, branch_id: uuid.UUID | None = None,
                      attend_in: uuid.UUID | None = None, ayex: AyexFilter | None = None,
                      ayex_before: date | None = None):
    """Pacientes que el usuario puede ver, con los filtros del listado (también para exportar).

    ``attend_in``: solo los que pueden atenderse en esa sucursal (los de ella y los privados),
    para elegir paciente al dar un turno.
    ``ayex``: "due" = AYEX vencidos o que vencen antes de ``ayex_before``; "missing" = AYEX sin
    fecha de vencimiento cargada (los mismos que cuenta el Inicio).
    """
    query = visible_patients(user)
    if branch_id:
        query = query.where(Patient.branch_id == branch_id)
    if attend_in:
        query = query.where(or_(Patient.branch_id == attend_in,
                                Patient.affiliation == AffiliationType.private.value))
    if q and q.strip():
        term = f"%{q.strip()}%"
        query = query.where(or_(
            Patient.first_name.ilike(term), Patient.last_name.ilike(term),
            Patient.second_last_name.ilike(term), Patient.document_number.ilike(term),
        ))
    if status_filter:
        query = query.where(Patient.status == status_filter.value)
    if affiliation:
        query = query.where(Patient.affiliation == affiliation.value)
    if ayex:
        query = query.where(Patient.affiliation == AffiliationType.ayex.value)
        if ayex == "missing":
            query = query.where(Patient.ayex_expires_on.is_(None))
        else:
            query = query.where(Patient.ayex_expires_on < ayex_before)
    return query.order_by(Patient.last_name, Patient.first_name)


@router.get("", response_model=list[PatientListItem])
def list_patients(
    request: Request,
    response: Response,
    q: str | None = Query(default=None, max_length=100),
    status_filter: PatientStatus | None = Query(default=None, alias="status"),
    affiliation: AffiliationType | None = None,
    branch: str | None = Query(default=None, max_length=40),
    ayex: AyexFilter | None = None,
    page: int = Query(default=1, ge=1, le=10000),
    page_size: int = Query(default=50, ge=1, le=200),
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Listado paginado. El total de resultados va en la cabecera ``X-Total-Count``."""
    query = filtered_patients(user, q, status_filter, affiliation, branch_filter_id(user, branch),
                              attend_in=user.branch_id if branch == "attend" else None,
                              ayex=ayex, ayex_before=ayex_due_before(db, user.clinic_id) if ayex else None)
    total = db.scalar(select(func.count()).select_from(query.order_by(None).subquery()))
    patients = db.scalars(query.offset((page - 1) * page_size).limit(page_size)).all()
    response.headers["X-Total-Count"] = str(total)
    responsibles = _responsibles(db, user.clinic_id, [p.id for p in patients])
    collaborators = _collaborator_names(db, user.clinic_id, [p.id for p in patients])
    no_shows = _no_shows_this_month(db, user.clinic_id, [p.id for p in patients])
    names = branch_names(db, user.clinic_id)
    audit.record(db, clinic_id=user.clinic_id, actor_id=user.id, action="patient.list",
                 entity_type="patient", details={"count": len(patients)}, request=request)
    db.commit()
    return [
        PatientListItem(**PatientOut.model_validate(p).model_dump(),
                        branch_name=names.get(p.branch_id),
                        responsible_id=responsibles.get(p.id, (None, None))[0],
                        responsible_name=responsibles.get(p.id, (None, None))[1],
                        collaborator_names=collaborators.get(p.id, []),
                        no_shows_month=no_shows.get(p.id, 0))
        for p in patients
    ]


@router.post("", response_model=PatientOut, status_code=status.HTTP_201_CREATED)
def create_patient(
    payload: PatientCreateIn,
    request: Request,
    user: CurrentUser = Depends(require_staff_or_titular),  # en un espacio independiente, el titular
    db: Session = Depends(get_db),
):
    # El titular de un espacio independiente siempre queda como responsable de sus pacientes
    # (si no, no podría verlos: un profesional solo ve los pacientes a los que tiene acceso).
    responsible_id = user.id if user.is_titular else payload.responsible_professional_id
    is_ayex = payload.affiliation == AffiliationType.ayex
    if is_ayex and payload.ayex_expires_on is None:
        raise _AYEX_DATE_REQUIRED
    _check_document_free(db, user.clinic_id, payload.document_number)
    branch_id = resolve_branch(db, user.clinic_id, user.id, user.role, payload.branch_id, user.branch_id)
    patient = Patient(
        clinic_id=user.clinic_id,
        branch_id=branch_id,
        first_name=payload.first_name,
        middle_name=payload.middle_name,
        last_name=payload.last_name,
        second_last_name=payload.second_last_name,
        document_number=payload.document_number,
        sex=payload.sex.value if payload.sex else None,
        affiliation=payload.affiliation.value,
        ayex_expires_on=payload.ayex_expires_on if is_ayex else None,
        birth_date=payload.birth_date,
        phone=payload.phone,
        email=payload.email,
        **PatientAddress.model_validate(payload.model_dump()).model_dump(),
        status=PatientStatus.active.value,
        created_by=user.id,
    )
    db.add(patient)
    db.flush()
    audit.record(db, clinic_id=user.clinic_id, actor_id=user.id, action="patient.create",
                 entity_type="patient", entity_id=patient.id, patient_id=patient.id,
                 request=request)
    if responsible_id:
        _grant(db, user, patient, responsible_id, AccessLevel.responsible,
               "Asignación inicial", request)
    db.commit()
    return patient


@router.get("/{patient_id}", response_model=PatientDetailOut)
def get_patient(
    patient_id: uuid.UUID,
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    patient = get_visible_patient(db, user, patient_id)
    access = active_access(db, user.clinic_id, user.id, patient.id)
    audit.record(db, clinic_id=user.clinic_id, actor_id=user.id, action="patient.view",
                 entity_type="patient", entity_id=patient.id, patient_id=patient.id,
                 request=request)
    db.commit()
    return PatientDetailOut(
        **PatientOut.model_validate(patient).model_dump(),
        my_access_level=access.level if access else None,
        can_view_clinical=user.is_professional and access is not None,
        can_view_reports=(user.is_professional and access is not None) or user.is_reception or user.is_admin,
        can_edit=user.is_admin or user.is_reception
        or (access is not None and access.level == AccessLevel.responsible.value),
        can_manage_access=_can_manage_access(user, access),
        responsible_id=_responsibles(db, user.clinic_id, [patient.id]).get(patient.id, (None, None))[0],
        responsible_name=_responsible_names(db, user.clinic_id, [patient.id]).get(patient.id),
        collaborator_names=_collaborator_names(db, user.clinic_id, [patient.id]).get(patient.id, []),
        branch_name=branch_names(db, user.clinic_id).get(patient.branch_id),
        future_appointments=len(
            appointment_moves.patient_future_appointments(db, user.clinic_id, patient.id)),
    )


@router.patch("/{patient_id}", response_model=PatientOut)
def update_patient(
    patient_id: uuid.UUID,
    payload: PatientUpdateIn,
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    patient = get_visible_patient(db, user, patient_id)
    if user.is_professional:
        access = active_access(db, user.clinic_id, user.id, patient.id)
        if access is None or access.level != AccessLevel.responsible.value:
            raise HTTPException(status.HTTP_403_FORBIDDEN,
                                detail="Solo el profesional responsable puede editar estos datos.")
    changes = payload.model_dump(exclude_unset=True)
    if "branch_id" in changes:
        changes["branch_id"] = resolve_branch(db, user.clinic_id, user.id, user.role,
                                              changes["branch_id"], None)
    for field in ("first_name", "last_name", "status", "affiliation"):
        if field in changes and changes[field] is None:
            raise HTTPException(422, detail="Nombre, apellido, estado y tipo de afiliación "
                                            "no pueden quedar vacíos.")
    old_status = patient.status
    if "document_number" in changes:
        _check_document_free(db, user.clinic_id, changes["document_number"], exclude_id=patient.id)
    for field, value in changes.items():
        setattr(patient, field, value.value if isinstance(value, (PatientStatus, Sex, AffiliationType)) else value)
    # Vencimiento del AYEX: obligatorio al pasar a AYEX o al tocar la fecha; si deja de ser
    # AYEX, se borra. (Los AYEX cargados antes sin fecha se pueden seguir editando hasta
    # que alguien cambie la afiliación o la fecha: el Inicio avisa cuántos faltan.)
    if patient.affiliation != AffiliationType.ayex.value:
        patient.ayex_expires_on = None
    elif ("affiliation" in changes or "ayex_expires_on" in changes) and patient.ayex_expires_on is None:
        db.rollback()
        raise _AYEX_DATE_REQUIRED
    details = {"fields": sorted(changes.keys())}
    if "status" in changes:
        details.update(from_status=old_status, to_status=patient.status)
    # Un paciente que deja de estar activo no puede tener turnos futuros: se cancelan.
    if old_status == PatientStatus.active.value and patient.status != PatientStatus.active.value:
        reason = _STATUS_CANCEL_REASON[patient.status]
        upcoming = appointment_moves.patient_future_appointments(db, user.clinic_id, patient.id)
        for appt in upcoming:
            appointment_moves.cancel(db, user, appt, reason, request)
        details["count"] = len(upcoming)
    # AYEX, Tutela Militar y Tutela Policial se atienden solo en su sucursal: si el paciente
    # cambia de sucursal (o deja de ser privado), se cancelan sus turnos futuros en otras.
    elif patient.affiliation != AffiliationType.private.value and (
            "branch_id" in changes or "affiliation" in changes):
        elsewhere = [a for a in appointment_moves.patient_future_appointments(db, user.clinic_id, patient.id)
                     if a.branch_id != patient.branch_id]
        names = branch_names(db, user.clinic_id)
        for appt in elsewhere:
            appointment_moves.cancel(
                db, user, appt, f"El paciente se atiende solo en la sucursal {names.get(patient.branch_id, '')}",
                request)
        if elsewhere:
            details["count"] = len(elsewhere)
    audit.record(db, clinic_id=user.clinic_id, actor_id=user.id, action="patient.update",
                 entity_type="patient", entity_id=patient.id, patient_id=patient.id,
                 details=details, request=request)
    db.commit()
    return patient


_STATUS_CANCEL_REASON = {
    PatientStatus.paused.value: "Paciente en pausa",
    PatientStatus.discharged.value: "Paciente dado de alta",
    PatientStatus.inactive.value: "Paciente inactivo",
}


# ---------- Accesos ----------


@router.get("/{patient_id}/access", response_model=list[AccessOut])
def list_access(
    patient_id: uuid.UUID,
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Historial completo de autorizaciones (vigentes y revocadas)."""
    if user.is_reception:
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            detail="Tu rol no tiene permiso para ver los accesos.")
    patient = get_visible_patient(db, user, patient_id)
    holder = aliased(User)
    granter = aliased(User)
    revoker = aliased(User)
    rows = db.execute(
        select(PatientAccess, holder.full_name, granter.full_name, revoker.full_name)
        .join(holder, holder.id == PatientAccess.user_id)
        .join(granter, granter.id == PatientAccess.granted_by)
        .outerjoin(revoker, revoker.id == PatientAccess.revoked_by)
        .where(PatientAccess.patient_id == patient.id, PatientAccess.clinic_id == user.clinic_id)
        .order_by(PatientAccess.granted_at.desc())
    ).all()
    audit.record(db, clinic_id=user.clinic_id, actor_id=user.id, action="access.list",
                 entity_type="patient", entity_id=patient.id, patient_id=patient.id,
                 request=request)
    db.commit()
    upcoming = appointment_moves.future_counts(db, user.clinic_id, patient.id)
    return [
        AccessOut(
            id=a.id, user_id=a.user_id, user_name=holder_name, level=a.level, reason=a.reason,
            granted_by_name=granter_name, granted_at=a.granted_at, revoked_by_name=revoker_name,
            revoked_at=a.revoked_at, revoke_reason=a.revoke_reason,
            future_appointments=0 if a.revoked_at else upcoming.get(a.user_id, 0),
        )
        for a, holder_name, granter_name, revoker_name in rows
    ]


@router.post("/{patient_id}/access", response_model=AccessOut, status_code=status.HTTP_201_CREATED)
def grant_access(
    patient_id: uuid.UUID,
    payload: AccessGrantIn,
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Concede acceso. Admin: cualquier nivel. Responsable: solo colaboradores."""
    patient = get_visible_patient(db, user, patient_id)
    my_access = active_access(db, user.clinic_id, user.id, patient.id)
    if not _can_manage_access(user, my_access):
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            detail="Solo administración o el profesional responsable pueden conceder accesos.")
    if not user.is_admin and payload.level != AccessLevel.collaborator:
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            detail="Solo administración puede asignar el profesional responsable.")
    access = _grant(db, user, patient, payload.professional_id, payload.level, payload.reason, request)
    db.commit()
    holder = db.get(User, access.user_id)
    return AccessOut(
        id=access.id, user_id=access.user_id, user_name=holder.full_name, level=access.level,
        reason=access.reason, granted_by_name=user.full_name, granted_at=access.granted_at,
        revoked_by_name=None, revoked_at=None, revoke_reason=None,
    )


@router.post("/{patient_id}/access/{access_id}/revoke", status_code=status.HTTP_204_NO_CONTENT)
def revoke_access(
    patient_id: uuid.UUID,
    access_id: uuid.UUID,
    payload: AccessRevokeIn,
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Revoca un acceso. Admin: cualquiera. Responsable: solo colaboradores."""
    patient = get_visible_patient(db, user, patient_id)
    my_access = active_access(db, user.clinic_id, user.id, patient.id)
    if not _can_manage_access(user, my_access):
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            detail="Solo administración o el profesional responsable pueden revocar accesos.")
    access = db.scalar(
        select(PatientAccess).where(
            PatientAccess.id == access_id, PatientAccess.patient_id == patient.id,
            PatientAccess.clinic_id == user.clinic_id,
        )
    )
    if access is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Acceso no encontrado.")
    if access.revoked_at is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Ese acceso ya estaba revocado.")
    if not user.is_admin and access.level != AccessLevel.collaborator.value:
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            detail="Solo administración puede retirar al profesional responsable.")
    access.revoked_at = utcnow()
    access.revoked_by = user.id
    access.revoke_reason = payload.reason
    # Sin acceso no puede atenderlo: sus turnos futuros con el paciente se cancelan con el motivo.
    upcoming = appointment_moves.future_appointments(db, user.clinic_id, access.user_id, patient.id)
    for appt in upcoming:
        appointment_moves.cancel(db, user, appt, payload.reason, request)
    audit.record(db, clinic_id=user.clinic_id, actor_id=user.id, action="access.revoke",
                 entity_type="patient_access", entity_id=access.id, patient_id=patient.id,
                 details={"level": access.level, "target_user_id": str(access.user_id),
                          "count": len(upcoming)},
                 request=request)
    db.commit()


@router.post("/{patient_id}/responsible", response_model=AccessOut)
def change_responsible(
    patient_id: uuid.UUID,
    payload: ResponsibleChangeIn,
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Asigna o cambia el profesional responsable en un solo paso.

    * Administración: asigna o cambia (al cambiar, el motivo es obligatorio).
    * Recepción: solo asigna a pacientes que todavía no tienen responsable.
    El anterior queda revocado con el motivo, y si el nuevo era colaborador pasa a responsable.
    """
    if not (user.is_admin or user.is_reception):
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            detail="Solo administración o recepción pueden asignar el responsable.")
    patient = get_visible_patient(db, user, patient_id)
    previous = current_responsible(db, user.clinic_id, patient.id)
    if previous is not None and not user.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            detail="El paciente ya tiene responsable. Solo administración puede cambiarlo.")
    if previous is not None and not payload.reason:
        raise HTTPException(422, detail="Indicá el motivo del cambio de responsable.")
    prof = get_clinic_professional(db, user, payload.professional_id)
    reason = payload.reason or "Asignación inicial"
    access = assign_responsible(db, user, patient.id, prof, reason, request)
    # Turnos futuros del responsable anterior con este paciente: al nuevo, o cancelados.
    if previous is not None:
        for appt in appointment_moves.future_appointments(db, user.clinic_id, previous.user_id, patient.id):
            if payload.move_appointments:
                appointment_moves.move(db, user, appt, prof.id, request,
                                       reason=f"Cambio de profesional responsable: {reason}")
            else:
                appointment_moves.cancel(db, user, appt, reason, request)
    db.commit()
    return AccessOut(
        id=access.id, user_id=access.user_id, user_name=prof.full_name, level=access.level,
        reason=access.reason, granted_by_name=user.full_name, granted_at=access.granted_at,
        revoked_by_name=None, revoked_at=None, revoke_reason=None,
    )
