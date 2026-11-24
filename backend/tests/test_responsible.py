"""Cambio de profesional responsable y reasignación obligatoria al eliminar una cuenta."""

from sqlalchemy import select

from app.models import AuditEvent, PatientAccess
from tests.conftest import new_id


def _reassign(world, prof):
    return {"reassignments": [{"patient_id": str(world.patient_a.id), "professional_id": str(prof.id)}]}


def _active(db, patient_id):
    db.expire_all()
    return db.scalars(select(PatientAccess).where(
        PatientAccess.patient_id == patient_id, PatientAccess.revoked_at.is_(None))).all()


def test_archive_requires_new_responsible_for_each_patient(world, login, db):
    admin = login(world.admin_a)
    pending = admin.get(f"/api/users/{world.lucia.id}/responsible-patients").json()
    assert [p["full_name"] for p in pending] == ["Ana Prueba"]

    r = admin.post(f"/api/users/{world.lucia.id}/archive")
    assert r.status_code == 409 and "1 paciente" in r.json()["detail"]
    # No se eliminó nada: Lucía sigue activa y responsable.
    assert login(world.lucia).get("/api/auth/me").status_code == 200
    assert admin.get(f"/api/patients/{world.patient_a.id}").json()["responsible_name"] == "Lucia"


def test_archive_rejects_invalid_reassignments(world, login, db):
    admin = login(world.admin_a)
    url = f"/api/users/{world.lucia.id}/archive"
    # La misma cuenta que se elimina.
    assert admin.post(url, json=_reassign(world, world.lucia)).status_code == 409
    # Profesional de otra clínica.
    assert admin.post(url, json=_reassign(world, world.bruno)).status_code == 404
    # Un paciente que no es suyo (o inexistente).
    bad = {"reassignments": [{"patient_id": new_id(), "professional_id": str(world.mateo.id)}]}
    assert admin.post(url, json=bad).status_code == 409
    # Paciente repetido.
    dup = {"reassignments": _reassign(world, world.mateo)["reassignments"] * 2}
    assert admin.post(url, json=dup).status_code == 422
    assert {a.user_id for a in _active(db, world.patient_a.id)} == {world.lucia.id}


def test_archive_with_reassignment_moves_patient(world, login, db):
    admin = login(world.admin_a)
    r = admin.post(f"/api/users/{world.lucia.id}/archive", json=_reassign(world, world.mateo))
    assert r.status_code == 200, r.text

    active = _active(db, world.patient_a.id)
    assert [(a.user_id, a.level) for a in active] == [(world.mateo.id, "responsible")]
    old = db.scalar(select(PatientAccess).where(PatientAccess.user_id == world.lucia.id))
    assert old.revoked_at is not None and old.revoke_reason.startswith("Reasignado")
    assert admin.get(f"/api/patients/{world.patient_a.id}").json()["responsible_name"] == "Mateo"
    # Mateo ahora ve la historia clínica.
    assert login(world.mateo).get(f"/api/patients/{world.patient_a.id}/notes").status_code == 200
    events = db.scalars(select(AuditEvent).where(AuditEvent.action.in_(["access.transfer", "user.archive"]))).all()
    assert {e.action for e in events} == {"access.transfer", "user.archive"}


