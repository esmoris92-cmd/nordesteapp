"""Agenda por profesional y sucursal: disponibilidad semanal y turnos.

* Cada horario de disponibilidad y cada turno pertenecen a una sucursal. La agenda muestra
  la sucursal activa de la sesión y los turnos nuevos se dan en ella.
* Un profesional nunca está en dos lugares a la vez: sus horarios no se superponen entre
  sucursales y no puede tener turnos simultáneos en sucursales distintas.
* AYEX, Tutela Militar y Tutela Policial se atienden solo en la sucursal del paciente;
  privados, en cualquiera.
* Dar, reprogramar y cancelar turnos, y cargar o quitar horarios, lo hacen solo Recepción y
  Administración (decisión del 24/11/2026). Los profesionales ven la agenda y marcan sus turnos
  como realizados o ausentes. El titular de un espacio independiente sí agenda: no tiene
  Recepción ni Administración.
"""

import uuid
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session, aliased

from app import audit
from app.db import get_db
from app.deps import CurrentUser, get_current_user, utcnow
from app.models import (
    Appointment,
    AppointmentStatus,
    AuditEvent,
    Availability,
    Clinic,
    Patient,
    PatientStatus,
    User,
)
from app.branches import branch_names, check_patient_branch, works_in_branch
from app.permissions import active_access, get_clinic_professional, visible_patients
from app.schemas import (
    AppointmentCancelIn,
    AppointmentCreateIn,
    AppointmentOut,
    AppointmentRescheduleIn,
    AppointmentStatusIn,
    AvailabilityIn,
    AvailabilityOut,
    AbsenceOut,
    RescheduleOut,
)

router = APIRouter(prefix="/api", tags=["agenda"])

_WEEKDAYS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]

SUNDAY = 6  # la clínica no atiende los domingos (el BPS tampoco los contempla)
SUNDAY_CLOSED = "La clínica no atiende los domingos."
_APPOINTMENT_NOT_FOUND = HTTPException(status.HTTP_404_NOT_FOUND, detail="Turno no encontrado.")
ONLY_STAFF_SCHEDULES = "Los turnos y los horarios los manejan Recepción y Administración."


def _check_can_schedule(user: CurrentUser) -> None:
    """Dar, reprogramar o cancelar turnos y cambiar horarios: Recepción, Administración o el
    titular de un espacio independiente. Un profesional de una clínica, no."""
    if not (user.is_admin or user.is_reception or user.is_titular):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail=ONLY_STAFF_SCHEDULES)


def _check_agenda_scope(user: CurrentUser, professional_id: uuid.UUID) -> None:
    """Admin y recepción gestionan cualquier agenda; un profesional solo la suya."""
    if user.is_admin or user.is_reception:
        return
    if user.is_professional and user.id == professional_id:
        return
    raise HTTPException(status.HTTP_403_FORBIDDEN,
                        detail="Solo podés gestionar tu propia agenda.")


# ---------- Disponibilidad ----------


