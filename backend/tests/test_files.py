"""Archivos adjuntos: tipos permitidos, tamaño, permisos, descarga y retiro."""

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from app.models import AuditEvent

PDF = b"%PDF-1.4\n% archivo ficticio de prueba\n%%EOF\n"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


def _upload(client, world, data, name="informe escolar.pdf", patient=None):
    pid = (patient or world.patient_a).id
    return client.post(f"/api/patients/{pid}/files", params={"filename": name, "description": "Prueba"},
                       content=data, headers={"Content-Type": "application/octet-stream"})


def test_upload_list_and_download(world, login, db):
    lucia = login(world.lucia)
    r = _upload(lucia, world, PDF)
    assert r.status_code == 201, r.text
    f = r.json()
    assert f["content_type"] == "application/pdf" and f["original_name"] == "informe escolar.pdf"
    assert [x["id"] for x in lucia.get(f"/api/patients/{world.patient_a.id}/files").json()] == [f["id"]]

    d = lucia.get(f"/api/files/{f['id']}/download")
    assert d.status_code == 200 and d.content == PDF
    assert d.headers["content-type"] == "application/pdf"
    assert d.headers["content-disposition"].startswith("attachment;")
    assert d.headers["x-content-type-options"] == "nosniff"

    actions = db.scalars(select(AuditEvent.action)).all()
    assert {"file.upload", "file.list", "file.download"} <= set(actions)
    assert all("escolar" not in str(x) for x in db.scalars(select(AuditEvent.details)).all())


def test_type_is_checked_by_content_not_name(world, login):
    lucia = login(world.lucia)
    r = _upload(lucia, world, b"MZ\x90\x00 programa", name="foto.pdf")
    assert r.status_code == 415
    r = _upload(lucia, world, PNG, name="dibujo.exe")
    assert r.status_code == 201 and r.json()["original_name"] == "dibujo.png"
    r = _upload(lucia, world, PDF, name="../../etc/passwd")
    assert r.status_code == 201 and "/" not in r.json()["original_name"]


def test_size_limit(world, login, monkeypatch):
    from app.config import get_settings
    monkeypatch.setattr(get_settings(), "max_upload_mb", 1)
    r = _upload(login(world.lucia), world, PDF + b"0" * (1024 * 1024 + 10))
    assert r.status_code == 413


def test_only_professionals_with_access_or_staff(world, login):
    """Profesionales sin acceso al paciente y otras clínicas: no. Administración y Recepción: sí
    (decisión del 24/11/2026)."""
    f = _upload(login(world.lucia), world, PDF).json()
    for user, code in ((world.mateo, 404), (world.bruno, 404)):
        client = login(user)
        assert client.get(f"/api/files/{f['id']}/download").status_code == code
        assert _upload(client, world, PDF).status_code == code
    for user in (world.reception_a, world.admin_a):
        client = login(user)
        assert client.get(f"/api/files/{f['id']}/download").status_code == 200
        assert _upload(client, world, PDF).status_code == 201
    # Administración de otra clínica no ve nada de la clínica A.
    other = login(world.admin_b)
    assert other.get(f"/api/files/{f['id']}/download").status_code == 404
    assert other.get(f"/api/patients/{world.patient_a.id}/files").status_code == 404
    assert _upload(other, world, PDF).status_code == 404


def test_staff_uploads_and_sees_every_file(world, login, db):
    """Recepción y Administración suben archivos y ven todos los del paciente (también los que
    subió el profesional); el profesional ve los que subieron ellos."""
    lucia = login(world.lucia)
    from_prof = _upload(lucia, world, PDF, name="evaluacion.pdf").json()
    reception = login(world.reception_a)
    r = _upload(reception, world, PNG, name="carne.png")
    assert r.status_code == 201, r.text
    from_reception = r.json()
    assert from_reception["uploaded_by_name"] == "Recepcion"
    admin = login(world.admin_a)
    from_admin = _upload(admin, world, PDF, name="orden.pdf").json()

    ids = {from_prof["id"], from_reception["id"], from_admin["id"]}
    for client in (lucia, reception, admin):
        assert {x["id"] for x in client.get(f"/api/patients/{world.patient_a.id}/files").json()} == ids
    assert reception.get(f"/api/files/{from_prof['id']}/download").content == PDF
    uploads = db.scalars(select(AuditEvent.actor_id).where(AuditEvent.action == "file.upload")).all()
    assert {world.lucia.id, world.reception_a.id, world.admin_a.id} <= set(uploads)


def test_staff_withdraws_only_what_they_uploaded(world, login):
    lucia = login(world.lucia)
    from_prof = _upload(lucia, world, PDF).json()
    reception = login(world.reception_a)
    mine = _upload(reception, world, PDF).json()
    listed = {x["id"]: x for x in reception.get(f"/api/patients/{world.patient_a.id}/files").json()}
    assert listed[mine["id"]]["can_withdraw"] and not listed[from_prof["id"]]["can_withdraw"]
    assert reception.post(f"/api/files/{from_prof['id']}/withdraw", json={"reason": "No corresponde"}).status_code == 403
    assert login(world.admin_a).post(f"/api/files/{mine['id']}/withdraw", json={"reason": "No corresponde"}).status_code == 403
    assert reception.post(f"/api/files/{mine['id']}/withdraw", json={"reason": "Subido por error"}).status_code == 200
    # El profesional responsable puede retirar lo que subió Recepción.
    again = _upload(reception, world, PDF).json()
    assert lucia.post(f"/api/files/{again['id']}/withdraw", json={"reason": "Duplicado"}).status_code == 200


