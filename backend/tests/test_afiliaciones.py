"""Tipos de afiliación: Privado, AYEX, Tutela Militar y Tutela Policial.
Los tres que no son privados se atienden solo en la sucursal del paciente."""

from tests.test_agenda_branches import DAY, OTHER, _book, _setup


def test_all_types_can_be_created_imported_and_filtered(world, login):
    admin = login(world.admin_a)
    for aff in ("private", "ayex", "military", "police"):
        r = admin.post("/api/patients", json={"first_name": f"Afi{aff}", "last_name": "Ficticio",
                                              "affiliation": aff, "ayex_expires_on": "2030-12-31"})
        assert r.status_code == 201 and r.json()["affiliation"] == aff, r.text
    assert admin.post("/api/patients", json={"first_name": "X", "last_name": "Y",
                                             "affiliation": "asse"}).status_code == 422
    body = ("primer_nombre;primer_apellido;tipo_afiliacion\n"
            "Uno;Ficticio;AYEX\nDos;Ficticio;Tutela Militar\nTres;Ficticio;Tutela Policial\n"
            "Cuatro;Ficticio;Policial\nCinco;Ficticio;ASSE\n")
    rows = admin.post("/api/patient-import?dry_run=true", content=body.encode(),
                      headers={"Content-Type": "application/octet-stream"}).json()["rows"]
    assert [r["affiliation"] for r in rows[:4]] == ["ayex", "military", "police", "police"]
    assert "Tutela Policial" in rows[4]["errors"][0]  # ASSE ya no es un tipo válido
    names = [p["first_name"] for p in admin.get("/api/patients", params={"affiliation": "police"}).json()]
    assert names == ["Afipolice"]


def test_police_patients_only_in_their_branch(world, login, db):
    central, pando, admin_c, admin_p, ids = _setup(world, login, db)
    r = admin_p.post("/api/patients", json={"first_name": "Poli", "last_name": "Pando", "affiliation": "police",
                                            "responsible_professional_id": str(world.lucia.id)})
    pid = r.json()["id"]
    r = _book(admin_c, pid, world.lucia, OTHER, 10)
    assert r.status_code == 409 and "es de Tutela Policial" in r.json()["detail"]
    assert _book(admin_p, pid, world.lucia, DAY, 10).status_code == 201