@router.get("/availability", response_model=list[AvailabilityOut])
def list_availability(
    professional_id: uuid.UUID | None = None,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Con ``professional_id``: todos los horarios de ese profesional, en todas sus sucursales.
    Sin él: los de todos los profesionales en la sucursal activa, para las vistas «Día (todos)»
    y «Horas libres» (también los profesionales, para coordinar con sus compañeros)."""
    query = select(Availability).where(Availability.clinic_id == user.clinic_id)
    if professional_id is not None:
        _check_agenda_scope(user, professional_id)
        query = query.where(Availability.professional_id == professional_id)
    elif user.is_admin or user.is_reception or user.is_professional:
        query = query.where(Availability.branch_id == user.branch_id)
    else:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Solo podés ver tu propia agenda.")
    blocks = db.scalars(query.order_by(Availability.weekday, Availability.start_time)).all()
    names = branch_names(db, user.clinic_id)
    return [_availability_out(b, names) for b in blocks]


def _availability_out(block: Availability, names: dict[uuid.UUID, str]) -> AvailabilityOut:
    return AvailabilityOut(id=block.id, professional_id=block.professional_id,
                           branch_id=block.branch_id, branch_name=names.get(block.branch_id),
                           weekday=block.weekday, start_time=block.start_time,
                           end_time=block.end_time)


@router.post("/availability", response_model=AvailabilityOut, status_code=status.HTTP_201_CREATED)
def create_availability(
    payload: AvailabilityIn,
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Agrega un horario en la sucursal activa."""
    _check_can_schedule(user)
    _check_agenda_scope(user, payload.professional_id)
    if payload.weekday == SUNDAY:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=SUNDAY_CLOSED)
    prof = get_clinic_professional(db, user, payload.professional_id)
    names = branch_names(db, user.clinic_id)
    branch_id = user.branch_id
    if branch_id is None or not works_in_branch(db, user.clinic_id, prof.id, branch_id):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail=f"{prof.full_name} no trabaja en la sucursal {names.get(branch_id, '')}. "
                   "Administración puede asignársela en Usuarios.",
        )
    # Sin filtrar por sucursal: nadie puede estar en dos sucursales a la misma hora.
    overlaps = db.scalars(
        select(Availability).where(
            Availability.clinic_id == user.clinic_id,
            Availability.professional_id == payload.professional_id,
            Availability.weekday == payload.weekday,
            Availability.start_time < payload.end_time,
            Availability.end_time > payload.start_time,
        ).order_by(Availability.start_time)
    ).all()
    if overlaps:
        # Decir exactamente qué bloque(s) estorban, para saber cuál quitar.
        def describe(b: Availability) -> str:
            where = "en esta sucursal" if b.branch_id == branch_id else f"en la sucursal {names.get(b.branch_id, '')}"
            return f"{_WEEKDAYS[b.weekday]} {b.start_time:%H:%M}–{b.end_time:%H:%M} {where}"
        listed = " y con ".join(describe(b) for b in overlaps)
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail=f"Ese horario se superpone con {listed}. Quitá primero "
                   f"{'ese horario' if len(overlaps) == 1 else 'esos horarios'} y volvé a cargar la "
                   "parte que corresponda.",
        )
    block = Availability(clinic_id=user.clinic_id, branch_id=branch_id, **payload.model_dump())
    db.add(block)
    db.flush()
    audit.record(db, clinic_id=user.clinic_id, actor_id=user.id, action="availability.create",
                 entity_type="availability", entity_id=block.id,
                 details={"professional_id": str(payload.professional_id)}, request=request)
    db.commit()
    return _availability_out(block, names)


@router.delete("/availability/{block_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_availability(
    block_id: uuid.UUID,
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _check_can_schedule(user)
    block = db.scalar(
        select(Availability).where(Availability.id == block_id,
                                   Availability.clinic_id == user.clinic_id)
    )
    if block is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Bloque no encontrado.")
    _check_agenda_scope(user, block.professional_id)
    if user.is_reception and block.branch_id != user.branch_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            detail="Solo podés cambiar los horarios de tu sucursal.")
    audit.record(db, clinic_id=user.clinic_id, actor_id=user.id, action="availability.delete",
                 entity_type="availability", entity_id=block.id,
                 details={"professional_id": str(block.professional_id)}, request=request)
    db.delete(block)
    db.commit()


# ---------- Turnos ----------


def _appointment_rows(db: Session, user: CurrentUser, query) -> list[AppointmentOut]:
    prof = aliased(User)
    moved_to = aliased(Appointment)
    rows = db.execute(
        query.add_columns(Patient.first_name, Patient.last_name, prof.full_name, moved_to.starts_at)
        .join(Patient, (Patient.id == Appointment.patient_id)
              & (Patient.clinic_id == Appointment.clinic_id))
        .join(prof, (prof.id == Appointment.professional_id)
              & (prof.clinic_id == Appointment.clinic_id))
        .outerjoin(moved_to, (moved_to.id == Appointment.rescheduled_to_id)
                   & (moved_to.clinic_id == Appointment.clinic_id))
    ).all()
    names = branch_names(db, user.clinic_id) if rows else {}
    return [
        AppointmentOut(
            id=a.id, patient_id=a.patient_id, patient_name=f"{fn} {ln}",
            professional_id=a.professional_id, professional_name=pn,
            branch_id=a.branch_id, branch_name=names.get(a.branch_id), starts_at=a.starts_at,
            ends_at=a.ends_at, status=a.status, cancel_reason=a.cancel_reason,
            rescheduled_to_id=a.rescheduled_to_id, reschedule_reason=a.reschedule_reason,
            rescheduled_to_starts_at=moved_starts, no_show_reason=a.no_show_reason,
        )
        for a, fn, ln, pn, moved_starts in rows
    ]


