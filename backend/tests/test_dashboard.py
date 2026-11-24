"""Pantalla de Inicio: los números respetan permisos y no cruzan clínicas."""

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.models import Appointment

TZ = ZoneInfo("America/Montevideo")


def _appt(db, clinic, patient, prof, creator, start, minutes, status):
    db.add(Appointment(clinic_id=clinic.id, patient_id=patient.id, professional_id=prof.id,
                       branch_id=patient.branch_id, created_by=creator.id, starts_at=start,
                       ends_at=start + timedelta(minutes=minutes), status=status))


def _setup(world, db):
    today0 = datetime.combine(datetime.now(TZ).date(), time(0), tzinfo=TZ)
    a, pa = world.clinic_a, world.patient_a
    _appt(db, a, pa, world.lucia, world.reception_a, today0 + timedelta(minutes=1), 1, "completed")
    _appt(db, a, pa, world.lucia, world.reception_a, today0 + timedelta(minutes=3), 1, "no_show")
    _appt(db, a, pa, world.mateo, world.reception_a, today0 + timedelta(minutes=5), 1, "completed")
    _appt(db, a, pa, world.lucia, world.reception_a,
          datetime.now(TZ) + timedelta(hours=1), 50, "scheduled")
    _appt(db, world.clinic_b, world.patient_b, world.bruno, world.admin_b,
          today0 + timedelta(minutes=7), 1, "completed")
    # Ana pasa a AYEX con vencimiento a fin de este mes.
    today = datetime.now(TZ).date()
    world.patient_a.affiliation = "ayex"
    world.patient_a.ayex_expires_on = (today.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
    db.commit()


def test_professional_sees_only_own_numbers(world, login, db):
    _setup(world, db)
    d = login(world.lucia).get("/api/dashboard").json()
    assert d["scope"] == "own"
    assert d["month"]["completed"] == 1 and d["month"]["no_show"] == 1
    assert d["month"]["attendance_rate"] == 50
    assert d["active_patients"] == 1
    assert [a["name"] for a in d["ayex_due"]] == ["Ana Prueba"] and d["ayex_due_total"] == 1
    assert d["next_appointment"]["professional_name"] == "Lucia"

    m = login(world.mateo).get("/api/dashboard").json()
    assert m["month"]["completed"] == 1 and m["month"]["no_show"] == 0
    assert m["active_patients"] == 0 and m["ayex_due"] == []  # sin acceso a Ana
    assert m["next_appointment"] is None


def test_reception_sees_her_branch_but_not_other_clinic(world, login, db):
    _setup(world, db)
    d = login(world.reception_a).get("/api/dashboard").json()
    assert d["scope"] == "branch" and d["branch_name"] == "Central"
    assert d["month"]["completed"] == 2  # Lucía + Mateo, no el de Boreal
    assert d["month"]["attendance_rate"] == 67
    assert d["active_patients"] == 1
    b = login(world.admin_b).get("/api/dashboard").json()
    assert b["month"]["completed"] == 1 and b["active_patients"] == 1
    assert b["ayex_due"] == [] and b["ayex_missing"] == 1  # Beto (AYEX de Boreal) sin fecha


def test_empty_dashboard(world, login):
    d = login(world.admin_a).get("/api/dashboard").json()
    assert d["month"] == {"completed": 0, "scheduled": 0, "no_show": 0, "cancelled": 0,
                          "attendance_rate": None}
    assert d["next_appointment"] is None and d["next_day_others"] == [] and d["next_day"] is None


def test_dashboard_requires_session(world):
    from fastapi.testclient import TestClient
    from app.main import app
    assert TestClient(app).get("/api/dashboard").status_code == 401


def test_shows_other_appointments_of_the_next_session_day(world, login, db):
    """Si la próxima sesión es otro día (p. ej. mañana), se listan los demás turnos de ese día."""
    tomorrow = datetime.combine(datetime.now(TZ).date() + timedelta(days=1), time(0), tzinfo=TZ)
    a, pa = world.clinic_a, world.patient_a
    _appt(db, a, pa, world.lucia, world.reception_a, tomorrow + timedelta(hours=11), 50, "scheduled")
    _appt(db, a, pa, world.lucia, world.reception_a, tomorrow + timedelta(hours=12), 50, "scheduled")
    _appt(db, a, pa, world.lucia, world.reception_a, tomorrow + timedelta(days=1, hours=9), 50, "scheduled")
    db.commit()
    d = login(world.lucia).get("/api/dashboard").json()
    assert d["next_day"] == (datetime.now(TZ).date() + timedelta(days=1)).isoformat()
    assert len(d["next_day_others"]) == 1  # el de las 12:00, no el de pasado mañana
