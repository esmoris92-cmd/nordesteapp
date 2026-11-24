"""Administración puede LEER (e imprimir) los informes FINALIZADOS; nada más de lo clínico."""

from sqlalchemy import select

from app.models import AccessLevel, AuditEvent, Branch, Patient, PatientAccess


def _two_reports(world, login, pid=None):
    """Lucía crea un informe finalizado y otro en borrador sobre su paciente."""
    lucia = login(world.lucia)
    pid = pid or world.patient_a.id
    final = lucia.post(f"/api/patients/{pid}/reports",
                       json={"title": "Informe final", "content": "Contenido ficticio final"}).json()
    lucia.post(f"/api/reports/{final['id']}/finalize")
    draft = lucia.post(f"/api/patients/{pid}/reports",
                       json={"title": "Borrador", "content": "Contenido ficticio borrador"}).json()
    return final["id"], draft["id"]


def test_admin_sees_only_final_reports(world, login):
    final_id, draft_id = _two_reports(world, login)
    adm = login(world.admin_a)
    pid = world.patient_a.id

    listed = adm.get(f"/api/patients/{pid}/reports")
    assert listed.status_code == 200
    assert [r["id"] for r in listed.json()] == [final_id]

    r = adm.get(f"/api/reports/{final_id}")
    assert r.status_code == 200 and r.json()["content"] == "Contenido ficticio final"
    assert adm.get(f"/api/reports/{draft_id}").status_code == 404

    detail = adm.get(f"/api/patients/{pid}").json()
    assert detail["can_view_reports"] is True and detail["can_view_clinical"] is False


def test_admin_cannot_write_reports_or_read_clinical(world, login):
    final_id, draft_id = _two_reports(world, login)
    adm = login(world.admin_a)
    pid = world.patient_a.id
    assert adm.post(f"/api/patients/{pid}/reports",
                    json={"title": "Intento", "content": "x"}).status_code == 403
    assert adm.patch(f"/api/reports/{draft_id}", json={"title": "Cambio"}).status_code == 403
    assert adm.post(f"/api/reports/{draft_id}/finalize").status_code == 403
    assert adm.get(f"/api/patients/{pid}/notes").status_code == 403
    assert adm.get(f"/api/patients/{pid}/report-sections").status_code == 403


def test_admin_report_reads_are_audited(world, login, db):
    final_id, _ = _two_reports(world, login)
    adm = login(world.admin_a)
    adm.get(f"/api/patients/{world.patient_a.id}/reports")
    adm.get(f"/api/reports/{final_id}")
    actions = db.scalars(
        select(AuditEvent.action).where(AuditEvent.actor_id == world.admin_a.id)
    ).all()
    assert "report.list" in actions and "report.view" in actions


def test_admin_reads_final_reports_of_any_branch(world, login, db):
    """A diferencia de recepción, administración ve los pacientes de todas las sucursales."""
    pando = Branch(clinic_id=world.clinic_a.id, name="Pando")
    db.add(pando)
    db.flush()
    other = Patient(clinic_id=world.clinic_a.id, first_name="Carla", last_name="Ficticia",
                    affiliation="ayex", created_by=world.admin_a.id, branch_id=pando.id)
    db.add(other)
    db.flush()
    db.add(PatientAccess(clinic_id=world.clinic_a.id, patient_id=other.id, user_id=world.lucia.id,
                         level=AccessLevel.responsible.value, granted_by=world.admin_a.id))
    db.commit()
    final_id, _ = _two_reports(world, login, other.id)
    adm = login(world.admin_a)
    # Con dos sucursales hay que elegir una: con Central activa, igual ve el informe de Pando.
    assert adm.post("/api/auth/branch", json={"branch_id": str(world.branch_a.id)}).status_code == 200
    assert [r["id"] for r in adm.get(f"/api/patients/{other.id}/reports").json()] == [final_id]
    assert adm.get(f"/api/reports/{final_id}").status_code == 200


def test_admin_cannot_read_reports_of_other_clinic(world, login):
    bruno = login(world.bruno)
    rep = bruno.post(f"/api/patients/{world.patient_b.id}/reports",
                     json={"title": "Informe Boreal", "content": "x"}).json()
    bruno.post(f"/api/reports/{rep['id']}/finalize")
    adm = login(world.admin_a)
    assert adm.get(f"/api/patients/{world.patient_b.id}/reports").status_code == 404
    assert adm.get(f"/api/reports/{rep['id']}").status_code == 404
