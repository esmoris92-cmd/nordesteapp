"""Informe mensual por profesional y afiliación: conteos por estado, pacientes atendidos,
límites del mes en hora de la clínica, permisos (profesional ve lo suyo) y aislamiento."""

import io
import zipfile
from datetime import datetime, timedelta, timezone

from app.models import Appointment, Patient

MVD = timezone(timedelta(hours=-3))  # hora de la clínica de prueba (Montevideo)
URL = "/api/monthly-summary"


def _appt(db, world, patient, prof, when, status, clinic=None):
    db.add(Appointment(clinic_id=(clinic or world.clinic_a).id, patient_id=patient.id,
                       professional_id=prof.id, branch_id=patient.branch_id, starts_at=when, ends_at=when + timedelta(minutes=50),
                       status=status, created_by=prof.id))


def _setup(db, world):
    rosa = Patient(clinic_id=world.clinic_a.id, first_name="Rosa", last_name="Ficticia",
                   affiliation="ayex", created_by=world.admin_a.id,
                   branch_id=world.branch_a.id)
    db.add(rosa)
    db.flush()
    d = lambda day, hour=10: datetime(2026, 9, day, hour, tzinfo=MVD)
    ana = world.patient_a  # Privado
    _appt(db, world, ana, world.lucia, d(2), "completed")
    _appt(db, world, ana, world.lucia, d(9), "completed")
    _appt(db, world, ana, world.lucia, d(16), "no_show")
    _appt(db, world, ana, world.lucia, datetime(2026, 9, 30, 23, 30, tzinfo=MVD), "completed")  # cuenta
    _appt(db, world, ana, world.lucia, datetime(2026, 10, 1, 0, 30, tzinfo=MVD), "completed")   # octubre
    _appt(db, world, ana, world.lucia, datetime(2026, 8, 31, 23, 0, tzinfo=MVD), "completed")   # agosto
    _appt(db, world, rosa, world.lucia, d(3), "completed")
    _appt(db, world, rosa, world.lucia, d(10), "cancelled")
    _appt(db, world, rosa, world.mateo, d(4), "completed")
    _appt(db, world, rosa, world.mateo, d(11), "rescheduled")  # no se cuenta
    _appt(db, world, world.patient_b, world.bruno, d(5), "completed", clinic=world.clinic_b)
    db.commit()


def test_counts_by_professional_and_affiliation(world, login, db):
    _setup(db, world)
    data = login(world.reception_a).get(URL, params={"month": "2026-09"}).json()
    rows = {(r["professional_name"], r["affiliation"]): r for r in data["rows"]}
    assert set(rows) == {("Lucia", "private"), ("Lucia", "ayex"), ("Mateo", "ayex")}  # sin Bruno
    lucia_private = rows[("Lucia", "private")]
    assert (lucia_private["completed"], lucia_private["no_show"], lucia_private["patients_seen"]) == (3, 1, 1)
    assert (rows[("Lucia", "ayex")]["completed"], rows[("Lucia", "ayex")]["cancelled"]) == (1, 1)
    assert rows[("Mateo", "ayex")]["completed"] == 1
    assert data["by_affiliation"]["ayex"] == {"completed": 2, "no_show": 0, "cancelled": 1,
                                              "scheduled": 0, "patients_seen": 1}
    assert data["by_affiliation"]["military"]["completed"] == 0
    assert data["total"]["completed"] == 5 and data["total"]["patients_seen"] == 2
    assert data["only_own"] is False


def test_professional_sees_only_own_and_validation(world, login, db):
    _setup(db, world)
    data = login(world.mateo).get(URL, params={"month": "2026-09"}).json()
    assert data["only_own"] is True
    assert [(r["professional_name"], r["completed"]) for r in data["rows"]] == [("Mateo", 1)]
    assert data["total"]["completed"] == 1
    admin = login(world.admin_a)
    assert admin.get(URL, params={"month": "2026-13"}).status_code == 422
    assert admin.get(URL, params={"month": "septiembre"}).status_code == 422
    assert admin.get(URL).status_code == 200  # sin mes: el actual


def test_export_to_excel(world, login, db):
    _setup(db, world)
    r = login(world.admin_a).get(f"{URL}/export", params={"month": "2026-09"})
    assert r.status_code == 200
    assert r.headers["content-disposition"] == 'attachment; filename="lumen-informe-2026-09-central.xlsx"'
    with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
        sheet = zf.read("xl/worksheets/sheet1.xml").decode()
    assert "TOTAL" in sheet and "Tutela Militar" in sheet and "Ana" not in sheet  # sin nombres de pacientes
