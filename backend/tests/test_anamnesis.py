"""Anamnesis estructurada: una por paciente, cada guardado es una versión nueva, mismos
permisos que la historia clínica y aviso si otra persona guardó mientras se editaba
(todo con datos ficticios)."""

from app.models import AnamnesisVersion, AuditEvent, PatientAccess


def _url(world):
    return f"/api/patients/{world.patient_a.id}/anamnesis"


def test_save_and_versions(world, login, db):
    lucia = login(world.lucia)
    r = lucia.get(_url(world))
    assert r.status_code == 200 and r.json() == {"current": None, "versions": []}

    r = lucia.post(_url(world), json={"data": {"motivo_dificultad": "  Dificultad ficticia  ",
                                               "madre_nombre": "", "familia_vive_con": "Madre y hermano"}})
    assert r.status_code == 201, r.text
    v1 = r.json()
    # Se guarda sin espacios de más y sin los campos vacíos.
    assert v1["data"] == {"motivo_dificultad": "Dificultad ficticia", "familia_vive_con": "Madre y hermano"}
    assert v1["author_name"] == world.lucia.full_name

    # Sin base_version_id cuando ya hay una: otra persona guardó antes → 409, no se pisa.
    r = lucia.post(_url(world), json={"data": {"motivo_dificultad": "Otra"}})
    assert r.status_code == 409
    # Sin cambios → 422.
    r = lucia.post(_url(world), json={"data": v1["data"], "base_version_id": v1["id"]})
    assert r.status_code == 422 and r.json()["detail"] == "No hay cambios para guardar."

    r = lucia.post(_url(world), json={"data": {**v1["data"], "psico_animo": "Sin cambios notables"},
                                      "base_version_id": v1["id"]})
    assert r.status_code == 201
    v2 = r.json()
    d = lucia.get(_url(world)).json()
    assert d["current"]["id"] == v2["id"] and d["current"]["data"]["psico_animo"] == "Sin cambios notables"
    assert [v["id"] for v in d["versions"]] == [v2["id"], v1["id"]]
    assert [v["fields"] for v in d["versions"]] == [3, 2]
    # La versión anterior sigue igual y se puede ver.
    old = lucia.get(f"{_url(world)}/{v1['id']}").json()
    assert old["data"] == v1["data"]
    assert lucia.get(f"{_url(world)}/{world.patient_b.id}").status_code == 404  # no es una versión
    # Queda en la auditoría (sin el contenido).
    actions = [e.action for e in db.query(AuditEvent).filter_by(patient_id=world.patient_a.id)]
    assert actions.count("anamnesis.save") == 2 and "anamnesis.view" in actions
    saved = db.query(AuditEvent).filter_by(action="anamnesis.save").first()
    assert saved.details == {"count": 2}


def test_other_professional_edits_on_top(world, login, db):
    """Otro profesional con acceso completa su área sobre la versión vigente."""
    lucia = login(world.lucia)
    v1 = lucia.post(_url(world), json={"data": {"motivo_dificultad": "Ficticia"}}).json()
    db.add(PatientAccess(clinic_id=world.clinic_a.id, patient_id=world.patient_a.id,
                         user_id=world.mateo.id, level="collaborator", granted_by=world.lucia.id))
    db.commit()
    mateo = login(world.mateo)
    r = mateo.post(_url(world), json={"data": {**v1["data"], "to_motricidad_fina": "Le cuesta abotonarse"},
                                      "base_version_id": v1["id"]})
    assert r.status_code == 201, r.text
    # Lucía, que había abierto la versión 1, no puede pisar lo de Mateo sin verlo.
    r = lucia.post(_url(world), json={"data": {"motivo_dificultad": "Cambio"}, "base_version_id": v1["id"]})
    assert r.status_code == 409 and world.mateo.full_name in r.json()["detail"]
    assert db.query(AnamnesisVersion).count() == 2


def test_permissions_like_clinical_record(world, login):
    url = _url(world)
    body = {"data": {"motivo_dificultad": "Ficticia"}}
    for who in (world.reception_a, world.admin_a):
        c = login(who)
        assert c.get(url).status_code == 403 and c.post(url, json=body).status_code == 403
    mateo = login(world.mateo)  # profesional sin acceso a este paciente
    assert mateo.get(url).status_code == 404 and mateo.post(url, json=body).status_code == 404
    bruno = login(world.bruno)  # otra clínica
    assert bruno.get(url).status_code == 404


def test_rejects_bad_fields(world, login):
    lucia = login(world.lucia)
    url = _url(world)
    assert lucia.post(url, json={"data": {"Campo Raro!": "x"}}).status_code == 422
    assert lucia.post(url, json={"data": {"motivo_dificultad": "x" * 5001}}).status_code == 422
    assert lucia.post(url, json={"data": {"motivo_dificultad": 3}}).status_code == 422
    r = lucia.post(url, json={"data": {"motivo_dificultad": "   "}})
    assert r.status_code == 422 and "al menos un campo" in r.json()["detail"]
