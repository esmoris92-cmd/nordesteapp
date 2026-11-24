"""Inicio e informe mensual por sucursal: recepción ve su sucursal, administración la
activa o todas juntas, cada profesional lo suyo en todas sus sucursales."""

import io
import zipfile
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.models import Appointment
from tests.test_agenda_branches import _setup
from tests.test_patient_branches import _client

TZ = ZoneInfo("America/Montevideo")


def _done(db, world, patient_id, branch_id, start):
    db.add(Appointment(clinic_id=world.clinic_a.id, patient_id=patient_id, professional_id=world.lucia.id,
                       branch_id=branch_id, starts_at=start, ends_at=start + timedelta(minutes=1),
                       status="completed", created_by=world.admin_a.id))


def _month_data(world, login, db):
    """Este mes: 1 sesión realizada en Central (Ana) y 2 en Pando (Pía y Ramón), todas de Lucía."""
    central, pando, admin_c, admin_p, ids = _setup(world, login, db)
    today0 = datetime.combine(datetime.now(TZ).date().replace(day=1), time(0), tzinfo=TZ)
    _done(db, world, world.patient_a.id, central, today0 + timedelta(minutes=1))
    _done(db, world, ids["Pia"], pando, today0 + timedelta(minutes=3))
    _done(db, world, ids["Ramon"], pando, today0 + timedelta(minutes=5))
    db.commit()
    return central, pando, admin_c, admin_p


def test_dashboard_by_branch(world, login, db):
    central, pando, admin_c, admin_p = _month_data(world, login, db)
    d = admin_c.get("/api/dashboard").json()
    assert (d["scope"], d["branch_name"], d["month"]["completed"]) == ("branch", "Central", 1)
    assert admin_p.get("/api/dashboard").json()["month"]["completed"] == 2
    d = admin_c.get("/api/dashboard", params={"branch": "all"}).json()
    assert (d["scope"], d["branch_name"], d["month"]["completed"]) == ("clinic", None, 3)
    assert admin_c.get("/api/dashboard", params={"branch": pando}).json()["branch_name"] == "Pando"
    # Recepción: solo su sucursal.
    rec = login(world.reception_a)
    assert rec.get("/api/dashboard").json()["month"]["completed"] == 1
    assert rec.get("/api/dashboard", params={"branch": "all"}).status_code == 403
    assert rec.get("/api/dashboard", params={"branch": pando}).status_code == 403
    # La profesional ve lo suyo en todas sus sucursales.
    d = _client("lucia@a.test", central).get("/api/dashboard").json()  # trabaja en dos: elige una
    assert (d["scope"], d["month"]["completed"]) == ("own", 3)


def test_monthly_summary_by_branch(world, login, db):
    central, pando, admin_c, admin_p = _month_data(world, login, db)
    data = admin_c.get("/api/monthly-summary").json()
    assert data["branch_name"] == "Central" and data["total"]["completed"] == 1
    data = admin_c.get("/api/monthly-summary", params={"branch": "all"}).json()
    assert data["scope"] == "clinic" and data["total"]["completed"] == 3
    assert {(b["branch_name"], b["completed"]) for b in data["by_branch"]} == {("Central", 1), ("Pando", 2)}
    assert {(r["branch_name"], r["affiliation"], r["completed"]) for r in data["rows"]} == {
        ("Central", "private", 1), ("Pando", "private", 1), ("Pando", "ayex", 1)}
    rec = login(world.reception_a)
    assert rec.get("/api/monthly-summary").json()["total"]["completed"] == 1
    assert rec.get("/api/monthly-summary", params={"branch": "all"}).status_code == 403
    assert _client("lucia@a.test", pando).get("/api/monthly-summary").json()["total"]["completed"] == 3
    # Excel de todas las sucursales: columna "Sucursal" y un total por sucursal.
    r = admin_c.get("/api/monthly-summary/export", params={"branch": "all"})
    assert r.headers["content-disposition"].endswith('-todas.xlsx"')
    with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
        sheet = zf.read("xl/worksheets/sheet1.xml").decode()
    assert "Sucursal" in sheet and "Total Pando" in sheet and "Total Central" in sheet
