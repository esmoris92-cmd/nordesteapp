"""Recepción puede LEER los informes FINALIZADOS; nada más de lo clínico."""

from sqlalchemy import select

from app.models import AuditEvent


def _two_reports(world, login):
    """Lucía crea un informe finalizado y otro en borrador sobre su paciente."""
    lucia = login(world.lucia)
    pid = world.patient_a.id
    final = lucia.post(f"/api/patients/{pid}/reports",
                       json={"title": "Informe final", "content": "Contenido ficticio final"}).json()
    lucia.post(f"/api/reports/{final['id']}/finalize")
    draft = lucia.post(f"/api/patients/{pid}/reports",
                       json={"title": "Borrador", "content": "Contenido ficticio borrador"}).json()
    return final["id"], draft["id"]


def test_reception_sees_only_final_reports(world, login):
    final_id, draft_id = _two_reports(world, login)
    rec = login(world.reception_a)
    pid = world.patient_a.id

    listed = rec.get(f"/api/patients/{pid}/reports")
    assert listed.status_code == 200
    assert [r["id"] for r in listed.json()] == [final_id]

    r = rec.get(f"/api/reports/{final_id}")
    assert r.status_code == 200 and r.json()["content"] == "Contenido ficticio final"
    assert rec.get(f"/api/reports/{draft_id}").status_code == 404

    detail = rec.get(f"/api/patients/{pid}").json()
    assert detail["can_view_reports"] is True and detail["can_view_clinical"] is False


def test_reception_cannot_write_reports_or_read_notes(world, login):
    final_id, draft_id = _two_reports(world, login)
    rec = login(world.reception_a)
    pid = world.patient_a.id
    assert rec.post(f"/api/patients/{pid}/reports",
                    json={"title": "Intento", "content": "x"}).status_code == 403
    assert rec.patch(f"/api/reports/{draft_id}", json={"title": "Cambio"}).status_code == 403
    assert rec.post(f"/api/reports/{draft_id}/finalize").status_code == 403
    assert rec.get(f"/api/patients/{pid}/notes").status_code == 403


def test_reception_report_reads_are_audited(world, login, db):
    final_id, _ = _two_reports(world, login)
    rec = login(world.reception_a)
    rec.get(f"/api/patients/{world.patient_a.id}/reports")
    rec.get(f"/api/reports/{final_id}")
    actions = db.scalars(
        select(AuditEvent.action).where(AuditEvent.actor_id == world.reception_a.id)
    ).all()
    assert "report.list" in actions and "report.view" in actions


def test_reception_cannot_read_reports_of_other_clinic(world, login):
    bruno = login(world.bruno)
    rep = bruno.post(f"/api/patients/{world.patient_b.id}/reports",
                     json={"title": "Informe Boreal", "content": "x"}).json()
    bruno.post(f"/api/reports/{rep['id']}/finalize")
    rec = login(world.reception_a)
    assert rec.get(f"/api/patients/{world.patient_b.id}/reports").status_code == 404
    assert rec.get(f"/api/reports/{rep['id']}").status_code == 404
