"""Separación de datos entre clínicas.

Cada prueba intenta, desde la clínica B, ver o tocar datos de la clínica A
(y viceversa) por todos los caminos de la API. Todas deben fallar.
"""

from datetime import datetime, timezone

import pytest
from sqlalchemy.exc import IntegrityError

from app.models import Appointment, ClinicalNote, PatientAccess
from tests.conftest import new_id


def test_patient_list_only_shows_own_clinic(world, login):
    names_b = {p["first_name"] for p in login(world.admin_b).get("/api/patients").json()}
    names_a = {p["first_name"] for p in login(world.admin_a).get("/api/patients").json()}
    assert names_b == {"Beto"}
    assert names_a == {"Ana"}


def test_cannot_read_or_edit_patient_of_other_clinic(world, login):
    admin_b = login(world.admin_b)
    pid = world.patient_a.id
    assert admin_b.get(f"/api/patients/{pid}").status_code == 404
    assert admin_b.patch(f"/api/patients/{pid}", json={"first_name": "Hack"}).status_code == 404
    assert admin_b.get(f"/api/patients/{pid}/access").status_code == 404
    bruno = login(world.bruno)
    assert bruno.get(f"/api/patients/{pid}/notes").status_code == 404
    assert bruno.post(f"/api/patients/{pid}/notes",
                      json={"kind": "session", "content": "x"}).status_code == 404
    assert bruno.get(f"/api/patients/{pid}/reports").status_code == 404


def test_cannot_grant_access_across_clinics(world, login):
    # Admin A intenta dar acceso a un profesional de B sobre un paciente de A.
    r = login(world.admin_a).post(f"/api/patients/{world.patient_a.id}/access",
                                  json={"professional_id": str(world.bruno.id),
                                        "level": "collaborator"})
    assert r.status_code == 404
    # Admin B intenta darse acceso a un paciente de A.
    r = login(world.admin_b).post(f"/api/patients/{world.patient_a.id}/access",
                                  json={"professional_id": str(world.bruno.id),
                                        "level": "collaborator"})
    assert r.status_code == 404


def test_cannot_book_appointment_with_other_clinic_data(world, login):
    admin_b = login(world.admin_b)
    r = admin_b.post("/api/appointments", json={
        "patient_id": str(world.patient_a.id), "professional_id": str(world.bruno.id),
        "starts_at": "2030-01-07T10:00:00-03:00", "ends_at": "2030-01-07T10:50:00-03:00",
    })
    assert r.status_code == 404
    r = admin_b.post("/api/appointments", json={
        "patient_id": str(world.patient_b.id), "professional_id": str(world.lucia.id),
        "starts_at": "2030-01-07T10:00:00-03:00", "ends_at": "2030-01-07T10:50:00-03:00",
    })
    assert r.status_code == 404


def test_cannot_see_users_or_agenda_of_other_clinic(world, login):
    admin_b = login(world.admin_b)
    emails = {u["email"] for u in admin_b.get("/api/users").json()}
    assert emails == {"admin@b.test", "bruno@b.test"}
    assert admin_b.patch(f"/api/users/{world.lucia.id}", json={"is_active": False}).status_code == 404
    profs = {p["full_name"] for p in admin_b.get("/api/professionals").json()}
    assert profs == {"Bruno"}
    r = admin_b.get("/api/availability", params={"professional_id": str(world.lucia.id)})
    assert r.json() == []


def test_audit_log_is_per_clinic(world, login):
    login(world.lucia).get(f"/api/patients/{world.patient_a.id}")
    events_b = login(world.admin_b).get("/api/audit").json()
    assert all(e["patient_id"] != str(world.patient_a.id) for e in events_b)
    assert all(e["actor_name"] in (None, "Admin", "Bruno") for e in events_b)


def test_unknown_ids_return_404(world, login):
    admin_a = login(world.admin_a)
    assert admin_a.get(f"/api/patients/{new_id()}").status_code == 404
    assert admin_a.get("/api/patients/no-es-un-uuid").status_code == 422


def test_database_rejects_cross_clinic_references(world, db):
    """Aunque el código fallara, la base no acepta mezclar clínicas."""
    db.add(ClinicalNote(clinic_id=world.clinic_b.id, patient_id=world.patient_a.id,
                        author_id=world.bruno.id, kind="session", content="x"))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()

    db.add(PatientAccess(clinic_id=world.clinic_a.id, patient_id=world.patient_a.id,
                         user_id=world.bruno.id, level="collaborator", granted_by=world.admin_a.id))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()

    db.add(Appointment(clinic_id=world.clinic_a.id, patient_id=world.patient_b.id,
                       professional_id=world.lucia.id, created_by=world.admin_a.id,
                       branch_id=world.branch_a.id,
                       starts_at=datetime(2030, 1, 1, 13, tzinfo=timezone.utc),
                       ends_at=datetime(2030, 1, 1, 14, tzinfo=timezone.utc)))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()
