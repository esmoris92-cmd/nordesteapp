"""Turnos futuros que quedarían "sueltos" cuando un profesional deja de atender a un paciente.

Pasa al eliminar (archivar) su cuenta, al revocarle el acceso a un paciente o al cambiar
el responsable. En esos casos sus turnos programados a futuro se cancelan con motivo o se
pasan a otro profesional, en el mismo horario y con las mismas reglas que un turno nuevo.

Nada se borra: un turno pasado a otro profesional queda como "reprogramado" y apunta al nuevo.
"""

import uuid
from zoneinfo import ZoneInfo

from fastapi import HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import audit
from app.deps import CurrentUser, utcnow
from app.models import Appointment, AppointmentStatus, Clinic, Patient
from app.permissions import active_access


def future_appointments(db: Session, clinic_id: uuid.UUID, professional_id: uuid.UUID,
                        patient_id: uuid.UUID | None = None) -> list[Appointment]:
    """Turnos programados que todavía no empezaron."""
    query = select(Appointment).where(
        Appointment.clinic_id == clinic_id, Appointment.professional_id == professional_id,
        Appointment.status == AppointmentStatus.scheduled.value, Appointment.starts_at > utcnow(),
    )
    if patient_id is not None:
        query = query.where(Appointment.patient_id == patient_id)
    return list(db.scalars(query.order_by(Appointment.starts_at)).all())


def patient_future_appointments(db: Session, clinic_id: uuid.UUID,
                                patient_id: uuid.UUID) -> list[Appointment]:
    """Turnos programados a futuro de un paciente, con cualquier profesional."""
    return list(db.scalars(
        select(Appointment).where(
            Appointment.clinic_id == clinic_id, Appointment.patient_id == patient_id,
            Appointment.status == AppointmentStatus.scheduled.value, Appointment.starts_at > utcnow(),
        ).order_by(Appointment.starts_at)
    ).all())


def future_counts(db: Session, clinic_id: uuid.UUID, patient_id: uuid.UUID) -> dict[uuid.UUID, int]:
    """Cantidad de turnos futuros de cada profesional con este paciente."""
    rows = db.execute(
        select(Appointment.professional_id, func.count())
        .where(Appointment.clinic_id == clinic_id, Appointment.patient_id == patient_id,
               Appointment.status == AppointmentStatus.scheduled.value,
               Appointment.starts_at > utcnow())
        .group_by(Appointment.professional_id)
    ).all()
    return dict(rows)


def _when(db: Session, appt: Appointment) -> str:
    clinic = db.get(Clinic, appt.clinic_id)
    local = appt.starts_at.astimezone(ZoneInfo(clinic.timezone))
    return local.strftime("%d/%m/%Y %H:%M")


def cancel(db: Session, actor: CurrentUser, appt: Appointment, reason: str,
           request: Request | None) -> None:
    appt.status = AppointmentStatus.cancelled.value
    appt.cancel_reason = reason[:300]
    audit.record(db, clinic_id=actor.clinic_id, actor_id=actor.id, action="appointment.cancel",
                 entity_type="appointment", entity_id=appt.id, patient_id=appt.patient_id,
                 details={"reason_given": True}, request=request)


MOVE_REASON = "Pasó a otro profesional (mismo día y hora)."


def move(db: Session, actor: CurrentUser, appt: Appointment, new_professional_id: uuid.UUID,
         request: Request | None, reason: str | None = None) -> Appointment:
    """Pasa el turno a otro profesional en el mismo horario (debe tener acceso y lugar).
    El motivo queda en el turno original, como en cualquier reprogramación."""
    from app.routers.agenda import _validate_slot  # evita importar el router al cargar el módulo

    when = _when(db, appt)
    if active_access(db, actor.clinic_id, new_professional_id, appt.patient_id) is None:
        patient = db.get(Patient, appt.patient_id)
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail=f"Turno del {when} ({patient.first_name} {patient.last_name}): el profesional "
                   "elegido no tiene asignado a este paciente.",
        )
    try:
        _validate_slot(db, actor, new_professional_id, appt.patient_id, appt.starts_at,
                       appt.ends_at, appt.branch_id, exclude_id=appt.id)
    except HTTPException as exc:
        raise HTTPException(exc.status_code, detail=f"Turno del {when}: {exc.detail}") from None
    new_appt = Appointment(
        clinic_id=actor.clinic_id, patient_id=appt.patient_id, professional_id=new_professional_id,
        branch_id=appt.branch_id, starts_at=appt.starts_at, ends_at=appt.ends_at, created_by=actor.id,
    )
    db.add(new_appt)
    db.flush()
    appt.status = AppointmentStatus.rescheduled.value
    appt.rescheduled_to_id = new_appt.id
    appt.reschedule_reason = (reason or MOVE_REASON)[:300]
    audit.record(db, clinic_id=actor.clinic_id, actor_id=actor.id, action="appointment.reassign",
                 entity_type="appointment", entity_id=appt.id, patient_id=appt.patient_id,
                 details={"professional_id": str(new_professional_id),
                          "new_appointment_id": str(new_appt.id)},
                 request=request)
    return new_appt
