"""Agenda por sucursal: horarios y turnos por sucursal, AYEX y militar solo en la suya,
un profesional nunca en dos sucursales a la vez y la agenda filtrada por la sucursal activa."""

from datetime import date, datetime, timedelta

from sqlalchemy import delete

from app.models import Appointment, Availability
from tests.test_patient_branches import _client
from tests.conftest import workday

DAY = workday()  # día con horario de Lucía en Pando
OTHER = workday(after=DAY)  # día con horario de Lucía en Central


def _slot(day, hour):
    d = day.isoformat()
    return {"starts_at": f"{d}T{hour:02d}:00:00-03:00", "ends_at": f"{d}T{hour:02d}:50:00-03:00"}


def _setup(world, login, db):
    """Central y Pando. Lucía trabaja en ambas: el día DAY en Pando, el resto en Central.
    Pacientes de Pando (con Lucía responsable): Pía (privada) y Ramón (AYEX)."""
    admin = login(world.admin_a)
    central = str(world.branch_a.id)
    pando = admin.post("/api/branches", json={"name": "Pando"}).json()["id"]
    r = admin.patch(f"/api/users/{world.lucia.id}", json={"branch_ids": [central, pando]})
    assert r.status_code == 200, r.text
    db.execute(delete(Availability).where(Availability.professional_id == world.lucia.id,
                                          Availability.weekday == DAY.weekday()))
    db.commit()
    admin_p = _client("admin@a.test", pando)
    r = admin_p.post("/api/availability", json={"professional_id": str(world.lucia.id),
                                                 "weekday": DAY.weekday(),
                                                 "start_time": "09:00", "end_time": "13:00"})
    assert r.status_code == 201 and r.json()["branch_name"] == "Pando", r.text
    ids = {}
    for first, aff in (("Pia", "private"), ("Ramon", "ayex")):
        r = admin_p.post("/api/patients", json={"first_name": first, "last_name": "Pando", "affiliation": aff, "ayex_expires_on": "2030-12-31",
                                                "responsible_professional_id": str(world.lucia.id)})
        assert r.status_code == 201, r.text
        ids[first] = r.json()["id"]
    admin_c = _client("admin@a.test", central)
    return central, pando, admin_c, admin_p, ids


def _book(client, patient_id, prof, day, hour):
    return client.post("/api/appointments", json={
        "patient_id": str(patient_id), "professional_id": str(prof.id), **_slot(day, hour)})


def test_availability_per_branch(world, login, db):
    central, pando, admin_c, admin_p, _ = _setup(world, login, db)
    # Mateo no trabaja en Pando.
    r = admin_p.post("/api/availability", json={"professional_id": str(world.mateo.id), "weekday": 0,
                                                 "start_time": "09:00", "end_time": "10:00"})
    assert r.status_code == 409 and "no trabaja en la sucursal Pando" in r.json()["detail"]
    # Lucía no puede estar en Pando a la hora en que está en Central.
    r = admin_p.post("/api/availability", json={"professional_id": str(world.lucia.id),
                                                 "weekday": OTHER.weekday(),
                                                 "start_time": "09:00", "end_time": "10:00"})
    assert r.status_code == 409
    assert "se superpone con " in r.json()["detail"] and "08:00–20:00 en la sucursal Central" in r.json()["detail"]
    blocks = admin_c.get("/api/availability", params={"professional_id": str(world.lucia.id)}).json()
    assert {b["branch_name"] for b in blocks} == {"Central", "Pando"}
    # Recepción de Central no toca los horarios de Pando.
    pando_block = next(b for b in blocks if b["branch_name"] == "Pando")
    assert login(world.reception_a).delete(f"/api/availability/{pando_block['id']}").status_code == 403
    # Administración sí puede quitar un horario de otra sucursal sin cambiar de sucursal.
    assert admin_c.delete(f"/api/availability/{pando_block['id']}").status_code == 204


def test_appointments_follow_the_active_branch(world, login, db):
    central, pando, admin_c, admin_p, ids = _setup(world, login, db)
    ana = world.patient_a.id  # privada, de Central
    # En Central, ese día Lucía no tiene horario.
    r = _book(admin_c, ana, world.lucia, DAY, 10)
    assert r.status_code == 409 and "en la sucursal Central" in r.json()["detail"]
    # Una paciente privada se atiende en cualquier sucursal.
    r = _book(admin_p, ana, world.lucia, DAY, 10)
    assert r.status_code == 201 and r.json()["branch_name"] == "Pando", r.text
    appt_id = r.json()["id"]
    # Un paciente de AYEX, solo en su sucursal.
    r = _book(admin_c, ids["Ramon"], world.lucia, OTHER, 10)
    assert r.status_code == 409 and "solo se atiende en la sucursal Pando" in r.json()["detail"]
    assert _book(admin_p, ids["Ramon"], world.lucia, DAY, 11).status_code == 201
    # La agenda muestra la sucursal activa; la ficha del paciente, todas.
    week = {"from": f"{DAY.isoformat()}T00:00:00-03:00", "to": f"{OTHER.isoformat()}T23:59:00-03:00",
            "professional_id": str(world.lucia.id)}
    assert admin_c.get("/api/appointments", params=week).json() == []
    assert len(admin_p.get("/api/appointments", params=week).json()) == 2
    week.pop("professional_id")
    mine = admin_c.get("/api/appointments", params={**week, "patient_id": str(ana)}).json()
    assert [a["branch_name"] for a in mine] == ["Pando"]
    # Recepción de Central no gestiona turnos de Pando.
    rec = login(world.reception_a)
    r = rec.post(f"/api/appointments/{appt_id}/cancel", json={"reason": "Prueba ficticia"})
    assert r.status_code == 404


