"""Responsables / tutores del paciente."""

from sqlalchemy import select

from app.models import AuditEvent

MOM = {"first_name": "Laura", "last_name": "Ficticia", "document_number": "1.234.567-8", "relationship": "Madre",
       "phone": "099 111 222",
       "email": "laura@ejemplo.test", "is_primary": True}


def _url(world):
    return f"/api/patients/{world.patient_a.id}/guardians"


def test_reception_manages_guardians(world, login, db):
    rec = login(world.reception_a)
    r = rec.post(_url(world), json=MOM)
    assert r.status_code == 201, r.text
    gid = r.json()["id"]
    dad = rec.post(_url(world), json={**MOM, "first_name": "Pedro", "last_name": "Ficticio", "relationship": "Padre"}).json()
    # Solo uno puede ser el contacto principal.
    listed = rec.get(_url(world)).json()
    assert [g["full_name"] for g in listed if g["is_primary"]] == ["Pedro Ficticio"]
    r = rec.patch(f"{_url(world)}/{gid}", json={"phone": "098 000 000", "is_primary": True})
    assert r.status_code == 200 and r.json()["phone"] == "098 000 000"
    assert rec.delete(f"{_url(world)}/{dad['id']}").status_code == 204
    assert [g["full_name"] for g in rec.get(_url(world)).json()] == ["Laura Ficticia"]
    actions = set(db.scalars(select(AuditEvent.action)).all())
    assert {"guardian.create", "guardian.update", "guardian.delete"} <= actions
    assert all("099 111" not in str(d) for d in db.scalars(select(AuditEvent.details)).all())


def test_permissions(world, login):
    rec = login(world.reception_a)
    gid = rec.post(_url(world), json=MOM).json()["id"]
    # La responsable puede editar; un colaborador o alguien sin acceso, no.
    assert login(world.lucia).post(_url(world), json=MOM).status_code == 201
    lucia = login(world.lucia)
    lucia.post(f"/api/patients/{world.patient_a.id}/access",
               json={"professional_id": str(world.mateo.id), "level": "collaborator"})
    mateo = login(world.mateo)
    assert mateo.get(_url(world)).status_code == 200  # puede verlos
    assert mateo.post(_url(world), json=MOM).status_code == 403
    assert mateo.delete(f"{_url(world)}/{gid}").status_code == 403
    assert login(world.admin_b).get(_url(world)).status_code == 404
    assert login(world.admin_b).delete(f"{_url(world)}/{gid}").status_code == 404


def test_validation(world, login):
    r = login(world.reception_a).post(_url(world), json={"first_name": "X", "last_name": "", "relationship": ""})
    assert r.status_code == 422


def test_guardian_ci_is_required(world, login, db):
    """La C.I. del responsable es obligatoria al agregarlo y al editarlo."""
    rec = login(world.reception_a)
    sin_ci = {k: v for k, v in MOM.items() if k != "document_number"}
    r = rec.post(_url(world), json=sin_ci)
    assert r.status_code == 422
    assert rec.post(_url(world), json={**MOM, "document_number": "  "}).status_code == 422
    assert rec.post(_url(world), json={**MOM, "document_number": "12<34>"}).status_code == 422
    r = rec.post(_url(world), json={**MOM, "document_number": "4.567.890-1"})
    assert r.status_code == 201 and r.json()["document_number"] == "4.567.890-1"
    gid = r.json()["id"]
    # No se puede borrar al editar.
    assert rec.patch(f"{_url(world)}/{gid}", json={"document_number": None}).status_code == 422
    assert rec.patch(f"{_url(world)}/{gid}", json={"phone": "098 000 000"}).status_code == 200

    # Un responsable cargado antes de exigirla (sin C.I.) debe completarla al editarlo.
    from app.models import PatientGuardian
    viejo = PatientGuardian(clinic_id=world.clinic_a.id, patient_id=world.patient_a.id,
                            full_name="Abuela Ficticia", relationship="Abuela",
                            created_by=world.admin_a.id)
    db.add(viejo)
    db.commit()
    listed = {g["full_name"]: g for g in rec.get(_url(world)).json()}
    assert listed["Abuela Ficticia"]["document_number"] is None
    url = f"{_url(world)}/{viejo.id}"
    r = rec.patch(url, json={"phone": "091 222 333"})
    assert r.status_code == 422 and r.json()["detail"] == "Indicá la C.I. del responsable."
    r = rec.patch(url, json={"phone": "091 222 333", "document_number": "2.345.678-9"})
    assert r.status_code == 422 and "primer nombre" in r.json()["detail"]
    r = rec.patch(url, json={"phone": "091 222 333", "document_number": "2.345.678-9",
                             "first_name": "Rosa", "last_name": "Ficticia", "second_last_name": "Pérez"})
    assert r.status_code == 200 and r.json()["document_number"] == "2.345.678-9"
    assert r.json()["full_name"] == "Rosa Ficticia Pérez"