def _max_simultaneous(intervals: list[tuple[datetime, datetime]]) -> int:
    """Máximo de turnos que coinciden en un mismo instante (barrido de inicios y fines)."""
    events = [(s, 1) for s, _ in intervals] + [(e, -1) for _, e in intervals]
    events.sort(key=lambda ev: (ev[0], ev[1]))  # un fin y un inicio a la misma hora no se pisan
    current = peak = 0
    for _, delta in events:
        current += delta
        peak = max(peak, current)
    return peak


def _validate_slot(
    db: Session, user: CurrentUser, professional_id: uuid.UUID, patient_id: uuid.UUID,
    starts_at: datetime, ends_at: datetime, branch_id: uuid.UUID,
    exclude_id: uuid.UUID | None = None, confirm_past: bool = False,
) -> bool:
    """Verifica que el profesional trabaje en la sucursal y tenga disponibilidad allí, su cupo
    de pacientes simultáneos, que no tenga otro turno a esa hora en otra sucursal y que el
    paciente no tenga otro turno superpuesto."""
    # Bloquea la fila del profesional para que dos reservas simultáneas no se pisen.
    db.execute(
        select(User.id).where(User.id == professional_id, User.clinic_id == user.clinic_id)
        .with_for_update()
    )
    names = branch_names(db, user.clinic_id)
    if not works_in_branch(db, user.clinic_id, professional_id, branch_id):
        raise HTTPException(status.HTTP_409_CONFLICT,
                            detail=f"El profesional no trabaja en la sucursal {names.get(branch_id, '')}.")
    clinic = db.get(Clinic, user.clinic_id)
    tz = ZoneInfo(clinic.timezone)
    local_start = starts_at.astimezone(tz)
    local_end = ends_at.astimezone(tz)
    if local_start.date() != local_end.date():
        raise HTTPException(status.HTTP_409_CONFLICT,
                            detail="El turno debe empezar y terminar el mismo día.")
    if local_start.weekday() == SUNDAY:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=SUNDAY_CLOSED)
    # Turnos con fecha pasada (por ejemplo, una sesión que se olvidó agendar): solo dentro del
    # mes en curso, para no cambiar meses que ya pueden estar informados al BPS, y con
    # confirmación explícita. Quedan marcados en la auditoría.
    is_past = starts_at < utcnow()
    if is_past:
        month_start = datetime.now(tz).date().replace(day=1)
        if local_start.date() < month_start:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail=f"Solo se pueden cargar turnos con fecha pasada dentro del mes en curso "
                       f"(desde el {month_start:%d/%m/%Y}). Los meses anteriores pueden estar ya "
                       "informados al BPS.",
            )
        if not confirm_past:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail="Ese turno es en una fecha u hora que ya pasó. Confirmá que querés cargarlo así.",
            )
    blocks = db.scalars(
        select(Availability).where(
            Availability.clinic_id == user.clinic_id,
            Availability.professional_id == professional_id,
            Availability.branch_id == branch_id,
            Availability.weekday == local_start.weekday(),
        )
    ).all()
    fits = any(
        b.start_time <= local_start.time().replace(tzinfo=None)
        and local_end.time().replace(tzinfo=None) <= b.end_time
        for b in blocks
    )
    if not fits:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            detail="El horario está fuera de la disponibilidad del profesional "
                                   f"en la sucursal {names.get(branch_id, '')}.")
    def overlapping():
        q = select(Appointment).where(
            Appointment.clinic_id == user.clinic_id,
            Appointment.status == AppointmentStatus.scheduled.value,
            Appointment.starts_at < ends_at,
            Appointment.ends_at > starts_at,
        )
        return q.where(Appointment.id != exclude_id) if exclude_id else q

    # El mismo paciente no puede estar en dos turnos a la vez (con ningún profesional).
    if db.scalar(overlapping().where(Appointment.patient_id == patient_id).limit(1)):
        raise HTTPException(status.HTTP_409_CONFLICT,
                            detail="El paciente ya tiene otro turno en ese horario.")

    # El profesional no puede estar a la misma hora en otra sucursal.
    elsewhere = db.scalar(overlapping().where(Appointment.professional_id == professional_id,
                                              Appointment.branch_id != branch_id).limit(1))
    if elsewhere is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail=f"El profesional ya tiene un turno en ese horario en la sucursal "
                   f"{names.get(elsewhere.branch_id, '')}.",
        )

    # Cupo del profesional: cuántos pacientes puede atender a la vez.
    capacity = db.scalar(select(User.max_concurrent_patients).where(User.id == professional_id)) or 1
    others = db.scalars(overlapping().where(Appointment.professional_id == professional_id)).all()
    intervals = [(max(a.starts_at, starts_at), min(a.ends_at, ends_at)) for a in others]
    if _max_simultaneous(intervals) + 1 > capacity:
        detail = ("El profesional ya tiene un turno en ese horario." if capacity == 1 else
                  f"El profesional ya tiene {capacity} pacientes en ese horario (máximo permitido).")
        raise HTTPException(status.HTTP_409_CONFLICT, detail=detail)
    return is_past