def test_change_responsible_in_one_step(world, login, db):
    admin = login(world.admin_a)
    url = f"/api/patients/{world.patient_a.id}/responsible"
    body = {"professional_id": str(world.mateo.id), "reason": "Cambio de turno de la profesional"}
    # Mateo era colaborador: pasa a responsable sin quedar con dos accesos.
    admin.post(f"/api/patients/{world.patient_a.id}/access",
               json={"professional_id": str(world.mateo.id), "level": "collaborator"})

    # Solo administración.
    assert login(world.lucia).post(url, json=body).status_code == 403
    assert login(world.reception_a).post(url, json=body).status_code == 403

    r = admin.post(url, json=body)
    assert r.status_code == 200, r.text
    assert r.json()["level"] == "responsible" and r.json()["user_name"] == "Mateo"
    assert [(a.user_id, a.level) for a in _active(db, world.patient_a.id)] == [(world.mateo.id, "responsible")]
    history = admin.get(f"/api/patients/{world.patient_a.id}/access").json()
    lucia_row = next(h for h in history if h["user_name"] == "Lucia")
    assert lucia_row["revoke_reason"] == "Cambio de turno de la profesional"
    # Otra vez el mismo: conflicto. Motivo obligatorio.
    assert admin.post(url, json=body).status_code == 409
    assert admin.post(url, json={"professional_id": str(world.lucia.id)}).status_code == 422
    # Otra clínica no puede.
    assert login(world.admin_b).post(url, json=body).status_code == 404


def test_role_change_blocked_while_responsible(world, login):
    admin = login(world.admin_a)
    r = admin.patch(f"/api/users/{world.lucia.id}", json={"role": "reception"})
    assert r.status_code == 409 and "responsable" in r.json()["detail"]
    admin.post(f"/api/patients/{world.patient_a.id}/responsible",
               json={"professional_id": str(world.mateo.id), "reason": "Pasa a recepción"})
    assert admin.patch(f"/api/users/{world.lucia.id}", json={"role": "reception"}).status_code == 200


def test_responsible_name_warns_when_account_not_in_use(world, login):
    admin = login(world.admin_a)
    admin.patch(f"/api/users/{world.lucia.id}", json={"is_active": False})
    name = admin.get(f"/api/patients/{world.patient_a.id}").json()["responsible_name"]
    assert name == "Lucia (cuenta desactivada)"


def test_reception_assigns_only_when_missing(world, login, db):
    reception = login(world.reception_a)
    new = reception.post("/api/patients", json={
        "first_name": "Sin", "last_name": "Responsable", "affiliation": "private"}).json()
    listed = {p["id"]: p for p in reception.get("/api/patients").json()}
    assert listed[new["id"]]["responsible_id"] is None
    assert listed[str(world.patient_a.id)]["responsible_id"] == str(world.lucia.id)

    # Asignar a un paciente sin responsable: recepción puede, sin motivo.
    r = reception.post(f"/api/patients/{new['id']}/responsible",
                       json={"professional_id": str(world.mateo.id)})
    assert r.status_code == 200, r.text
    assert r.json()["reason"] == "Asignación inicial"
    listed = {p["id"]: p for p in reception.get("/api/patients").json()}
    assert listed[new["id"]]["responsible_name"] == "Mateo"
    actions = db.scalars(select(AuditEvent.action).where(AuditEvent.patient_id == new["id"])).all()
    assert "access.grant" in actions

    # Cambiar uno existente: recepción no puede (aunque indique motivo).
    r = reception.post(f"/api/patients/{new['id']}/responsible",
                       json={"professional_id": str(world.lucia.id), "reason": "Prueba"})
    assert r.status_code == 403
    # Un profesional tampoco puede asignar.
    other = reception.post("/api/patients", json={
        "first_name": "Otro", "last_name": "Sin", "affiliation": "ayex", "ayex_expires_on": "2030-12-31"}).json()
    r = login(world.mateo).post(f"/api/patients/{other['id']}/responsible",
                                json={"professional_id": str(world.mateo.id)})
    assert r.status_code == 403


def test_admin_change_requires_reason_but_first_assignment_does_not(world, login):
    admin = login(world.admin_a)
    url = f"/api/patients/{world.patient_a.id}/responsible"
    r = admin.post(url, json={"professional_id": str(world.mateo.id)})
    assert r.status_code == 422 and "motivo" in r.json()["detail"]
    new = admin.post("/api/patients", json={
        "first_name": "Nuevo", "last_name": "Ficticio", "affiliation": "military"}).json()
    r = admin.post(f"/api/patients/{new['id']}/responsible", json={"professional_id": str(world.lucia.id)})
    assert r.status_code == 200