def test_reception_only_patients_of_its_branch(world, login, db):
    """Recepción ve los archivos de los pacientes que ve: los de su sucursal y los privados."""
    from app.models import Branch, Patient, PatientAccess
    other_branch = Branch(clinic_id=world.clinic_a.id, name="Pando")
    db.add(other_branch)
    db.flush()
    p = Patient(clinic_id=world.clinic_a.id, first_name="Carla", last_name="Prueba", affiliation="ayex",
                created_by=world.admin_a.id, branch_id=other_branch.id)
    db.add(p)
    db.flush()
    db.add(PatientAccess(clinic_id=world.clinic_a.id, patient_id=p.id, user_id=world.lucia.id,
                         level="responsible", granted_by=world.admin_a.id))
    db.commit()
    f = _upload(login(world.lucia), world, PDF, patient=p).json()
    reception = login(world.reception_a)
    assert reception.get(f"/api/patients/{p.id}/files").status_code == 404
    assert reception.get(f"/api/files/{f['id']}/download").status_code == 404
    assert _upload(reception, world, PDF, patient=p).status_code == 404
    admin = login(world.admin_a)  # con dos sucursales, Administración elige una para entrar
    assert admin.post("/api/auth/branch", json={"branch_id": str(world.branch_a.id)}).status_code == 200
    assert admin.get(f"/api/files/{f['id']}/download").status_code == 200


def test_institution_files_only_by_professionals(world, login):
    reception = login(world.reception_a)
    inst = reception.post(f"/api/patients/{world.patient_a.id}/institutions",
                          json={"name": "Escuela ficticia", "level": "primaria"})
    assert inst.status_code == 201, inst.text
    r = reception.post(f"/api/patients/{world.patient_a.id}/files",
                       params={"filename": "a.pdf", "institution_id": inst.json()["id"]},
                       content=PDF, headers={"Content-Type": "application/octet-stream"})
    assert r.status_code == 403


def test_withdraw_hides_and_keeps_record(world, login, db):
    lucia = login(world.lucia)
    f = _upload(lucia, world, PDF).json()
    lucia.post(f"/api/patients/{world.patient_a.id}/access",
               json={"professional_id": str(world.mateo.id), "level": "collaborator"})
    mateo = login(world.mateo)
    # Un colaborador no puede retirar un archivo que no subió.
    assert mateo.post(f"/api/files/{f['id']}/withdraw", json={"reason": "No corresponde"}).status_code == 403
    r = lucia.post(f"/api/files/{f['id']}/withdraw", json={"reason": "Subido por error"})
    assert r.status_code == 200 and r.json()["withdraw_reason"] == "Subido por error"
    assert lucia.get(f"/api/patients/{world.patient_a.id}/files").json() == []
    hist = lucia.get(f"/api/patients/{world.patient_a.id}/files", params={"include_withdrawn": "true"}).json()
    assert len(hist) == 1 and hist[0]["withdrawn_by_name"] == "Lucia"
    assert lucia.get(f"/api/files/{f['id']}/download").status_code == 404
    with pytest.raises(DBAPIError):
        db.execute(text("DELETE FROM patient_files"))
    db.rollback()


def test_csrf_required_for_upload(world, login):
    lucia = login(world.lucia)
    r = lucia.http.post(f"/api/patients/{world.patient_a.id}/files", params={"filename": "a.pdf"}, content=PDF)
    assert r.status_code == 403


def test_view_inside_medflow_is_audited_as_view(world, login, db):
    lucia = login(world.lucia)
    f = _upload(lucia, world, PNG, name="foto.png").json()
    v = lucia.get(f"/api/files/{f['id']}/download", params={"view": "true"})
    assert v.status_code == 200 and v.content == PNG and v.headers["content-type"] == "image/png"
    assert "file.view" in db.scalars(select(AuditEvent.action)).all()
    # Quien no tiene acceso tampoco puede verlo.
    assert login(world.mateo).get(f"/api/files/{f['id']}/download", params={"view": "true"}).status_code == 404
    # Para verlo se muestra "inline" y solo puede incrustarse dentro de MedFlow.
    assert v.headers["content-disposition"].startswith("inline;")
    assert v.headers["content-security-policy"] == "frame-ancestors 'self'"
    assert v.headers["x-frame-options"] == "SAMEORIGIN" and v.headers["cache-control"] == "no-store"
    # La descarga normal sigue sin poder incrustarse en ninguna página.
    d = lucia.get(f"/api/files/{f['id']}/download")
    assert d.headers["content-disposition"].startswith("attachment;")
    assert d.headers["x-frame-options"] == "DENY" and "frame-ancestors 'none'" in d.headers["content-security-policy"]
