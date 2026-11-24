"""Ficha del paciente: segundo nombre/apellido, sexo y documento."""

from sqlalchemy import select

from app.models import AuditEvent

FULL = {
    "first_name": "Tomás", "middle_name": "Ignacio", "last_name": "Ficticio",
    "second_last_name": "Prueba", "document_number": "1.234.567-8", "sex": "male",
    "birth_date": "2018-05-20", "affiliation": "military",
}


def test_create_and_read_full_profile(world, login):
    rec = login(world.reception_a)
    r = rec.post("/api/patients", json=FULL)
    assert r.status_code == 201, r.text
    p = rec.get(f"/api/patients/{r.json()['id']}").json()
    for key in ("middle_name", "second_last_name", "document_number", "sex"):
        assert p[key] == FULL[key]


def test_document_is_unique_per_clinic(world, login):
    rec = login(world.reception_a)
    assert rec.post("/api/patients", json=FULL).status_code == 201
    r = rec.post("/api/patients", json={**FULL, "first_name": "Otro"})
    assert r.status_code == 409 and "documento" in r.json()["detail"]
    # Otra clínica puede tener un paciente con el mismo número.
    assert login(world.admin_b).post("/api/patients", json=FULL).status_code == 201


def test_edit_document_checks_duplicates_and_can_clear(world, login):
    rec = login(world.reception_a)
    rec.post("/api/patients", json=FULL)
    pid = world.patient_a.id
    assert rec.patch(f"/api/patients/{pid}", json={"document_number": "1.234.567-8"}).status_code == 409
    r = rec.patch(f"/api/patients/{pid}", json={"document_number": "9.999.999-9", "sex": "female"})
    assert r.status_code == 200 and r.json()["sex"] == "female"
    r = rec.patch(f"/api/patients/{pid}", json={"document_number": ""})
    assert r.status_code == 200 and r.json()["document_number"] is None


def test_search_by_document(world, login):
    rec = login(world.reception_a)
    rec.post("/api/patients", json=FULL)
    found = rec.get("/api/patients", params={"q": "234.567"}).json()
    assert [p["first_name"] for p in found] == ["Tomás"]


def test_invalid_values_are_rejected(world, login):
    rec = login(world.reception_a)
    r = rec.post("/api/patients", json={**FULL, "document_number": "<script>", "sex": "otro"})
    assert r.status_code == 422
    assert "<script>" not in r.text


def test_document_never_goes_to_audit(world, login, db):
    rec = login(world.reception_a)
    pid = rec.post("/api/patients", json=FULL).json()["id"]
    rec.patch(f"/api/patients/{pid}", json={"document_number": "5.555.555-5"})
    for details in db.scalars(select(AuditEvent.details)).all():
        assert "234.567" not in str(details) and "555.555" not in str(details)


def test_affiliation_is_required_and_editable(world, login):
    rec = login(world.reception_a)
    without = {k: v for k, v in FULL.items() if k != "affiliation"}
    r = rec.post("/api/patients", json=without)
    assert r.status_code == 422
    assert {"field": "affiliation", "message": "Este campo es obligatorio."} in r.json()["errors"]
    assert rec.post("/api/patients", json={**FULL, "affiliation": "mutualista"}).status_code == 422
    assert rec.post("/api/patients", json={**FULL, "affiliation": ""}).status_code == 422

    created = rec.post("/api/patients", json=FULL).json()
    assert created["affiliation"] == "military"
    pid = created["id"]
    # Pasar a AYEX pide la fecha de vencimiento.
    r = rec.patch(f"/api/patients/{pid}", json={"affiliation": "ayex"})
    assert r.status_code == 422 and "vencimiento del AYEX" in r.json()["detail"]
    r = rec.patch(f"/api/patients/{pid}", json={"affiliation": "ayex", "ayex_expires_on": "2030-12-31"})
    assert r.status_code == 200 and r.json()["affiliation"] == "ayex"
    assert r.json()["ayex_expires_on"] == "2030-12-31"
    # No se puede dejar vacío al editar.
    assert rec.patch(f"/api/patients/{pid}", json={"affiliation": None}).status_code == 422
    assert rec.get(f"/api/patients/{pid}").json()["affiliation"] == "ayex"


def test_filter_by_affiliation(world, login):
    rec = login(world.reception_a)
    rec.post("/api/patients", json=FULL)  # Tutela Militar
    rec.post("/api/patients", json={**FULL, "document_number": None, "first_name": "Rosa",
                                     "affiliation": "ayex", "ayex_expires_on": "2030-12-31"})
    names = lambda **params: sorted(p["first_name"] for p in rec.get("/api/patients", params=params).json())
    assert names(affiliation="military") == ["Tomás"]
    assert names(affiliation="ayex") == ["Rosa"]
    assert names(affiliation="private") == ["Ana"]  # paciente de la clínica A en las pruebas
    assert names(affiliation="ayex", q="Rosa") == ["Rosa"]
    assert names(affiliation="ayex", q="Tomás") == []
    assert len(names()) == 3
    assert rec.get("/api/patients", params={"affiliation": "otra"}).status_code == 422
    # Nunca muestra pacientes de otra clínica (Beto, de la clínica B, es de AYEX).
    assert "Beto" not in names(affiliation="ayex")
