"""Antecedentes, Diagnóstico, Encuadre (uno por paciente) y Abordaje (uno por profesional, con
En suma y Sugerencias): versiones, permisos y aviso si otra persona guardó (datos ficticios)."""

from app.models import AuditEvent, PatientAccess


def _url(world, section=""):
    base = f"/api/patients/{world.patient_a.id}/report-sections"
    return f"{base}/{section}" if section else base


def _give_mateo_access(world, db):
    db.add(PatientAccess(clinic_id=world.clinic_a.id, patient_id=world.patient_a.id,
                         user_id=world.mateo.id, level="collaborator", granted_by=world.lucia.id))
    db.commit()


def test_shared_sections_have_versions(world, login, db):
    lucia = login(world.lucia)
    d = lucia.get(_url(world)).json()
    assert d["diagnostico"] == {"current": None, "versions": []} and d["abordajes"] == []

    r = lucia.post(_url(world, "diagnostico"), json={"data": {"texto": "  Diagnóstico ficticio  "}})
    assert r.status_code == 201, r.text
    v1 = r.json()
    assert v1["data"] == {"texto": "Diagnóstico ficticio"} and v1["owner_id"] is None
    # Otra persona con acceso actualiza sobre la vigente; quien tenía la vieja no la pisa.
    _give_mateo_access(world, db)
    mateo = login(world.mateo)
    r = mateo.post(_url(world, "diagnostico"), json={"data": {"texto": "Actualizado (ficticio)"},
                                                     "base_version_id": v1["id"]})
    assert r.status_code == 201
    r = lucia.post(_url(world, "diagnostico"), json={"data": {"texto": "Otro"}, "base_version_id": v1["id"]})
    assert r.status_code == 409 and world.mateo.full_name in r.json()["detail"]
    d = lucia.get(_url(world)).json()["diagnostico"]
    assert d["current"]["data"]["texto"] == "Actualizado (ficticio)" and len(d["versions"]) == 2
    old = lucia.get(f"{_url(world)}/versions/{v1['id']}").json()
    assert old["data"] == v1["data"]
    # Validaciones.
    assert lucia.post(_url(world, "encuadre"), json={"data": {"abordaje": "x"}}).status_code == 422
    assert lucia.post(_url(world, "encuadre"), json={"data": {"texto": "  "}}).status_code == 422
    assert lucia.post(_url(world, "encuadre"), json={"data": {"texto": "x" * 20001}}).status_code == 422
    assert lucia.post(_url(world, "otra"), json={"data": {"texto": "x"}}).status_code == 422
    actions = [e.action for e in db.query(AuditEvent).filter_by(patient_id=world.patient_a.id)]
    assert actions.count("report_section.save") == 2 and "report_section.view" in actions


def test_each_professional_has_own_abordaje(world, login, db):
    _give_mateo_access(world, db)
    lucia, mateo = login(world.lucia), login(world.mateo)
    body = {"abordaje": "Abordaje ficticio", "en_suma": "En suma ficticio", "sugerencias": "Continuar"}
    assert lucia.post(_url(world, "abordaje"), json={"data": body}).status_code == 201
    # El de Mateo es otro (no choca con el de Lucía aunque no indique versión base).
    r = mateo.post(_url(world, "abordaje"), json={"data": {"abordaje": "Abordaje TO ficticio"}})
    assert r.status_code == 201, r.text
    d = lucia.get(_url(world)).json()["abordajes"]
    # Por profesión: Psicología (Lucía) antes que Terapia ocupacional (Mateo).
    assert [(a["owner_name"], a["specialty_name"]) for a in d] == [
        (world.lucia.full_name, "Psicología"), (world.mateo.full_name, "Terapia ocupacional")]
    assert d[0]["current"]["data"] == body
    assert lucia.post(_url(world, "abordaje"), json={"data": {"texto": "x"}}).status_code == 422


def test_permissions_like_clinical_record(world, login):
    for who in (world.reception_a, world.admin_a):
        c = login(who)
        assert c.get(_url(world)).status_code == 403
        assert c.post(_url(world, "encuadre"), json={"data": {"texto": "x"}}).status_code == 403
    assert login(world.mateo).get(_url(world)).status_code == 404  # sin acceso al paciente
    assert login(world.bruno).get(_url(world)).status_code == 404  # otra clínica


