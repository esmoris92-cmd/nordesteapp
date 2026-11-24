"""Turnos sueltos: al eliminar una cuenta, revocar un acceso o cambiar el responsable,
los turnos futuros de ese profesional se cancelan con motivo o pasan a otro profesional."""

from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select

from app.models import Appointment
from tests.conftest import workday

DAY = workday().isoformat()


def _slot(hour):
    return {"starts_at": f"{DAY}T{hour:02d}:00:00-03:00", "ends_at": f"{DAY}T{hour:02d}:50:00-03:00"}


def _book(client, patient_id, prof, hour):
    r = client.post("/api/appointments", json={
        "patient_id": str(patient_id), "professional_id": str(prof.id), **_slot(hour)})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _appt(db, appt_id):
    db.expire_all()
    return db.get(Appointment, appt_id)


def _reassign_ana(world, prof):
    return [{"patient_id": str(world.patient_a.id), "professional_id": str(prof.id)}]


def test_archive_requires_decision_and_moves_appointment(world, login, db):
    admin = login(world.admin_a)
    appt_id = _book(admin, world.patient_a.id, world.lucia, 10)
    # Un turno pasado no se toca.
    past = Appointment(clinic_id=world.clinic_a.id, patient_id=world.patient_a.id,
                       professional_id=world.lucia.id, created_by=world.admin_a.id,
                       branch_id=world.branch_a.id,
                       starts_at=datetime.now(timezone.utc) - timedelta(days=2),
                       ends_at=datetime.now(timezone.utc) - timedelta(days=2) + timedelta(minutes=50))
    db.add(past)
    db.commit()

    listed = admin.get(f"/api/users/{world.lucia.id}/future-appointments").json()
    assert [a["id"] for a in listed] == [appt_id]

    url = f"/api/users/{world.lucia.id}/archive"
    r = admin.post(url, json={"reassignments": _reassign_ana(world, world.mateo)})
    assert r.status_code == 409 and "1 turno" in r.json()["detail"]
    assert _appt(db, appt_id).status == "scheduled"  # no cambió nada

    r = admin.post(url, json={
        "reassignments": _reassign_ana(world, world.mateo),
        "appointments": [{"appointment_id": appt_id, "action": "move",
                          "professional_id": str(world.mateo.id)}]})
    assert r.status_code == 200, r.text
    old = _appt(db, appt_id)
    assert old.status == "rescheduled"
    assert old.reschedule_reason == "Se eliminó la cuenta del profesional: pasó a otro profesional."
    new = db.get(Appointment, old.rescheduled_to_id)
    assert new.professional_id == world.mateo.id and new.starts_at == old.starts_at
    assert new.status == "scheduled"
    assert _appt(db, past.id).status == "scheduled"


def test_archive_can_cancel_with_reason(world, login, db):
    admin = login(world.admin_a)
    appt_id = _book(admin, world.patient_a.id, world.lucia, 11)
    r = admin.post(f"/api/users/{world.lucia.id}/archive", json={
        "reassignments": _reassign_ana(world, world.mateo),
        "appointments": [{"appointment_id": appt_id, "action": "cancel"}],
        "cancel_reason": "Licencia prolongada"})
    assert r.status_code == 200, r.text
    appt = _appt(db, appt_id)
    assert appt.status == "cancelled" and appt.cancel_reason == "Licencia prolongada"


def test_move_that_does_not_fit_is_rejected_and_nothing_changes(world, login, db):
    admin = login(world.admin_a)
    reception = login(world.reception_a)
    appt_id = _book(admin, world.patient_a.id, world.lucia, 10)
    # Mateo atiende de a uno y ya tiene otro paciente a las 10.
    admin.patch(f"/api/users/{world.mateo.id}", json={"max_concurrent_patients": 1})
    other = reception.post("/api/patients", json={
        "first_name": "Otro", "last_name": "Ficticio", "affiliation": "private",
        "responsible_professional_id": str(world.mateo.id)}).json()
    _book(admin, other["id"], world.mateo, 10)

    r = admin.post(f"/api/users/{world.lucia.id}/archive", json={
        "reassignments": _reassign_ana(world, world.mateo),
        "appointments": [{"appointment_id": appt_id, "action": "move",
                          "professional_id": str(world.mateo.id)}]})
    assert r.status_code == 409 and r.json()["detail"].startswith("Turno del")
    assert _appt(db, appt_id).status == "scheduled"
    assert login(world.lucia).get("/api/auth/me").status_code == 200  # no se eliminó


