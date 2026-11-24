"""Logo de la clínica: lo sube Administración y lo ve cualquier usuario de la clínica (para imprimir)."""

from sqlalchemy import select

from app.models import AuditEvent

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
JPG = b"\xff\xd8\xff\xe0" + b"\x00" * 32
OCTET = {"Content-Type": "application/octet-stream"}


def _upload(client, data):
    return client.post("/api/clinic/logo", content=data, headers=OCTET)


def test_admin_uploads_logo_and_everyone_in_clinic_sees_it(world, login, db):
    adm = login(world.admin_a)
    assert adm.get("/api/clinic/logo").status_code == 404  # todavía no hay
    r = _upload(adm, PNG)
    assert r.status_code == 200 and r.json()["logo_updated_at"]
    for user in (world.admin_a, world.reception_a, world.lucia):
        client = login(user)
        got = client.get("/api/clinic/logo")
        assert got.status_code == 200 and got.content == PNG
        assert got.headers["content-type"] == "image/png"
        assert got.headers["x-content-type-options"] == "nosniff"
        # La sesión avisa que hay logo (la hoja para imprimir lo usa).
        assert client.get("/api/auth/me").json()["clinic"]["logo_updated_at"]
    # Reemplazarlo por un JPG.
    assert _upload(adm, JPG).status_code == 200
    assert adm.get("/api/clinic/logo").headers["content-type"] == "image/jpeg"
    actions = db.scalars(select(AuditEvent.action).where(AuditEvent.actor_id == world.admin_a.id)).all()
    assert actions.count("clinic.logo_update") == 2


def test_only_admin_uploads_or_removes_logo(world, login):
    for user in (world.reception_a, world.lucia):
        client = login(user)
        assert _upload(client, PNG).status_code == 403
        assert client.delete("/api/clinic/logo").status_code == 403


def test_logo_must_be_small_png_or_jpg(world, login):
    adm = login(world.admin_a)
    assert _upload(adm, b"%PDF-1.7 ficticio").status_code == 415
    assert _upload(adm, b"<svg xmlns='http://www.w3.org/2000/svg'></svg>").status_code == 415
    assert _upload(adm, b"").status_code == 422
    assert _upload(adm, PNG + b"\x00" * (1024 * 1024)).status_code == 413
    assert adm.get("/api/clinic/logo").status_code == 404  # nada quedó guardado


def test_logo_belongs_to_its_clinic_and_can_be_removed(world, login, db):
    adm = login(world.admin_a)
    assert _upload(adm, PNG).status_code == 200
    assert login(world.admin_b).get("/api/clinic/logo").status_code == 404  # la otra clínica no lo ve
    r = adm.delete("/api/clinic/logo")
    assert r.status_code == 200 and r.json()["logo_updated_at"] is None
    assert adm.get("/api/clinic/logo").status_code == 404
    assert adm.delete("/api/clinic/logo").status_code == 404
    actions = db.scalars(select(AuditEvent.action).where(AuditEvent.actor_id == world.admin_a.id)).all()
    assert "clinic.logo_remove" in actions
