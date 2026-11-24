"""Título universitario de los profesionales: lo suben ellos y lo ven solo ellos y Administración."""

from sqlalchemy import select

from app.models import AuditEvent, ProfessionalDegree

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64  # imagen ficticia (solo la firma importa)
PDF = b"%PDF-1.4\n%ficticio\n"


def _upload(client, data, name="titulo.png"):
    return client.post("/api/account/degree", params={"filename": name}, content=data,
                       headers={"Content-Type": "application/octet-stream"})


def test_professional_uploads_and_replaces_degree(world, login, db):
    lucia = login(world.lucia)
    assert lucia.get("/api/account/degree").json() is None
    assert lucia.get("/api/auth/me").json()["user"]["degree_uploaded_at"] is None
    r = _upload(lucia, PNG, "Título Lucía.png")
    assert r.status_code == 201, r.text
    first = r.json()
    assert first["content_type"] == "image/png" and first["original_name"] == "Título Lucía.png"
    me = lucia.get("/api/auth/me").json()["user"]
    assert me["degree_id"] == first["id"] and me["degree_uploaded_at"] is not None
    # Reemplazarlo: el anterior queda guardado como reemplazado.
    r = _upload(lucia, PDF, "titulo.pdf")
    assert r.status_code == 201 and r.json()["content_type"] == "application/pdf"
    assert lucia.get("/api/account/degree").json()["id"] == r.json()["id"]
    rows = db.scalars(select(ProfessionalDegree).where(ProfessionalDegree.user_id == world.lucia.id)).all()
    assert len(rows) == 2 and sum(1 for d in rows if d.replaced_at is None) == 1
    # Descargarlo: ella sí.
    d = lucia.get(f"/api/degrees/{r.json()['id']}/download")
    assert d.status_code == 200 and d.content == PDF and d.headers["x-content-type-options"] == "nosniff"
    actions = db.scalars(select(AuditEvent.action)).all()
    assert actions.count("degree.upload") == 2 and "degree.download" in actions
    assert all("titulo" not in str(e) for e in db.scalars(select(AuditEvent.details)).all())


def test_who_can_see_the_degree(world, login):
    lucia = login(world.lucia)
    degree = _upload(lucia, PNG).json()
    url = f"/api/degrees/{degree['id']}/download"
    # Administración: sí (y lo ve en el listado de cuentas).
    admin = login(world.admin_a)
    assert admin.get(url, params={"view": "true"}).status_code == 200
    users = {u["id"]: u for u in admin.get("/api/users").json()}
    assert users[str(world.lucia.id)]["degree_id"] == degree["id"]
    assert users[str(world.mateo.id)]["degree_id"] is None
    assert admin.get(f"/api/users/{world.lucia.id}/degree").json()["id"] == degree["id"]
    # Recepción, otro profesional u otra clínica: no (404, sin revelar que existe).
    assert login(world.reception_a).get(url).status_code == 404
    assert login(world.mateo).get(url).status_code == 404
    assert login(world.mateo).get(f"/api/users/{world.lucia.id}/degree").status_code == 404
    assert login(world.admin_b).get(url).status_code == 404


def test_upload_rules(world, login):
    lucia = login(world.lucia)
    assert _upload(lucia, b"").status_code == 422
    assert _upload(lucia, b"<html>no</html>", "titulo.png").status_code == 415
    # Solo los profesionales cargan título.
    assert _upload(login(world.reception_a), PNG).status_code == 403
    assert _upload(login(world.admin_a), PNG).status_code == 403