def test_long_generated_report_fits(world, login):
    """El informe generado puede superar los 20.000 caracteres de una nota."""
    lucia = login(world.lucia)
    r = lucia.post(f"/api/patients/{world.patient_a.id}/reports",
                   json={"title": "Informe de evolución (ficticio)", "content": "x" * 45000})
    assert r.status_code == 201, r.text
    r = lucia.post(f"/api/patients/{world.patient_a.id}/reports",
                   json={"title": "Demasiado largo", "content": "x" * 60001})
    assert r.status_code == 422


def test_generated_report_is_signed_by_everyone(world, login, db):
    """El informe generado lo firman todos los profesionales con abordaje (y quien lo genera)."""
    lucia = login(world.lucia)
    url = f"/api/patients/{world.patient_a.id}/reports"
    r = lucia.post(url, json={"title": "Informe de evolución (ficticio)", "content": "Texto",
                              "signer_ids": [str(world.mateo.id)]})
    assert r.status_code == 201, r.text
    signers = [(s["name"], s["specialty"]) for s in r.json()["signers"]]
    assert signers == [(world.mateo.full_name, "Terapia ocupacional"), (world.lucia.full_name, "Psicología")]
    rid = r.json()["id"]
    assert len(lucia.get(f"/api/reports/{rid}").json()["signers"]) == 2
    # Editar el borrador no cambia quién firma.
    assert lucia.patch(f"/api/reports/{rid}", json={"content": "Otro texto"}).json()["signers"][0]["name"] == world.mateo.full_name
    # Un informe en blanco lo firma solo el autor (lista vacía).
    assert lucia.post(url, json={"title": "Informe en blanco", "content": "x"}).json()["signers"] == []
    # No se puede poner como firmante a alguien de otra clínica ni a quien no es profesional.
    for other in (world.bruno, world.reception_a):
        r = lucia.post(url, json={"title": "Informe", "content": "x", "signer_ids": [str(other.id)]})
        assert r.status_code == 422



# ---------- Cierre del informe generado ----------


def _version_ids(client, world):
    d = client.get(_url(world)).json()
    ids = [d[k]["current"]["id"] for k in ("antecedentes", "diagnostico", "encuadre") if d[k]["current"]]
    return ids + [a["current"]["id"] for a in d["abordajes"] if a["current"]]


def _generate(client, world, signer_ids=()):
    return client.post(f"/api/patients/{world.patient_a.id}/reports", json={
        "title": "Informe de evolución (ficticio)", "content": "Texto ficticio",
        "signer_ids": list(signer_ids), "section_version_ids": _version_ids(client, world)})


def test_only_responsible_generates_and_all_abordajes_are_needed(world, login, db):
    _give_mateo_access(world, db)
    lucia, mateo = login(world.lucia), login(world.mateo)  # Lucía es la responsable
    lucia.post(_url(world, "abordaje"), json={"data": {"abordaje": "Abordaje ficticio"}})
    # Un colaborador no genera el informe conjunto (sí puede hacer uno en blanco).
    r = _generate(mateo, world)
    assert r.status_code == 403 and "responsable" in r.json()["detail"]
    blank = mateo.post(f"/api/patients/{world.patient_a.id}/reports", json={"title": "Mi informe", "content": "x"})
    assert blank.status_code == 201 and blank.json()["generated"] is False

    rep = _generate(lucia, world)
    assert rep.status_code == 201 and rep.json()["generated"] is True
    rid = rep.json()["id"]
    # Falta el abordaje de Mateo: no se puede finalizar.
    ready = lucia.get(f"/api/reports/{rid}/readiness").json()
    assert [p["name"] for p in ready["missing"]] == [world.mateo.full_name] and ready["can_close"] is True
    assert mateo.get(f"/api/reports/{rid}/readiness").json()["can_close"] is False
    r = lucia.post(f"/api/reports/{rid}/finalize")
    assert r.status_code == 409 and world.mateo.full_name in r.json()["detail"]

    # Mateo escribe el suyo: el borrador queda desactualizado hasta "Actualizar con lo último".
    mateo.post(_url(world, "abordaje"), json={"data": {"abordaje": "Abordaje TO ficticio"}})
    ready = lucia.get(f"/api/reports/{rid}/readiness").json()
    assert ready["missing"] == [] and ready["stale"] is True
    assert lucia.post(f"/api/reports/{rid}/finalize").status_code == 409
    r = lucia.patch(f"/api/reports/{rid}", json={"content": "Texto nuevo", "signer_ids": [str(world.mateo.id)],
                                                 "section_version_ids": _version_ids(lucia, world)})
    assert r.status_code == 200 and len(r.json()["signers"]) == 2
    # Mateo no puede finalizar ni actualizar el de Lucía.
    assert mateo.post(f"/api/reports/{rid}/finalize").status_code == 403
    r = lucia.post(f"/api/reports/{rid}/finalize")
    assert r.status_code == 200 and r.json()["status"] == "final"