def test_professional_never_in_two_branches_at_once(world, login, db):
    central, pando, admin_c, admin_p, ids = _setup(world, login, db)
    # Turno de Lucía en Pando cargado directamente (como si viniera de antes).
    start = datetime.fromisoformat(_slot(OTHER, 10)["starts_at"])
    db.add(Appointment(clinic_id=world.clinic_a.id, patient_id=ids["Pia"], professional_id=world.lucia.id,
                       branch_id=pando, starts_at=start, ends_at=start + timedelta(minutes=50),
                       created_by=world.admin_a.id))
    db.commit()
    # Aunque Lucía atiende hasta 3 pacientes a la vez, no puede estar en Central a esa hora.
    r = _book(admin_c, world.patient_a.id, world.lucia, OTHER, 10)
    assert r.status_code == 409 and "en la sucursal Pando" in r.json()["detail"]
    assert _book(admin_c, world.patient_a.id, world.lucia, OTHER, 12).status_code == 201


def test_branch_changes_keep_the_agenda_consistent(world, login, db):
    central, pando, admin_c, admin_p, ids = _setup(world, login, db)
    ramon = _book(admin_p, ids["Ramon"], world.lucia, DAY, 10).json()["id"]
    pia = _book(admin_p, ids["Pia"], world.lucia, DAY, 11).json()["id"]
    # Ni quitarle Pando a Lucía ni desactivar Pando mientras haya turnos allí.
    r = admin_c.patch(f"/api/users/{world.lucia.id}", json={"branch_ids": [central]})
    assert r.status_code == 409 and "2 turno(s)" in r.json()["detail"]
    r = admin_c.patch(f"/api/branches/{pando}", json={"is_active": False})
    assert r.status_code == 409
    # Ramón (AYEX) pasa a Central: su turno en Pando se cancela; el de Pía (privada) sigue.
    assert admin_c.patch(f"/api/patients/{ids['Ramon']}", json={"branch_id": central}).status_code == 200
    db.expire_all()
    assert db.get(Appointment, ramon).status == "cancelled"
    assert "solo en la sucursal Central" in db.get(Appointment, ramon).cancel_reason
    assert admin_c.patch(f"/api/patients/{ids['Pia']}", json={"branch_id": central}).status_code == 200
    db.expire_all()
    assert db.get(Appointment, pia).status == "scheduled"
    # Sin turnos pendientes en Pando, se le puede quitar y sus horarios de Pando desaparecen.
    admin_p.post(f"/api/appointments/{pia}/cancel", json={"reason": "Prueba ficticia"})
    assert admin_c.patch(f"/api/users/{world.lucia.id}", json={"branch_ids": [central]}).status_code == 200
    blocks = admin_c.get("/api/availability", params={"professional_id": str(world.lucia.id)}).json()
    assert {b["branch_name"] for b in blocks} == {"Central"}


def test_branch_day_view_data(world, login, db):
    """Vista diaria: horarios y turnos de todos los profesionales de la sucursal activa."""
    central, pando, admin_c, admin_p, ids = _setup(world, login, db)
    assert _book(admin_p, ids["Pia"], world.lucia, DAY, 10).status_code == 201
    pando_blocks = admin_p.get("/api/availability").json()
    assert pando_blocks and {b["branch_name"] for b in pando_blocks} == {"Pando"}
    central_blocks = login(world.reception_a).get("/api/availability").json()
    assert {b["branch_name"] for b in central_blocks} == {"Central"}
    assert {b["professional_id"] for b in central_blocks} == {str(world.lucia.id), str(world.mateo.id)}
    day = {"from": f"{DAY.isoformat()}T00:00:00-03:00", "to": f"{DAY.isoformat()}T23:59:00-03:00"}
    assert [a["patient_name"] for a in admin_p.get("/api/appointments", params=day).json()] == ["Pia Pando"]
    assert admin_c.get("/api/appointments", params=day).json() == []
    # Un profesional también ve los horarios de todos, pero solo los de su sucursal activa.
    mateo_blocks = login(world.mateo).get("/api/availability").json()
    assert mateo_blocks and {b["branch_name"] for b in mateo_blocks} == {"Central"}
