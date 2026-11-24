"""Instituciones educativas del paciente: datos de contacto para quien ve la ficha; reportes
y archivos solo para los profesionales con acceso; los reportes se corrigen, no se borran."""

from tests.test_files import PDF

BASE = "/api/patients/{}/institutions"


def _inst(client, world, **extra):
    body = {"name": "Escuela N.º 999 (ficticia)", "level": "primaria", "phone": "099 000 111",
            "email": "direccion@escuela-ficticia.test", **extra}
    return client.post(BASE.format(world.patient_a.id), json=body)


def test_reception_manages_institutions(world, login):
    rec = login(world.reception_a)
    r = _inst(rec, world)
    assert r.status_code == 201, r.text
    first = r.json()
    assert (first["level"], first["is_current"], first["email"]) == ("primaria", True, "direccion@escuela-ficticia.test")
    # Una nueva institución actual reemplaza a la anterior como "actual".
    second = _inst(rec, world, name="Liceo ficticio", level="secundaria").json()
    rows = rec.get(BASE.format(world.patient_a.id)).json()
    assert [(i["name"], i["is_current"]) for i in rows] == [("Liceo ficticio", True),
                                                            ("Escuela N.º 999 (ficticia)", False)]
    assert _inst(rec, world, level="maternal").status_code == 422
    assert _inst(rec, world, email="no-es-correo").status_code == 422
    r = rec.patch(f"{BASE.format(world.patient_a.id)}/{second['id']}", json={"phone": "2600 0000", "level": "utu"})
    assert r.status_code == 200 and (r.json()["phone"], r.json()["level"]) == ("2600 0000", "utu")
    # Sin reportes ni archivos se puede quitar.
    assert rec.delete(f"{BASE.format(world.patient_a.id)}/{first['id']}").status_code == 204
    # Otra clínica no la ve; un profesional sin acceso al paciente tampoco.
    assert login(world.admin_b).get(BASE.format(world.patient_a.id)).status_code == 404
    assert login(world.mateo).get(BASE.format(world.patient_a.id)).status_code == 404


def test_reports_and_files_are_clinical(world, login):
    rec, lucia = login(world.reception_a), login(world.lucia)
    inst = _inst(rec, world).json()
    notes_url = f"/api/patients/{world.patient_a.id}/notes"
    report = {"kind": "institution", "institution_id": inst["id"], "content": "Reunión con la maestra (ficticio)."}
    # Recepción no escribe reportes; la profesional responsable sí.
    assert rec.post(notes_url, json=report).status_code == 403
    r = lucia.post(notes_url, json=report)
    assert r.status_code == 201 and r.json()["institution_id"] == inst["id"], r.text
    # Un reporte de institución necesita la institución, y debe ser de ESTE paciente.
    assert lucia.post(notes_url, json={**report, "institution_id": None}).status_code == 422
    other = login(world.admin_b).post(BASE.format(world.patient_b.id), json={
        "name": "Escuela de otra clínica", "level": "primaria"}).json()
    assert lucia.post(notes_url, json={**report, "institution_id": other["id"]}).status_code == 404
    assert lucia.post(notes_url, json={"kind": "session", "content": "x", "institution_id": inst["id"]}).status_code == 422
    # La corrección conserva la institución.
    fixed = lucia.post(f"/api/notes/{r.json()['id']}/corrections",
                       json={"content": "Reunión con la directora (ficticio).", "reason": "Error de cargo"})
    assert fixed.status_code == 201 and fixed.json()["institution_id"] == inst["id"]
    # Archivo de la institución.
    up = lucia.post(f"/api/patients/{world.patient_a.id}/files",
                    params={"filename": "carné escolar.pdf", "institution_id": inst["id"]},
                    content=PDF, headers={"Content-Type": "application/octet-stream"})
    assert up.status_code == 201 and up.json()["institution_name"] == "Escuela N.º 999 (ficticia)", up.text
    # Desde el 24/11/2026 Recepción ve los archivos del paciente (también los de instituciones),
    # pero no sube archivos a una institución.
    listed = rec.get(f"/api/patients/{world.patient_a.id}/files")
    assert listed.status_code == 200 and [f["institution_id"] for f in listed.json()] == [inst["id"]]
    # Con reportes o archivos, la institución no se puede quitar.
    r = rec.delete(f"{BASE.format(world.patient_a.id)}/{inst['id']}")
    assert r.status_code == 409 and "desmarcala" in r.json()["detail"]
