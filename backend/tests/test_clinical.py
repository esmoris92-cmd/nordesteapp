"""Historia clínica de solo-agregar, correcciones trazables e informes."""

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from app.models import AuditEvent

SECRET_TEXT = "Texto clínico ficticio que no debe aparecer en la auditoría"


def test_note_correction_keeps_original(world, login):
    lucia = login(world.lucia)
    pid = world.patient_a.id
    original = lucia.post(f"/api/patients/{pid}/notes",
                          json={"kind": "session", "session_date": "2026-01-10",
                                "content": "Versión original"}).json()
    r = lucia.post(f"/api/notes/{original['id']}/corrections",
                   json={"content": "Versión corregida", "reason": "Error de tipeo"})
    assert r.status_code == 201, r.text
    correction = r.json()
    assert correction["supersedes_id"] == original["id"]
    assert correction["correction_reason"] == "Error de tipeo"

    notes = {n["id"]: n for n in lucia.get(f"/api/patients/{pid}/notes").json()}
    assert notes[original["id"]]["content"] == "Versión original"  # no se perdió
    assert notes[original["id"]]["superseded_by_id"] == correction["id"]

    # No se puede corregir dos veces la misma versión.
    r = lucia.post(f"/api/notes/{original['id']}/corrections",
                   json={"content": "Otra", "reason": "Otro motivo"})
    assert r.status_code == 409


def test_only_author_can_correct(world, login):
    lucia = login(world.lucia)
    pid = world.patient_a.id
    note = lucia.post(f"/api/patients/{pid}/notes", json={"kind": "progress", "content": "x"}).json()
    lucia.post(f"/api/patients/{pid}/access",
               json={"professional_id": str(world.mateo.id), "level": "collaborator"})
    r = login(world.mateo).post(f"/api/notes/{note['id']}/corrections",
                                json={"content": "y", "reason": "No soy autor"})
    assert r.status_code == 403
    r = login(world.bruno).post(f"/api/notes/{note['id']}/corrections",
                                json={"content": "y", "reason": "Otra clínica"})
    assert r.status_code == 404


def test_database_forbids_editing_or_deleting_notes_and_audit(world, login, db):
    login(world.lucia).post(f"/api/patients/{world.patient_a.id}/notes",
                            json={"kind": "session", "content": "x"})
    for statement in (
        "UPDATE clinical_notes SET content = 'alterado'",
        "DELETE FROM clinical_notes",
        "UPDATE audit_log SET action = 'otra'",
        "DELETE FROM audit_log",
    ):
        with pytest.raises(DBAPIError):
            db.execute(text(statement))
        db.rollback()


def test_audit_does_not_store_clinical_content(world, login, db):
    lucia = login(world.lucia)
    pid = world.patient_a.id
    lucia.post(f"/api/patients/{pid}/notes", json={"kind": "session", "content": SECRET_TEXT})
    rep = lucia.post(f"/api/patients/{pid}/reports",
                     json={"title": "Informe X", "content": SECRET_TEXT}).json()
    lucia.patch(f"/api/reports/{rep['id']}", json={"content": SECRET_TEXT + " (v2)"})
    for details in db.scalars(select(AuditEvent.details)).all():
        assert SECRET_TEXT not in str(details)


def test_validation_errors_do_not_echo_input(world, login):
    r = login(world.lucia).post(f"/api/patients/{world.patient_a.id}/notes",
                                json={"kind": "inventado", "content": SECRET_TEXT})
    assert r.status_code == 422
    assert SECRET_TEXT not in r.text


def test_report_lifecycle(world, login, db):
    lucia = login(world.lucia)
    pid = world.patient_a.id
    r = lucia.post(f"/api/patients/{pid}/reports",
                   json={"title": "Informe inicial", "content": "Borrador ficticio"})
    assert r.status_code == 201
    rid = r.json()["id"]
    assert r.json()["status"] == "draft"

    r = lucia.patch(f"/api/reports/{rid}", json={"content": "Borrador revisado"})
    assert r.status_code == 200 and r.json()["content"] == "Borrador revisado"

    lucia.post(f"/api/patients/{pid}/access",
               json={"professional_id": str(world.mateo.id), "level": "collaborator"})
    mateo = login(world.mateo)
    assert mateo.get(f"/api/reports/{rid}").status_code == 200
    assert mateo.patch(f"/api/reports/{rid}", json={"title": "Cambio ajeno"}).status_code == 403

    r = lucia.post(f"/api/reports/{rid}/finalize")
    assert r.status_code == 200 and r.json()["status"] == "final"
    assert lucia.patch(f"/api/reports/{rid}", json={"title": "Tarde"}).status_code == 409

    summaries = lucia.get(f"/api/patients/{pid}/reports").json()
    assert summaries[0]["id"] == rid and "content" not in summaries[0]

    with pytest.raises(DBAPIError):
        db.execute(text("UPDATE reports SET title = 'alterado' WHERE status = 'final'"))
    db.rollback()

    assert login(world.admin_a).get(f"/api/reports/{rid}").status_code == 200  # finalizado: solo lectura
    assert login(world.bruno).get(f"/api/reports/{rid}").status_code == 404
