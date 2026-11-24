"""Especialidades editables por Administración (p. ej. Fonoaudiología)."""

from sqlalchemy import select

from app.models import AuditEvent


def _create(client, name):
    return client.post("/api/specialties", json={"name": name})


def test_admin_creates_specialty_and_assigns_it(world, login):
    admin = login(world.admin_a)
    r = _create(admin, "  Fonoaudiología ")
    assert r.status_code == 201, r.text
    fono = r.json()
    assert fono["name"] == "Fonoaudiología" and fono["is_active"] is True

    r = admin.post("/api/users", json={
        "email": "camila@a.test", "full_name": "Lic. Camila Prueba", "role": "professional", "document_number": "3333333-3",
        "specialty_id": fono["id"], "password": "contraseña-de-prueba-123",
        "branch_ids": [str(world.branch_a.id)],
    })
    assert r.status_code == 201, r.text
    assert r.json()["specialty_name"] == "Fonoaudiología"

    # Aparece en la lista de profesionales que usan agenda y accesos.
    profs = {p["full_name"]: p["specialty_name"] for p in admin.get("/api/professionals").json()}
    assert profs["Lic. Camila Prueba"] == "Fonoaudiología"

    counts = {s["name"]: s["professional_count"] for s in admin.get("/api/specialties").json()}
    assert counts["Fonoaudiología"] == 1


def test_duplicate_name_is_rejected_ignoring_case(world, login):
    admin = login(world.admin_a)
    assert _create(admin, "psicología").status_code == 409
    # Otra clínica puede tener su propia "Fonoaudiología".
    assert _create(admin, "Fonoaudiología").status_code == 201
    assert _create(login(world.admin_b), "Fonoaudiología").status_code == 201


def test_only_admin_manages_specialties(world, login):
    for user in (world.reception_a, world.lucia):
        client = login(user)
        assert _create(client, "Psicopedagogía").status_code == 403
        assert client.get("/api/specialties").status_code == 200  # puede ver la lista


def test_deactivated_specialty_cannot_be_assigned_but_is_kept(world, login, db):
    admin = login(world.admin_a)
    specialties = {s["name"]: s for s in admin.get("/api/specialties").json()}
    psy = specialties["Psicología"]
    r = admin.patch(f"/api/specialties/{psy['id']}", json={"is_active": False})
    assert r.status_code == 200 and r.json()["is_active"] is False

    # Ya no aparece en la lista normal, sí con include_inactive (solo admin).
    assert "Psicología" not in {s["name"] for s in admin.get("/api/specialties").json()}
    all_names = {s["name"] for s in admin.get("/api/specialties?include_inactive=true").json()}
    assert "Psicología" in all_names

    # Lucía conserva su especialidad aunque esté desactivada, y puede editarse su nombre.
    r = admin.patch(f"/api/users/{world.lucia.id}", json={"full_name": "Lucía Editada"})
    assert r.status_code == 200 and r.json()["specialty_name"] == "Psicología"

    # Pero no se puede asignar a otra persona.
    r = admin.patch(f"/api/users/{world.mateo.id}", json={"specialty_id": psy["id"]})
    assert r.status_code == 422

    actions = db.scalars(select(AuditEvent.action)).all()
    assert "specialty.update" in actions


def test_rename_specialty(world, login):
    admin = login(world.admin_a)
    ot = next(s for s in admin.get("/api/specialties").json() if s["name"] == "Terapia ocupacional")
    r = admin.patch(f"/api/specialties/{ot['id']}", json={"name": "Terapia Ocupacional (TO)"})
    assert r.status_code == 200
    profs = {p["full_name"]: p["specialty_name"] for p in admin.get("/api/professionals").json()}
    assert profs["Mateo"] == "Terapia Ocupacional (TO)"


def test_specialties_are_isolated_between_clinics(world, login):
    admin_b = login(world.admin_b)
    psy_b = next(s for s in admin_b.get("/api/specialties").json() if s["name"] == "Psicología")
    admin_a = login(world.admin_a)
    # No se ve ni se edita la especialidad de otra clínica...
    assert psy_b["id"] not in {s["id"] for s in admin_a.get("/api/specialties").json()}
    assert admin_a.patch(f"/api/specialties/{psy_b['id']}", json={"name": "Otro nombre"}).status_code == 404
    # ...ni se puede asignar a una cuenta propia.
    r = admin_a.patch(f"/api/users/{world.mateo.id}", json={"specialty_id": psy_b["id"]})
    assert r.status_code == 422