def test_responsible_can_mark_not_participating(world, login, db):
    _give_mateo_access(world, db)
    lucia, mateo = login(world.lucia), login(world.mateo)
    lucia.post(_url(world, "diagnostico"), json={"data": {"texto": "Diagnóstico ficticio"}})
    rid = _generate(lucia, world).json()["id"]
    body = {"user_id": str(world.mateo.id), "participates": False}
    assert mateo.post(f"/api/reports/{rid}/participation", json=body).status_code == 403
    r = lucia.post(f"/api/reports/{rid}/participation", json=body)
    assert r.status_code == 200
    # Lucía también tiene acceso y no escribió abordaje: se la marca también para poder cerrar.
    assert [p["name"] for p in r.json()["missing"]] == [world.lucia.full_name]
    r = lucia.post(f"/api/reports/{rid}/participation", json={"user_id": str(world.lucia.id), "participates": False})
    assert r.json()["missing"] == [] and {p["name"] for p in r.json()["excluded"]} == {world.lucia.full_name, world.mateo.full_name}
    assert lucia.post(f"/api/reports/{rid}/participation",
                      json={"user_id": str(world.bruno.id), "participates": False}).status_code == 422
    assert lucia.post(f"/api/reports/{rid}/finalize").status_code == 200
    ev = db.query(AuditEvent).filter_by(action="report.participation").first()
    assert ev.details["status"] == "excluded"


def test_responsible_gets_notice_when_abordaje_is_written(world, login, db):
    _give_mateo_access(world, db)
    lucia, mateo = login(world.lucia), login(world.mateo)
    r = mateo.post(_url(world, "abordaje"), json={"data": {"abordaje": "Abordaje TO ficticio"}})
    notices = lucia.get("/api/notices/mine").json()
    assert len(notices) == 1
    msg = notices[0]["message"]
    assert msg.startswith(f"{world.mateo.full_name} (Terapia ocupacional) completó su abordaje de Ana Prueba.")
    assert "falta el abordaje de: el tuyo" in msg
    # Si vuelve a guardar, el aviso sin leer se reemplaza (no se acumulan).
    mateo.post(_url(world, "abordaje"), json={"data": {"abordaje": "Corregido"}, "base_version_id": r.json()["id"]})
    assert len(lucia.get("/api/notices/mine").json()) == 1
    # Cuando ya están todos, el aviso pide generar y finalizar.
    lucia.post(_url(world, "abordaje"), json={"data": {"abordaje": "Abordaje de Lucía"}})
    v = mateo.get(_url(world)).json()["abordajes"]
    mine = next(a for a in v if a["owner_id"] == str(world.mateo.id))
    mateo.post(_url(world, "abordaje"), json={"data": {"abordaje": "Final"}, "base_version_id": mine["current"]["id"]})
    notices = lucia.get("/api/notices/mine").json()
    assert len(notices) == 1 and notices[0]["message"].endswith("Por favor, generá y finalizá el informe.")
    # La responsable no se avisa a sí misma, y la lista de avisos de Administración no los muestra.
    assert login(world.mateo).get("/api/notices/mine").json() == []
    assert login(world.admin_a).get("/api/notices").json() == []
