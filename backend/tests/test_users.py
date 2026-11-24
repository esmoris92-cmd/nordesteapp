"""Edición de cuentas por Administración: nombre, correo, rol y estado."""

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.main import app
from app.models import AuditEvent, User
from tests.conftest import PASSWORD


def _login_status(email: str) -> int:
    return TestClient(app).post("/api/auth/login",
                                json={"email": email, "password": PASSWORD}).status_code


def test_admin_edits_name_email_and_role(world, login, db):
    lucia = login(world.lucia)
    admin = login(world.admin_a)
    ot = next(sp for sp in admin.get("/api/specialties").json() if sp["name"] == "Terapia ocupacional")
    r = admin.patch(f"/api/users/{world.lucia.id}", json={
        "full_name": "Lic. Lucía Renombrada", "email": "Lucia.Nueva@A.test",
        "role": "professional", "specialty_id": ot["id"],
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["full_name"] == "Lic. Lucía Renombrada"
    assert body["email"] == "lucia.nueva@a.test"  # se guarda en minúsculas
    assert body["specialty_id"] == ot["id"] and body["specialty_name"] == "Terapia ocupacional"

    # Cambió el correo: su sesión abierta se cierra y debe entrar con el correo nuevo.
    assert lucia.get("/api/auth/me").status_code == 401
    assert _login_status("lucia@a.test") == 401
    assert _login_status("lucia.nueva@a.test") == 200

    # La auditoría registra QUÉ campos cambiaron, no los valores.
    details = db.scalars(select(AuditEvent.details).where(AuditEvent.action == "user.update")).all()
    assert any(set(d["fields"]) >= {"full_name", "email", "specialty"} for d in details)
    assert all("lucia.nueva" not in str(d) for d in details)


def test_role_change_closes_sessions(world, login):
    rec = login(world.reception_a)
    r = login(world.admin_a).patch(f"/api/users/{world.reception_a.id}", json={"role": "admin"})
    assert r.status_code == 200
    assert rec.get("/api/auth/me").status_code == 401


def test_only_name_change_keeps_sessions(world, login):
    rec = login(world.reception_a)
    r = login(world.admin_a).patch(f"/api/users/{world.reception_a.id}",
                                   json={"full_name": "Recepción Renombrada"})
    assert r.status_code == 200
    assert rec.get("/api/auth/me").status_code == 200


def test_duplicate_email_is_rejected(world, login):
    admin = login(world.admin_a)
    r = admin.patch(f"/api/users/{world.lucia.id}", json={"email": "mateo@a.test"})
    assert r.status_code == 409
    r = admin.patch(f"/api/users/{world.lucia.id}", json={"email": "no-es-un-correo"})
    assert r.status_code == 422


def test_professional_needs_specialty(world, login):
    r = login(world.admin_a).patch(f"/api/users/{world.reception_a.id}",
                                   json={"role": "professional"})
    assert r.status_code == 422


def test_admin_can_edit_own_email_but_not_demote_self(world, login):
    admin = login(world.admin_a)
    assert admin.patch(f"/api/users/{world.admin_a.id}", json={"role": "reception"}).status_code == 409
    r = admin.patch(f"/api/users/{world.admin_a.id}", json={"email": "jefa@a.test"})
    assert r.status_code == 200
    # Su propia sesión actual sigue abierta.
    assert admin.get("/api/auth/me").json()["user"]["email"] == "jefa@a.test"


def test_only_admin_can_edit_users(world, login):
    for user in (world.reception_a, world.lucia):
        r = login(user).patch(f"/api/users/{world.mateo.id}", json={"full_name": "Hack"})
        assert r.status_code == 403


def test_new_account_gets_temporary_password(world, login, db):
    """Al crear una cuenta, Nordeste genera una contraseña temporal y obliga a cambiarla."""
    admin = login(world.admin_a)
    r = admin.post("/api/users", json={
        "email": "nueva.temp@a.test", "full_name": "Nueva Temporal", "role": "reception",
        "document_number": "7.777.777-7", "branch_ids": [str(world.branch_a.id)],
        "password": "una-que-elige-administracion"})  # se ignora: ya no se elige
    assert r.status_code == 201, r.text
    temporary = r.json()["temporary_password"]
    assert len(temporary) == 19 and r.json()["must_change_password"] is True
    assert db.scalar(select(User.must_change_password).where(User.email == "nueva.temp@a.test")) is True
    http = TestClient(app)
    # La contraseña que inventó administración no sirve; la temporal sí, y obliga a cambiarla.
    assert http.post("/api/auth/login", json={"email": "nueva.temp@a.test",
                                              "password": "una-que-elige-administracion"}).status_code == 401
    r = http.post("/api/auth/login", json={"email": "nueva.temp@a.test", "password": temporary})
    assert r.status_code == 200 and r.json()["user"]["must_change_password"] is True
    # La lista de cuentas no muestra la contraseña.
    assert all("temporary_password" not in u for u in admin.get("/api/users").json())