def test_move_to_professional_without_access_is_rejected(world, login, db):
    admin = login(world.admin_a)
    nora = admin.post("/api/users", json={
        "full_name": "Nora Ficticia", "email": "nora@a.test", "role": "professional", "document_number": "4444444-4",
        "specialty_id": str(world.lucia.specialty_id), "password": "Clave-ficticia-2026",
        "branch_ids": [str(world.branch_a.id)]}).json()
    appt_id = _book(admin, world.patient_a.id, world.lucia, 10)
    r = admin.post(f"/api/users/{world.lucia.id}/archive", json={
        "reassignments": _reassign_ana(world, world.mateo),
        "appointments": [{"appointment_id": appt_id, "action": "move", "professional_id": nora["id"]}]})
    assert r.status_code == 409 and "no tiene asignado" in r.json()["detail"]


def test_revoking_access_cancels_that_professionals_future_appointments(world, login, db):
    admin = login(world.admin_a)
    admin.post(f"/api/patients/{world.patient_a.id}/access",
               json={"professional_id": str(world.mateo.id), "level": "collaborator"})
    mateo_appt = _book(admin, world.patient_a.id, world.mateo, 12)
    lucia_appt = _book(admin, world.patient_a.id, world.lucia, 10)

    rows = admin.get(f"/api/patients/{world.patient_a.id}/access").json()
    mateo_row = next(a for a in rows if a["user_name"] == "Mateo")
    assert mateo_row["future_appointments"] == 1
    r = admin.post(f"/api/patients/{world.patient_a.id}/access/{mateo_row['id']}/revoke",
                   json={"reason": "Fin del abordaje conjunto"})
    assert r.status_code == 204
    assert _appt(db, mateo_appt).status == "cancelled"
    assert _appt(db, mateo_appt).cancel_reason == "Fin del abordaje conjunto"
    assert _appt(db, lucia_appt).status == "scheduled"


def test_change_responsible_moves_or_cancels_appointments(world, login, db):
    admin = login(world.admin_a)
    url = f"/api/patients/{world.patient_a.id}/responsible"
    appt_id = _book(admin, world.patient_a.id, world.lucia, 10)

    r = admin.post(url, json={"professional_id": str(world.mateo.id), "reason": "Cambio ficticio"})
    assert r.status_code == 200, r.text
    moved = db.get(Appointment, _appt(db, appt_id).rescheduled_to_id)
    assert moved.professional_id == world.mateo.id

    r = admin.post(url, json={"professional_id": str(world.lucia.id), "reason": "Vuelve Lucía",
                              "move_appointments": False})
    assert r.status_code == 200, r.text
    moved = _appt(db, moved.id)
    assert moved.status == "cancelled" and moved.cancel_reason == "Vuelve Lucía"
    active = db.scalars(select(Appointment).where(Appointment.status == "scheduled")).all()
    assert active == []


def test_role_change_blocked_with_future_appointments(world, login):
    admin = login(world.admin_a)
    admin.post(f"/api/patients/{world.patient_a.id}/access",
               json={"professional_id": str(world.mateo.id), "level": "collaborator"})
    _book(admin, world.patient_a.id, world.mateo, 12)
    r = admin.patch(f"/api/users/{world.mateo.id}", json={"role": "reception"})
    assert r.status_code == 409 and "turno" in r.json()["detail"]


def test_patient_leaving_active_cancels_future_appointments(world, login, db):
    reception = login(world.reception_a)
    first = _book(reception, world.patient_a.id, world.lucia, 10)
    second = _book(reception, world.patient_a.id, world.lucia, 12)
    detail = reception.get(f"/api/patients/{world.patient_a.id}").json()
    assert detail["future_appointments"] == 2

    r = reception.patch(f"/api/patients/{world.patient_a.id}", json={"status": "discharged"})
    assert r.status_code == 200
    for appt_id in (first, second):
        appt = _appt(db, appt_id)
        assert appt.status == "cancelled" and appt.cancel_reason == "Paciente dado de alta"
    assert reception.get(f"/api/patients/{world.patient_a.id}").json()["future_appointments"] == 0
    # Otros cambios de datos no tocan la agenda.
    assert reception.patch(f"/api/patients/{world.patient_a.id}", json={"phone": "099 123 456"}).status_code == 200


def test_paused_patient_also_cancels(world, login, db):
    reception = login(world.reception_a)
    appt_id = _book(reception, world.patient_a.id, world.lucia, 9)
    reception.patch(f"/api/patients/{world.patient_a.id}", json={"status": "paused"})
    appt = _appt(db, appt_id)
    assert appt.status == "cancelled" and appt.cancel_reason == "Paciente en pausa"
