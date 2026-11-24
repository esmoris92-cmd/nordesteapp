"""Plan de tratamiento: objetivos y avances. Solo profesionales con acceso; nada se
reescribe ni se borra (también lo impide la base); auditoría sin textos clínicos."""

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from app.models import AuditEvent, GoalUpdate, TreatmentGoal


def _goal(client, world, **extra):
    r = client.post(f"/api/patients/{world.patient_a.id}/goals", json={
        "area": "Lenguaje", "description": "Ampliar vocabulario expresivo (objetivo ficticio)", **extra})
    assert r.status_code == 201, r.text
    return r.json()


def test_professionals_who_attend_can_create_and_update(world, login):
    lucia = login(world.lucia)
    goal = _goal(lucia, world, target_date="2027-03-31")
    assert goal["status"] == "active" and goal["progress"] == 0 and goal["created_by_name"] == "Lucia"

    mateo = login(world.mateo)
    assert mateo.get(f"/api/patients/{world.patient_a.id}/goals").status_code == 404  # sin acceso
    login(world.admin_a).post(f"/api/patients/{world.patient_a.id}/access",
                              json={"professional_id": str(world.mateo.id), "level": "collaborator"})
    _goal(mateo, world, area="Motricidad fina", description="Recortar con tijera (ficticio)")
    r = mateo.post(f"/api/goals/{goal['id']}/updates",
                   json={"note": "Mejora en sesión conjunta", "progress": 30, "session_date": "2026-09-15"})
    assert r.status_code == 201 and r.json()["progress"] == 30
    goals = lucia.get(f"/api/patients/{world.patient_a.id}/goals").json()
    assert [g["area"] for g in goals] == ["Lenguaje", "Motricidad fina"]
    assert goals[0]["updates"][0]["author_name"] == "Mateo"

    for staff in (world.admin_a, world.reception_a):
        client = login(staff)
        assert client.get(f"/api/patients/{world.patient_a.id}/goals").status_code == 403
        assert client.post(f"/api/goals/{goal['id']}/updates", json={"note": "x"}).status_code == 403
    assert login(world.bruno).get(f"/api/patients/{world.patient_a.id}/goals").status_code == 404


def test_progress_status_and_reopen(world, login):
    lucia = login(world.lucia)
    goal = _goal(lucia, world)
    url = f"/api/goals/{goal['id']}/updates"
    assert lucia.post(url, json={"note": "Avance", "progress": 40}).json()["progress"] == 40
    # Sin porcentaje, mantiene el anterior.
    assert lucia.post(url, json={"note": "Sin cambios"}).json()["progress"] == 40
    done = lucia.post(url, json={"note": "Logrado en la evaluación", "new_status": "achieved"}).json()
    assert done["status"] == "achieved" and done["progress"] == 100
    assert [u["new_status"] for u in done["updates"]][:1] == ["achieved"]  # el más reciente primero
    # Cerrado: no se registran avances sin reabrirlo.
    r = lucia.post(url, json={"note": "Otro", "progress": 90})
    assert r.status_code == 409
    r = lucia.post(url, json={"note": "Retroceso, se retoma", "progress": 70, "new_status": "active"})
    assert r.status_code == 201 and r.json()["status"] == "active"
    assert len(r.json()["updates"]) == 4


def test_validation(world, login):
    lucia = login(world.lucia)
    goal = _goal(lucia, world)
    url = f"/api/goals/{goal['id']}/updates"
    assert lucia.post(url, json={"note": "x", "progress": 150}).status_code == 422
    assert lucia.post(url, json={"note": "x", "session_date": "2999-01-01"}).status_code == 422
    assert lucia.post(url, json={"note": ""}).status_code == 422
    r = lucia.post(f"/api/patients/{world.patient_a.id}/goals", json={"area": "", "description": "ok ok"})
    assert r.status_code == 422


def test_database_prevents_rewriting_or_deleting(world, login, db):
    lucia = login(world.lucia)
    goal = _goal(lucia, world)
    lucia.post(f"/api/goals/{goal['id']}/updates", json={"note": "Nota ficticia secreta", "progress": 10})
    for sql in (
        "UPDATE treatment_goals SET description = 'otra cosa'",
        "DELETE FROM treatment_goals",
        "UPDATE goal_updates SET note = 'cambiada'",
        "DELETE FROM goal_updates",
    ):
        with pytest.raises(DBAPIError):
            db.execute(text(sql))
        db.rollback()
    assert db.scalar(select(TreatmentGoal.description)).startswith("Ampliar")
    assert db.scalar(select(GoalUpdate.note)) == "Nota ficticia secreta"
    # La auditoría no copia textos clínicos.
    for details in db.scalars(select(AuditEvent.details)).all():
        assert "secreta" not in str(details) and "vocabulario" not in str(details)
