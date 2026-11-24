"""Pulido de Profesional: correcciones de notas, fechas con la zona de la clínica y objetivos
logrados al 100 %."""

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from fastapi import HTTPException

from app.clinic_time import check_not_future, clinic_today
from app.models import Clinic


def _note(client, world, **extra):
    r = client.post(f"/api/patients/{world.patient_a.id}/notes",
                    json={"kind": "session", "session_date": "2026-01-10",
                          "content": "Nota ficticia.", **extra})
    assert r.status_code == 201, r.text
    return r.json()


def test_identical_correction_is_rejected(world, login):
    lucia = login(world.lucia)
    note = _note(lucia, world)
    r = lucia.post(f"/api/notes/{note['id']}/corrections",
                   json={"content": "  Nota ficticia.  ", "reason": "sin cambios"})
    assert r.status_code == 422 and "no cambia nada" in r.json()["detail"]


def test_correction_can_fix_only_the_date(world, login):
    lucia = login(world.lucia)
    note = _note(lucia, world)
    r = lucia.post(f"/api/notes/{note['id']}/corrections",
                   json={"content": "Nota ficticia.", "reason": "fecha equivocada",
                         "session_date": "2026-01-11"})
    assert r.status_code == 201, r.text
    assert r.json()["session_date"] == "2026-01-11"
    # Sin mandar fecha, la corrección conserva la de la versión anterior.
    r = lucia.post(f"/api/notes/{r.json()['id']}/corrections",
                   json={"content": "Nota ficticia corregida.", "reason": "agrego detalle"})
    assert r.status_code == 201 and r.json()["session_date"] == "2026-01-11"


def test_future_dates_are_rejected(world, login):
    lucia = login(world.lucia)
    tomorrow = (date.today() + timedelta(days=2)).isoformat()
    r = lucia.post(f"/api/patients/{world.patient_a.id}/notes",
                   json={"kind": "session", "session_date": tomorrow, "content": "x"})
    assert r.status_code == 422
    note = _note(lucia, world)
    r = lucia.post(f"/api/notes/{note['id']}/corrections",
                   json={"content": "otra", "reason": "fecha", "session_date": tomorrow})
    assert r.status_code == 422


@pytest.mark.parametrize("tz", ["Pacific/Kiritimati", "America/Montevideo", "Pacific/Pago_Pago"])
def test_clinic_today_uses_clinic_timezone(world, db, tz):
    clinic = db.get(Clinic, world.clinic_a.id)
    clinic.timezone = tz
    db.commit()
    today = clinic_today(db, clinic.id)
    assert today == datetime.now(ZoneInfo(tz)).date()
    check_not_future(db, clinic.id, today)  # hoy en la clínica: válido
    with pytest.raises(HTTPException):
        check_not_future(db, clinic.id, today + timedelta(days=1))


def test_achieved_goal_is_always_100(world, login):
    lucia = login(world.lucia)
    r = lucia.post(f"/api/patients/{world.patient_a.id}/goals",
                   json={"area": "Lenguaje", "description": "Objetivo ficticio."})
    assert r.status_code == 201, r.text
    goal = r.json()
    r = lucia.post(f"/api/goals/{goal['id']}/updates",
                   json={"note": "Logrado.", "progress": 40, "new_status": "achieved"})
    assert r.status_code == 201, r.text
    assert r.json()["status"] == "achieved" and r.json()["progress"] == 100


def test_session_info_has_expiry(world, login):
    """La sesión informa cuándo se cierra, para avisar antes y no perder lo escrito."""
    me = login(world.lucia).get("/api/auth/me").json()
    assert me["idle_minutes"] == 60
    assert me["expires_at"] is not None