def _get_appointment(db: Session, user: CurrentUser, appointment_id: uuid.UUID) -> Appointment:
    appt = db.scalar(
        select(Appointment).where(Appointment.id == appointment_id,
                                  Appointment.clinic_id == user.clinic_id)
    )
    if appt is None:
        raise _APPOINTMENT_NOT_FOUND
    if user.is_professional and appt.professional_id != user.id:
        raise _APPOINTMENT_NOT_FOUND
    if user.is_reception and appt.branch_id != user.branch_id:  # recepción: solo su sucursal
        raise _APPOINTMENT_NOT_FOUND
    if not (user.is_admin or user.is_reception or user.is_professional):
        raise _APPOINTMENT_NOT_FOUND
    return appt


def _require_scheduled(appt: Appointment) -> None:
    if appt.status != AppointmentStatus.scheduled.value:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            detail="Solo se pueden modificar turnos programados.")


@router.get("/appointments", response_model=list[AppointmentOut])
def list_appointments(
    start: datetime = Query(..., alias="from"),
    end: datetime = Query(..., alias="to"),
    professional_id: uuid.UUID | None = None,
    patient_id: uuid.UUID | None = None,
    all_professionals: bool = False,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Turnos de la sucursal activa (o de un paciente). Un profesional ve solo los suyos, salvo
    con ``all_professionals=true`` (vistas «Día (todos)» y «Horas libres»): ahí ve los de todos
    los profesionales de la sucursal activa, solo para mirar; modificar sigue siendo solo lo suyo."""
    if start.tzinfo is None or end.tzinfo is None:
        raise HTTPException(422,
                            detail="Las fechas deben incluir zona horaria.")
    if end <= start or end - start > timedelta(days=62):
        raise HTTPException(422,
                            detail="El rango de fechas debe ser válido y de hasta 62 días.")
    query = select(Appointment).where(
        Appointment.clinic_id == user.clinic_id,
        Appointment.starts_at < end,
        Appointment.ends_at > start,
    )
    if patient_id:
        # Turnos de un paciente (en su ficha): de todas las sucursales, si se puede ver al paciente.
        if (user.is_admin or user.is_reception) and db.scalar(
                visible_patients(user).where(Patient.id == patient_id)) is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Paciente no encontrado.")
        query = query.where(Appointment.patient_id == patient_id)
    else:
        query = query.where(Appointment.branch_id == user.branch_id)  # la agenda de la sucursal activa
    if user.is_professional:
        if professional_id and professional_id != user.id:
            raise HTTPException(status.HTTP_403_FORBIDDEN,
                                detail="Solo podés ver tu propia agenda.")
        if not (all_professionals and patient_id is None and professional_id is None):
            query = query.where(Appointment.professional_id == user.id)
    elif professional_id:
        query = query.where(Appointment.professional_id == professional_id)
    return _appointment_rows(db, user, query.order_by(Appointment.starts_at))


@router.get("/patients/{patient_id}/reschedules", response_model=list[RescheduleOut])
def patient_reschedules(
    patient_id: uuid.UUID,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Todas las reprogramaciones del paciente, de la más reciente a la más vieja, con su motivo,
    quién la hizo y cuándo (el turno nuevo lo crea quien reprograma). Un profesional ve solo las
    de sus propios turnos, igual que en la lista de turnos."""
    if db.scalar(visible_patients(user).where(Patient.id == patient_id)) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Paciente no encontrado.")
    new = aliased(Appointment)
    prof, new_prof, author = aliased(User), aliased(User), aliased(User)
    query = (
        select(Appointment, new, prof.full_name, new_prof.full_name, author.full_name)
        .outerjoin(new, (new.id == Appointment.rescheduled_to_id) & (new.clinic_id == Appointment.clinic_id))
        .join(prof, (prof.id == Appointment.professional_id) & (prof.clinic_id == Appointment.clinic_id))
        .outerjoin(new_prof, (new_prof.id == new.professional_id) & (new_prof.clinic_id == new.clinic_id))
        .outerjoin(author, (author.id == new.created_by) & (author.clinic_id == new.clinic_id))
        .where(Appointment.clinic_id == user.clinic_id, Appointment.patient_id == patient_id,
               Appointment.status == AppointmentStatus.rescheduled.value)
    )
    if user.is_professional:
        query = query.where((Appointment.professional_id == user.id) | (new.professional_id == user.id))
    rows = db.execute(query.order_by(func.coalesce(new.created_at, Appointment.updated_at).desc())).all()
    return [
        RescheduleOut(
            id=a.id, from_starts_at=a.starts_at, to_starts_at=n.starts_at if n else None,
            to_status=n.status if n else None, professional_name=pn,
            to_professional_name=npn if n and n.professional_id != a.professional_id else None,
            reason=a.reschedule_reason, rescheduled_by=author_name,
            rescheduled_at=n.created_at if n else None,
        )
        for a, n, pn, npn, author_name in rows
    ]


@router.get("/patients/{patient_id}/absences", response_model=list[AbsenceOut])
def patient_absences(
    patient_id: uuid.UUID,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Todos los turnos del paciente marcados como ausente, del más reciente al más viejo, con el
    motivo y quién lo marcó (según la auditoría). Un profesional ve solo los de sus turnos."""
    if db.scalar(visible_patients(user).where(Patient.id == patient_id)) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Paciente no encontrado.")
    query = (
        select(Appointment, User.full_name)
        .join(User, (User.id == Appointment.professional_id) & (User.clinic_id == Appointment.clinic_id))
        .where(Appointment.clinic_id == user.clinic_id, Appointment.patient_id == patient_id,
               Appointment.status == AppointmentStatus.no_show.value)
    )
    if user.is_professional:
        query = query.where(Appointment.professional_id == user.id)
    rows = db.execute(query.order_by(Appointment.starts_at.desc())).all()
    marks: dict[str, tuple[str | None, datetime]] = {}
    if rows:
        author = aliased(User)
        for entity_id, name, when in db.execute(
            select(AuditEvent.entity_id, author.full_name, AuditEvent.created_at)
            .outerjoin(author, (author.id == AuditEvent.actor_id) & (author.clinic_id == AuditEvent.clinic_id))
            .where(AuditEvent.clinic_id == user.clinic_id, AuditEvent.action == "appointment.status",
                   AuditEvent.entity_id.in_([str(a.id) for a, _ in rows]),
                   AuditEvent.details["to_status"].astext == AppointmentStatus.no_show.value)
        ).all():
            marks[entity_id] = (name, when)
    names = branch_names(db, user.clinic_id)
    return [
        AbsenceOut(id=a.id, starts_at=a.starts_at, professional_name=pn, branch_name=names.get(a.branch_id),
                   reason=a.no_show_reason, marked_by=marks.get(str(a.id), (None, None))[0],
                   marked_at=marks.get(str(a.id), (None, None))[1])
        for a, pn in rows
    ]


@router.post("/appointments", response_model=AppointmentOut, status_code=status.HTTP_201_CREATED)
def create_appointment(
    payload: AppointmentCreateIn,
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _check_can_schedule(user)
    _check_agenda_scope(user, payload.professional_id)
    get_clinic_professional(db, user, payload.professional_id)
    patient = db.scalar(
        select(Patient).where(Patient.id == payload.patient_id, Patient.clinic_id == user.clinic_id)
    )
    if patient is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Paciente no encontrado.")
    if active_access(db, user.clinic_id, payload.professional_id, patient.id) is None:
        if user.is_professional:  # no revelar datos de pacientes ajenos
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Paciente no encontrado.")
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail="Este profesional no trabaja con este paciente (no es su responsable ni colaborador). "
                   "Para darle turnos, administración o el profesional responsable deben agregarlo como "
                   "colaborador: ficha del paciente → pestaña Accesos.",
        )
    if patient.status != PatientStatus.active.value:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            detail="Solo se pueden dar turnos a pacientes activos.")
    branch_id = user.branch_id  # el turno se da en la sucursal activa
    check_patient_branch(db, patient, branch_id)
    is_past = _validate_slot(db, user, payload.professional_id, patient.id, payload.starts_at,
                             payload.ends_at, branch_id, confirm_past=payload.confirm_past)
    appt = Appointment(
        clinic_id=user.clinic_id, patient_id=patient.id, professional_id=payload.professional_id,
        branch_id=branch_id, starts_at=payload.starts_at, ends_at=payload.ends_at, created_by=user.id,
    )
    db.add(appt)
    db.flush()
    audit.record(db, clinic_id=user.clinic_id, actor_id=user.id, action="appointment.create",
                 entity_type="appointment", entity_id=appt.id, patient_id=patient.id,
                 details={"professional_id": str(payload.professional_id), "past": is_past}, request=request)
    db.commit()
    return _appointment_rows(db, user, select(Appointment).where(Appointment.id == appt.id))[0]


@router.post("/appointments/{appointment_id}/cancel", response_model=AppointmentOut)
def cancel_appointment(
    appointment_id: uuid.UUID,
    payload: AppointmentCancelIn,
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _check_can_schedule(user)
    appt = _get_appointment(db, user, appointment_id)
    _require_scheduled(appt)
    appt.status = AppointmentStatus.cancelled.value
    appt.cancel_reason = payload.reason
    audit.record(db, clinic_id=user.clinic_id, actor_id=user.id, action="appointment.cancel",
                 entity_type="appointment", entity_id=appt.id, patient_id=appt.patient_id,
                 request=request)
    db.commit()
    return _appointment_rows(db, user, select(Appointment).where(Appointment.id == appt.id))[0]


@router.post("/appointments/{appointment_id}/reschedule", response_model=AppointmentOut,
             status_code=status.HTTP_201_CREATED)
def reschedule_appointment(
    appointment_id: uuid.UUID,
    payload: AppointmentRescheduleIn,
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Crea un turno nuevo y marca el original como "reprogramado" (queda el historial)."""
    _check_can_schedule(user)
    appt = _get_appointment(db, user, appointment_id)
    _require_scheduled(appt)
    check_patient_branch(db, db.get(Patient, appt.patient_id), appt.branch_id)
    is_past = _validate_slot(db, user, appt.professional_id, appt.patient_id, payload.starts_at,
                             payload.ends_at, appt.branch_id, exclude_id=appt.id,
                             confirm_past=payload.confirm_past)
    new_appt = Appointment(
        clinic_id=user.clinic_id, patient_id=appt.patient_id, professional_id=appt.professional_id,
        branch_id=appt.branch_id, starts_at=payload.starts_at, ends_at=payload.ends_at, created_by=user.id,
    )
    db.add(new_appt)
    db.flush()
    appt.status = AppointmentStatus.rescheduled.value
    appt.rescheduled_to_id = new_appt.id
    appt.reschedule_reason = payload.reason
    audit.record(db, clinic_id=user.clinic_id, actor_id=user.id, action="appointment.reschedule",
                 entity_type="appointment", entity_id=appt.id, patient_id=appt.patient_id,
                 details={"new_appointment_id": str(new_appt.id), "past": is_past, "reason_given": True},
                 request=request)
    db.commit()
    return _appointment_rows(db, user, select(Appointment).where(Appointment.id == new_appt.id))[0]


@router.post("/appointments/{appointment_id}/status", response_model=AppointmentOut)
def set_appointment_status(
    appointment_id: uuid.UUID,
    payload: AppointmentStatusIn,
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    appt = _get_appointment(db, user, appointment_id)
    _require_scheduled(appt)
    # Realizado o ausente solo desde que empieza el turno: evita marcar por error uno futuro
    # (el resultado no se puede deshacer).
    if appt.starts_at > utcnow():
        raise HTTPException(status.HTTP_409_CONFLICT,
                            detail="Este turno todavía no empezó: se puede marcar como realizado o "
                                   "ausente desde su hora de inicio.")
    appt.status = payload.status.value
    details: dict = {"to_status": payload.status.value}
    if payload.status == AppointmentStatus.no_show:
        appt.no_show_reason = payload.reason or None
        details["reason_given"] = bool(payload.reason)
    audit.record(db, clinic_id=user.clinic_id, actor_id=user.id, action="appointment.status",
                 entity_type="appointment", entity_id=appt.id, patient_id=appt.patient_id,
                 details=details, request=request)
    db.commit()
    return _appointment_rows(db, user, select(Appointment).where(Appointment.id == appt.id))[0]
