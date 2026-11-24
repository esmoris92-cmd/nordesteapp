"""Acceso a pacientes por rol y acceso compartido autorizado / no autorizado."""

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from app.models import AuditEvent


def _note(client, patient_id, content="Nota de prueba ficticia"):
    return client.post(f"/api/patients/{patient_id}/notes",
                       json={"kind": "session", "content": content})


def test_professional_only_sees_assigned_patients(world, login):
    assert [p["first_name"] for p in login(world.lucia).get("/api/patients").json()] == ["Ana"]
    assert login(world.mateo).get("/api/patients").json() == []
    assert login(world.mateo).get(f"/api/patients/{world.patient_a.id}").status_code == 404


def test_unauthorized_professional_cannot_read_or_write_clinical_record(world, login):
    mateo = login(world.mateo)
    pid = world.patient_a.id
    assert mateo.get(f"/api/patients/{pid}/notes").status_code == 404
    assert _note(mateo, pid).status_code == 404
    assert mateo.get(f"/api/patients/{pid}/reports").status_code == 404


def test_admin_and_reception_cannot_read_clinical_record(world, login):
    pid = world.patient_a.id
    for user in (world.admin_a, world.reception_a):
        client = login(user)
        assert client.get(f"/api/patients/{pid}").status_code == 200  # datos administrativos
        assert client.get(f"/api/patients/{pid}/notes").status_code == 403
        assert _note(client, pid).status_code == 403
    # De los informes, ambos roles leen solo los finalizados
    # (test_reception_reports.py y test_admin_reports.py).


def test_shared_access_grant_and_revoke(world, login, db):
    lucia, mateo = login(world.lucia), login(world.mateo)
    pid = world.patient_a.id
    assert _note(lucia, pid).status_code == 201

    # La responsable concede acceso de colaborador a Mateo.
    r = lucia.post(f"/api/patients/{pid}/access",
                   json={"professional_id": str(world.mateo.id), "level": "collaborator",
                         "reason": "Abordaje interdisciplinario"})
    assert r.status_code == 201, r.text
    access_id = r.json()["id"]

    notes = mateo.get(f"/api/patients/{pid}/notes")
    assert notes.status_code == 200 and len(notes.json()) == 1
    assert _note(mateo, pid).status_code == 201

    # Un colaborador no puede compartir el paciente con terceros.
    r = mateo.post(f"/api/patients/{pid}/access",
                   json={"professional_id": str(world.lucia.id), "level": "collaborator"})
    assert r.status_code == 403

    # La responsable revoca; Mateo pierde el acceso de inmediato.
    r = lucia.post(f"/api/patients/{pid}/access/{access_id}/revoke",
                   json={"reason": "Fin del abordaje conjunto"})
    assert r.status_code == 204
    assert mateo.get(f"/api/patients/{pid}/notes").status_code == 404
    assert mateo.get(f"/api/patients/{pid}").status_code == 404

    # Queda la trazabilidad: quién concedió y quién retiró.
    history = login(world.admin_a).get(f"/api/patients/{pid}/access").json()
    revoked = next(h for h in history if h["id"] == access_id)
    assert revoked["granted_by_name"] == "Lucia"
    assert revoked["revoked_by_name"] == "Lucia"
    assert revoked["revoke_reason"] == "Fin del abordaje conjunto"
    actions = db.scalars(select(AuditEvent.action).where(AuditEvent.patient_id == pid)).all()
    assert "access.grant" in actions and "access.revoke" in actions
    assert "clinical_record.view" in actions


def test_only_admin_assigns_responsible(world, login):
    pid = world.patient_a.id
    r = login(world.lucia).post(f"/api/patients/{pid}/access",
                                json={"professional_id": str(world.mateo.id), "level": "responsible"})
    assert r.status_code == 403
    # Ya hay responsable: admin debe revocarlo primero.
    r = login(world.admin_a).post(f"/api/patients/{pid}/access",
                                  json={"professional_id": str(world.mateo.id), "level": "responsible"})
    assert r.status_code == 409


def test_reception_cannot_manage_access(world, login):
    rec = login(world.reception_a)
    pid = world.patient_a.id
    assert rec.get(f"/api/patients/{pid}/access").status_code == 403
    r = rec.post(f"/api/patients/{pid}/access",
                 json={"professional_id": str(world.mateo.id), "level": "collaborator"})
    assert r.status_code == 403


def test_access_rows_cannot_be_deleted(world, db):
    with pytest.raises(DBAPIError):
        db.execute(text("DELETE FROM patient_access"))
    db.rollback()


def test_patient_crud_by_reception(world, login):
    rec = login(world.reception_a)
    r = rec.post("/api/patients", json={
        "first_name": "  Nuevo ", "last_name": "Ficticio", "birth_date": "2000-01-01",
        "affiliation": "ayex", "ayex_expires_on": "2030-12-31",
        "phone": "099 123 456", "email": "NUEVO@Ejemplo.test",
        "responsible_professional_id": str(world.mateo.id),
    })
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["first_name"] == "Nuevo" and body["email"] == "nuevo@ejemplo.test"
    # Mateo, asignado como responsable, ya lo ve.
    assert login(world.mateo).get(f"/api/patients/{body['id']}").status_code == 200
    r = rec.patch(f"/api/patients/{body['id']}", json={"status": "paused"})
    assert r.json()["status"] == "paused"


def test_patient_validation_messages_in_spanish(world, login):
    r = login(world.reception_a).post("/api/patients", json={
        "first_name": "", "last_name": "X", "email": "sin-arroba", "birth_date": "2999-01-01"})
    assert r.status_code == 422
    messages = " ".join(e["message"] for e in r.json()["errors"])
    assert "correo" in messages and "futuro" in messages


def test_professional_cannot_create_patients(world, login):
    r = login(world.lucia).post("/api/patients", json={"first_name": "A", "last_name": "B"})
    assert r.status_code == 403
