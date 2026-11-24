"""Domingos cerrados y turnos con fecha pasada (solo del mes en curso y con confirmación).
Todo con datos ficticios."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select

from app.models import AuditEvent
from tests.conftest import workday

MVD = ZoneInfo("America/Montevideo")


def _slot(start: datetime, minutes: int = 50) -> dict:
    return {"starts_at": start.isoformat(), "ends_at": (start + timedelta(minutes=minutes)).isoformat()}


def _past_slot_this_month() -> datetime:
    """Una hora ya pasada del mes en curso, de lunes a sábado entre 8 y 19 (la disponibilidad
    de prueba es de 8 a 20). Si no hay ninguna (el 1.º del mes muy temprano), se saltea."""
    now = datetime.now(MVD)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    t = now.replace(minute=0, second=0, microsecond=0) - timedelta(hours=1)
    while t >= month_start:
        if t.weekday() != 6 and 8 <= t.hour <= 18:
            return t
        t -= timedelta(hours=1)
    pytest.skip("Todavía no pasó ninguna hora hábil en este mes.")


def _book(client, world, start, **extra):
    return client.post("/api/appointments", json={
        "patient_id": str(world.patient_a.id), "professional_id": str(world.lucia.id), **_slot(start), **extra})


def test_sundays_are_closed(world, login):
    rec = login(world.reception_a)
    r = rec.post("/api/availability", json={"professional_id": str(world.lucia.id), "weekday": 6,
                                            "start_time": "09:00", "end_time": "12:00"})
    assert r.status_code == 409 and "domingos" in r.json()["detail"]
    # Aunque haya un horario de domingo cargado de antes (las pruebas lo tienen), no hay turnos.
    sunday = workday()
    while sunday.weekday() != 6:
        sunday += timedelta(days=1)
    r = _book(rec, world, datetime(sunday.year, sunday.month, sunday.day, 10, tzinfo=MVD))
    assert r.status_code == 409 and "domingos" in r.json()["detail"]
    # Reprogramar a un domingo, tampoco.
    day = workday()
    r = _book(rec, world, datetime(day.year, day.month, day.day, 10, tzinfo=MVD))
    assert r.status_code == 201, r.text
    r = rec.post(f"/api/appointments/{r.json()['id']}/reschedule",
                 json={**_slot(datetime(sunday.year, sunday.month, sunday.day, 11, tzinfo=MVD)), "reason": "Pedido del paciente (prueba)"})
    assert r.status_code == 409 and "domingos" in r.json()["detail"]


def test_past_appointments_need_confirmation_and_stay_in_the_month(world, login, db):
    rec = login(world.reception_a)
    past = _past_slot_this_month()
    r = _book(rec, world, past)
    assert r.status_code == 409 and "Confirmá" in r.json()["detail"]
    r = _book(rec, world, past, confirm_past=True)
    assert r.status_code == 201, r.text
    event = db.scalar(select(AuditEvent).where(AuditEvent.action == "appointment.create")
                      .order_by(AuditEvent.id.desc()))
    assert event.details["past"] is True
    # Un turno futuro queda marcado como no pasado.
    day = workday()
    r = _book(rec, world, datetime(day.year, day.month, day.day, 15, tzinfo=MVD))
    assert r.status_code == 201
    event = db.scalar(select(AuditEvent).where(AuditEvent.action == "appointment.create")
                      .order_by(AuditEvent.id.desc()))
    assert event.details["past"] is False
    # Del mes anterior: no, ni confirmando.
    prev = datetime.now(MVD).replace(day=1, hour=10, minute=0, second=0, microsecond=0) - timedelta(days=3)
    if prev.weekday() == 6:
        prev -= timedelta(days=1)
    r = _book(rec, world, prev, confirm_past=True)
    assert r.status_code == 409 and "mes en curso" in r.json()["detail"]
    # Reprogramar a una fecha pasada: la misma regla.
    r = _book(rec, world, datetime(day.year, day.month, day.day, 17, tzinfo=MVD))
    appt_id = r.json()["id"]
    r = rec.post(f"/api/appointments/{appt_id}/reschedule", json={**_slot(prev), "reason": "Pedido del paciente (prueba)"})
    assert r.status_code == 409 and "mes en curso" in r.json()["detail"]
    other = past - timedelta(hours=1) if past.hour > 8 else past + timedelta(minutes=55)
    if other < datetime.now(MVD) and other.month == past.month:
        r = rec.post(f"/api/appointments/{appt_id}/reschedule", json={**_slot(other, 50), "reason": "Pedido del paciente (prueba)"})
        assert r.status_code == 409 and "Confirmá" in r.json()["detail"]
