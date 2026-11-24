"""Restablecer contraseña desde administración: contraseña temporal mostrada una vez,
cambio obligatorio al entrar, sesiones cerradas, desbloqueo y auditoría sin la clave."""

from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.deps import utcnow
from app.main import app
from app.models import AuditEvent, User
from tests.conftest import PASSWORD


def _login(email: str, password: str):
    client = TestClient(app)
    r = client.post("/api/auth/login", json={"email": email, "password": password})
    return client, r


def test_reset_forces_change_before_using_medflow(world, login, db):
    lucia = login(world.lucia)
    admin = login(world.admin_a)
    r = admin.post(f"/api/users/{world.lucia.id}/reset-password")
    assert r.status_code == 200
    temporary = r.json()["temporary_password"]
    assert len(temporary) == 19

    assert lucia.get("/api/auth/me").status_code == 401  # sesiones anteriores cerradas
    assert _login("lucia@a.test", PASSWORD)[1].status_code == 401  # la clave vieja ya no sirve

    client, r = _login("lucia@a.test", temporary)
    assert r.status_code == 200 and r.json()["user"]["must_change_password"] is True
    csrf = {"X-CSRF-Token": r.json()["csrf_token"]}
    # Hasta cambiarla no puede usar el resto de MedFlow.
    r = client.get("/api/patients")
    assert r.status_code == 403 and "contraseña temporal" in r.json()["detail"]
    assert client.get("/api/auth/me").status_code == 200
    # La nueva debe ser distinta de la temporal.
    r = client.post("/api/auth/change-password", headers=csrf,
                    json={"current_password": temporary, "new_password": temporary})
    assert r.status_code == 422
    r = client.post("/api/auth/change-password", headers=csrf,
                    json={"current_password": temporary, "new_password": "Nueva-clave-ficticia-2026"})
    assert r.status_code == 204
    assert client.get("/api/patients").status_code == 200
    assert client.get("/api/auth/me").json()["user"]["must_change_password"] is False

    # La contraseña nunca queda en la auditoría.
    for details in db.scalars(select(AuditEvent.details)).all():
        assert temporary not in str(details)
    assert "user.password_reset" in db.scalars(select(AuditEvent.action)).all()


def test_reset_unlocks_and_permissions(world, login, db):
    user = db.get(User, world.mateo.id)
    user.failed_login_count = 5
    user.locked_until = utcnow() + timedelta(minutes=15)
    db.commit()
    admin = login(world.admin_a)
    temporary = admin.post(f"/api/users/{world.mateo.id}/reset-password").json()["temporary_password"]
    assert _login("mateo@a.test", temporary)[1].status_code == 200  # ya no está bloqueado

    assert login(world.reception_a).post(f"/api/users/{world.mateo.id}/reset-password").status_code == 403
    assert admin.post(f"/api/users/{world.admin_a.id}/reset-password").status_code == 409
    assert login(world.admin_b).post(f"/api/users/{world.mateo.id}/reset-password").status_code == 404
