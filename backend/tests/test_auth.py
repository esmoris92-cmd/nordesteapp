"""Inicio de sesión, sesiones, CSRF y contraseñas."""

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.main import app
from app.models import AuditEvent, AuthSession, User
from tests.conftest import PASSWORD


def test_login_ok_and_me(world, login):
    client = login(world.lucia)
    r = client.get("/api/auth/me")
    assert r.status_code == 200
    body = r.json()
    assert body["user"]["email"] == "lucia@a.test"
    assert body["clinic"]["name"] == "Clínica A (prueba)"
    assert "password_hash" not in body["user"]


def test_cookie_flags(world):
    http = TestClient(app)
    r = http.post("/api/auth/login", json={"email": "lucia@a.test", "password": PASSWORD})
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie
    assert "samesite=strict" in cookie
    assert "path=/api" in cookie


def test_wrong_password_and_unknown_email_get_same_message(world):
    http = TestClient(app)
    r1 = http.post("/api/auth/login", json={"email": "lucia@a.test", "password": "incorrecta"})
    r2 = http.post("/api/auth/login", json={"email": "nadie@a.test", "password": "incorrecta"})
    assert r1.status_code == r2.status_code == 401
    assert r1.json()["detail"] == r2.json()["detail"]


def test_lockout_after_repeated_failures(world):
    http = TestClient(app)
    for _ in range(5):
        http.post("/api/auth/login", json={"email": "lucia@a.test", "password": "incorrecta"})
    r = http.post("/api/auth/login", json={"email": "lucia@a.test", "password": PASSWORD})
    assert r.status_code == 401  # bloqueada aunque la contraseña sea correcta


def test_passwords_and_tokens_are_not_stored_in_plain_text(world, login, db):
    client = login(world.lucia)
    user = db.scalar(select(User).where(User.email == "lucia@a.test"))
    assert user.password_hash.startswith("$argon2id$")
    session = db.scalar(select(AuthSession).where(AuthSession.user_id == user.id))
    cookie_value = client.http.cookies.get("medflow_session")
    assert session.token_hash != cookie_value and len(session.token_hash) == 64


def test_write_without_csrf_is_rejected(world, login):
    client = login(world.reception_a)
    r = client.http.post("/api/patients", json={"first_name": "X", "last_name": "Y"})
    assert r.status_code == 403
    r = client.http.post("/api/patients", json={"first_name": "X", "last_name": "Y"},
                         headers={"X-CSRF-Token": "falso"})
    assert r.status_code == 403


def test_logout_invalidates_session(world, login):
    client = login(world.lucia)
    token = client.http.cookies.get("medflow_session")
    assert client.post("/api/auth/logout").status_code == 204
    assert client.get("/api/auth/me").status_code == 401
    # Aunque alguien hubiera copiado la cookie, el servidor ya no la acepta.
    stolen = TestClient(app, cookies={"medflow_session": token})
    assert stolen.get("/api/auth/me").status_code == 401


def test_deactivated_user_loses_access(world, login):
    lucia = login(world.lucia)
    admin = login(world.admin_a)
    r = admin.patch(f"/api/users/{world.lucia.id}", json={"is_active": False})
    assert r.status_code == 200
    assert lucia.get("/api/auth/me").status_code == 401
    http = TestClient(app)
    r = http.post("/api/auth/login", json={"email": "lucia@a.test", "password": PASSWORD})
    assert r.status_code == 401


def test_requests_without_session_are_rejected(world):
    http = TestClient(app)
    for url in ("/api/patients", "/api/auth/me", "/api/audit"):
        assert http.get(url).status_code == 401


def test_login_is_audited(world, login, db):
    login(world.lucia)
    actions = db.scalars(select(AuditEvent.action).where(AuditEvent.actor_id == world.lucia.id)).all()
    assert "auth.login" in actions


def test_change_password_policy(world, login):
    client = login(world.lucia)
    r = client.post("/api/auth/change-password",
                    json={"current_password": PASSWORD, "new_password": "corta"})
    assert r.status_code == 422
    r = client.post("/api/auth/change-password",
                    json={"current_password": PASSWORD, "new_password": "una-clave-nueva-larga"})
    assert r.status_code == 204
