"""Varios profesionales con un mismo paciente: el responsable y sus colaboradores.
Recepción los ve en el listado y en la ficha, y el error al dar turno explica qué hacer."""

from datetime import date, timedelta
from tests.conftest import workday

DAY = workday().isoformat()
SLOT = {"starts_at": f"{DAY}T10:00:00-03:00", "ends_at": f"{DAY}T10:50:00-03:00"}


def test_collaborator_can_be_booked_and_is_listed(world, login):
    rec = login(world.reception_a)
    ana = str(world.patient_a.id)  # responsable: Lucía
    r = rec.post("/api/appointments", json={"patient_id": ana, "professional_id": str(world.mateo.id), **SLOT})
    assert r.status_code == 409 and "colaborador" in r.json()["detail"] and "Accesos" in r.json()["detail"]
    # Recepción no puede agregar colaboradores; la responsable sí.
    grant = {"professional_id": str(world.mateo.id), "level": "collaborator", "reason": "Abordaje (prueba)"}
    assert rec.post(f"/api/patients/{ana}/access", json=grant).status_code == 403
    assert login(world.lucia).post(f"/api/patients/{ana}/access", json=grant).status_code in (200, 201)
    item = next(p for p in rec.get("/api/patients").json() if p["id"] == ana)
    assert item["responsible_name"] == world.lucia.full_name
    assert item["collaborator_names"] == [world.mateo.full_name]
    assert rec.get(f"/api/patients/{ana}").json()["collaborator_names"] == [world.mateo.full_name]
    r = rec.post("/api/appointments", json={"patient_id": ana, "professional_id": str(world.mateo.id), **SLOT})
    assert r.status_code == 201, r.text
