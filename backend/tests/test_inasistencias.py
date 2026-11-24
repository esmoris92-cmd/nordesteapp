"""Listado de pacientes: inasistencias del mes en curso (se reinician cada mes)."""

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.models import Appointment

TZ = ZoneInfo("America/Montevideo")


def _appt(db, world, start, status):
    db.add(Appointment(clinic_id=world.clinic_a.id, patient_id=world.patient_a.id,
                       professional_id=world.lucia.id, branch_id=world.patient_a.branch_id,
                       created_by=world.admin_a.id, starts_at=start, ends_at=start + timedelta(minutes=1),
                       status=status))


def test_no_shows_count_only_this_month(world, login, db):
    month0 = datetime.combine(datetime.now(TZ).date().replace(day=1), time(0), tzinfo=TZ)
    _appt(db, world, month0 + timedelta(minutes=1), "no_show")
    _appt(db, world, month0 + timedelta(minutes=3), "no_show")
    _appt(db, world, month0 + timedelta(minutes=5), "completed")
    _appt(db, world, month0 + timedelta(minutes=7), "cancelled")
    _appt(db, world, month0 - timedelta(days=3), "no_show")  # mes anterior: no cuenta
    db.commit()
    rows = login(world.reception_a).get("/api/patients").json()
    assert {r["first_name"]: r["no_shows_month"] for r in rows} == {"Ana": 2}
    # La profesional con acceso ve el mismo número; un paciente sin faltas tiene 0.
    rec = login(world.reception_a)
    rec.post("/api/patients", json={"first_name": "Sin", "last_name": "Faltas", "affiliation": "private"})
    rows = {r["first_name"]: r["no_shows_month"] for r in login(world.lucia).get("/api/patients").json()}
    assert rows["Ana"] == 2
    assert {r["first_name"]: r["no_shows_month"] for r in rec.get("/api/patients").json()}["Sin"] == 0
