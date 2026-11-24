"""Datos de la pantalla de Inicio.

Los números respetan los mismos permisos que el resto de la app:
* Profesional: solo SUS turnos y los pacientes a los que tiene acceso, en todas sus sucursales.
* Recepción: su sucursal activa.
* Administración: la sucursal activa o, si lo pide, toda la clínica (ver ``branch_scope``).
"""

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ayex_alert import AyexLevel, ayex_alert_before, ayex_level
from app.branch_scope import report_scope
from app.db import get_db
from app.deps import CurrentUser, get_current_user
from app.models import AffiliationType, Appointment, AppointmentStatus, Clinic, Patient, PatientStatus
from app.permissions import visible_patients
from app.routers.agenda import _appointment_rows
from app.schemas import AppointmentOut

router = APIRouter(prefix="/api", tags=["inicio"])


class MonthStats(BaseModel):
    completed: int
    scheduled: int
    no_show: int
    cancelled: int
    attendance_rate: int | None  # % realizados sobre (realizados + ausentes)


class AyexDue(BaseModel):
    patient_id: str
    name: str
    expires_on: date
    expired: bool  # ya venció (antes de hoy)
    level: AyexLevel  # "red" (2 meses o menos, o vencido) o "yellow" (entre 2 y 3 meses)


AYEX_LIST_LIMIT = 50


class DashboardOut(BaseModel):
    scope: str  # "own" (profesional), "branch" (una sucursal) o "clinic" (todas)
    branch_name: str | None = None  # la sucursal mostrada (None = todas)
    today: date
    month: MonthStats
    active_patients: int
    # AYEX vencidos o que vencen en los próximos 3 meses (pacientes activos), ordenados por
    # fecha: primero los vencidos y después del más cercano a vencer al más lejano.
    ayex_due: list[AyexDue]
    ayex_due_total: int  # por si hay más que los que se listan
    ayex_missing: int  # pacientes AYEX activos sin fecha de vencimiento cargada
    next_appointment: AppointmentOut | None
    # Fecha (hora de la clínica) de la próxima sesión y el resto de los turnos de ese día.
    next_day: date | None
    next_day_others: list[AppointmentOut]


@router.get("/dashboard", response_model=DashboardOut)
def dashboard(
    branch: str | None = Query(default=None, max_length=40),
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    scope = report_scope(db, user, branch)
    tz = ZoneInfo(db.get(Clinic, user.clinic_id).timezone)
    now = datetime.now(tz)
    today = now.date()
    month_start = datetime.combine(today.replace(day=1), time(0), tzinfo=tz)
    next_month = (today.replace(day=28) + timedelta(days=4)).replace(day=1)
    month_end = datetime.combine(next_month, time(0), tzinfo=tz)

    base = select(Appointment).where(Appointment.clinic_id == user.clinic_id)
    if user.is_professional:
        base = base.where(Appointment.professional_id == user.id)
    if scope.branch_id:
        base = base.where(Appointment.branch_id == scope.branch_id)

    # Turnos del mes por estado ("reprogramado" no cuenta: el turno nuevo ya está incluido).
    month_ids = base.with_only_columns(Appointment.id).where(
        Appointment.starts_at >= month_start, Appointment.starts_at < month_end
    )
    counts = dict(db.execute(
        select(Appointment.status, func.count())
        .where(Appointment.id.in_(month_ids))
        .group_by(Appointment.status)
    ).all())
    completed = counts.get(AppointmentStatus.completed.value, 0)
    no_show = counts.get(AppointmentStatus.no_show.value, 0)
    month = MonthStats(
        completed=completed,
        scheduled=counts.get(AppointmentStatus.scheduled.value, 0),
        no_show=no_show,
        cancelled=counts.get(AppointmentStatus.cancelled.value, 0),
        attendance_rate=round(100 * completed / (completed + no_show)) if completed + no_show else None,
    )

    patients_q = visible_patients(user)
    if scope.branch_id:
        patients_q = patients_q.where(Patient.branch_id == scope.branch_id)
    active_patients = db.scalar(
        select(func.count()).select_from(
            patients_q.where(Patient.status == PatientStatus.active.value).subquery())
    ) or 0
    ayex_q = patients_q.where(Patient.status == PatientStatus.active.value,
                              Patient.affiliation == AffiliationType.ayex.value)
    due_q = ayex_q.where(Patient.ayex_expires_on < ayex_alert_before(today))
    ayex_due_total = db.scalar(select(func.count()).select_from(due_q.subquery())) or 0
    ayex_due = [
        AyexDue(patient_id=str(p.id), name=f"{p.first_name} {p.last_name}",
                expires_on=p.ayex_expires_on, expired=p.ayex_expires_on < today,
                level=ayex_level(p.ayex_expires_on, today))
        for p in db.scalars(due_q.order_by(Patient.ayex_expires_on, Patient.last_name)
                            .limit(AYEX_LIST_LIMIT))
    ]
    ayex_missing = db.scalar(select(func.count()).select_from(
        ayex_q.where(Patient.ayex_expires_on.is_(None)).subquery())) or 0

    upcoming = base.where(
        Appointment.status == AppointmentStatus.scheduled.value, Appointment.ends_at > now
    ).order_by(Appointment.starts_at)
    next_rows = _appointment_rows(db, user, upcoming.limit(1))
    next_appt = next_rows[0] if next_rows else None
    next_day = None
    next_day_others: list[AppointmentOut] = []
    if next_appt:
        # El resto de los turnos del MISMO día que la próxima sesión (sea hoy o más adelante).
        next_day = next_appt.starts_at.astimezone(tz).date()
        day_end = datetime.combine(next_day + timedelta(days=1), time(0), tzinfo=tz)
        same_day = _appointment_rows(db, user, upcoming.where(Appointment.starts_at < day_end).limit(30))
        next_day_others = [a for a in same_day if a.id != next_appt.id]

    return DashboardOut(
        scope=scope.scope,
        branch_name=scope.branch_name,
        today=today,
        month=month,
        active_patients=active_patients,
        ayex_due=ayex_due,
        ayex_due_total=ayex_due_total,
        ayex_missing=ayex_missing,
        next_appointment=next_appt,
        next_day=next_day,
        next_day_others=next_day_others,
    )
