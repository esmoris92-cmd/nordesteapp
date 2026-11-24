"""Varios pacientes en el mismo horario con un mismo profesional (hasta su cupo)."""

from datetime import date, timedelta

from app.models import Patient, PatientAccess
from tests.conftest import workday

DAY = workday().isoformat()


def _t(hour, minute=0):
    return f"{DAY}T{hour:02d}:{minute:02d}:00-03:00"


def _patients(world, db, n):
    """Crea n pacientes de la clínica A asignados a Lucía."""
    created = []
    for i in range(n):
        p = Patient(clinic_id=world.clinic_a.id, first_name=f"Grupo{i}", last_name="Prueba",
                    affiliation="private", created_by=world.reception_a.id,
                    branch_id=world.branch_a.id)
        db.add(p)
        db.flush()
        db.add(PatientAccess(clinic_id=world.clinic_a.id, patient_id=p.id, user_id=world.lucia.id,
                             level="responsible", granted_by=world.admin_a.id))
        created.append(p)
    db.commit()
    return created


def _book(client, world, patient, start, end):
    return client.post("/api/appointments", json={
        "patient_id": str(patient.id), "professional_id": str(world.lucia.id),
        "starts_at": start, "ends_at": end})


def test_up_to_three_patients_at_the_same_time(world, login, db):
    ps = _patients(world, db, 4)
    rec = login(world.reception_a)
    for p in ps[:3]:
        assert _book(rec, world, p, _t(10), _t(10, 50)).status_code == 201
    r = _book(rec, world, ps[3], _t(10), _t(10, 50))
    assert r.status_code == 409 and "3 pacientes" in r.json()["detail"]
    # Justo cuando terminan los anteriores, sí hay lugar.
    assert _book(rec, world, ps[3], _t(10, 50), _t(11, 40)).status_code == 201


def test_partial_overlaps_count_only_real_simultaneity(world, login, db):
    ps = _patients(world, db, 4)
    rec = login(world.reception_a)
    assert _book(rec, world, ps[0], _t(9), _t(10)).status_code == 201
    assert _book(rec, world, ps[1], _t(10), _t(11)).status_code == 201
    assert _book(rec, world, ps[2], _t(9, 30), _t(10, 30)).status_code == 201
    # 9:30-10:30 ya tiene 2 a la vez como máximo; un tercero entra.
    assert _book(rec, world, ps[3], _t(9, 45), _t(10, 15)).status_code == 201


def test_same_patient_cannot_have_two_overlapping_appointments(world, login, db):
    (p,) = _patients(world, db, 1)
    rec = login(world.reception_a)
    assert _book(rec, world, p, _t(10), _t(10, 50)).status_code == 201
    r = _book(rec, world, p, _t(10, 30), _t(11))
    assert r.status_code == 409 and "paciente" in r.json()["detail"]


def test_capacity_is_configurable_per_professional(world, login, db):
    ps = _patients(world, db, 2)
    admin = login(world.admin_a)
    r = admin.patch(f"/api/users/{world.lucia.id}", json={"max_concurrent_patients": 1})
    assert r.status_code == 200 and r.json()["max_concurrent_patients"] == 1
    rec = login(world.reception_a)
    assert _book(rec, world, ps[0], _t(10), _t(10, 50)).status_code == 201
    r = _book(rec, world, ps[1], _t(10), _t(10, 50))
    assert r.status_code == 409 and r.json()["detail"] == "El profesional ya tiene un turno en ese horario."
    assert admin.patch(f"/api/users/{world.lucia.id}",
                       json={"max_concurrent_patients": 11}).status_code == 422


def test_reschedule_respects_capacity(world, login, db):
    ps = _patients(world, db, 4)
    rec = login(world.reception_a)
    for p in ps[:3]:
        _book(rec, world, p, _t(10), _t(10, 50))
    moving = _book(rec, world, ps[3], _t(12), _t(12, 50)).json()
    r = rec.post(f"/api/appointments/{moving['id']}/reschedule",
                 json={"starts_at": _t(10), "ends_at": _t(10, 50), "reason": "Pedido del paciente (prueba)"})
    assert r.status_code == 409
