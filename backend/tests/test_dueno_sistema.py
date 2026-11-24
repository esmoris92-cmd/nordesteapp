"""Dueño del sistema: cuenta aparte con código del celular, alta y suspensión de clínicas,
recuperar el acceso del administrador, y que NUNCA vea pacientes. Datos ficticios."""

import re

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from app import dueno_sistema, totp
from app.main import app
from app.models import Branch, Clinic, OwnerAuditEvent, Specialty, SystemOwner, User
from tests.conftest import PASSWORD, ApiClient

OWNER_EMAIL = "duena@lumen.test"
NEW_PASSWORD = "clave-nueva-del-dueno-123"


def _temp_password(capsys) -> str:
    out = capsys.readouterr().out
    return re.search(r"Contraseña temporal:\s+(\S+)", out).group(1)


class OwnerClient:
    def __init__(self):
        self.http = TestClient(app)
        self.csrf = ""

    def login(self, email, password, code=""):
        r = self.http.post("/api/owner/auth/login", json={"email": email, "password": password, "code": code})
        if r.status_code == 200:
            self.csrf = r.json()["csrf_token"]
        return r

    def get(self, url):
        return self.http.get(url)

    def post(self, url, json=None):
        return self.http.post(url, json=json or {}, headers={"X-CSRF-Token": self.csrf})


def _ready_owner(db, capsys) -> tuple[OwnerClient, str]:
    """Crea la cuenta con el comando, entra, cambia la contraseña y activa el código."""
    dueno_sistema.crear(OWNER_EMAIL, "Dueña Ficticia")
    temp = _temp_password(capsys)
    owner = OwnerClient()
    r = owner.login(OWNER_EMAIL, temp)
    assert r.status_code == 200, r.text
    assert r.json()["owner"]["must_change_password"] is True
    assert owner.get("/api/owner/clinics").status_code == 403  # todavía no está lista
    assert owner.post("/api/owner/auth/totp/start").status_code == 409  # primero la contraseña
    r = owner.post("/api/owner/auth/change-password",
                   {"current_password": temp, "new_password": NEW_PASSWORD})
    assert r.status_code == 204, r.text
    assert owner.get("/api/owner/clinics").status_code == 403  # falta el código
    start = owner.post("/api/owner/auth/totp/start").json()
    secret = start["secret"].replace(" ", "")
    assert start["uri"].startswith("otpauth://totp/Lumen:") and secret in start["uri"]
    bad = owner.post("/api/owner/auth/totp/confirm", {"code": "000000" if totp.code_at(secret, totp.current_step()) != "000000" else "111111"})
    assert bad.status_code == 422
    r = owner.post("/api/owner/auth/totp/confirm", {"code": totp.code_at(secret, totp.current_step())})
    assert r.status_code == 204, r.text
    assert owner.get("/api/owner/clinics").status_code == 200
    return owner, secret


def test_totp_matches_rfc_6238():
    secret = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"  # "12345678901234567890" en base32
    assert totp.code_at(secret, 59 // 30) == "287082"
    assert totp.code_at(secret, 1111111109 // 30) == "081804"
    assert totp.code_at(secret, 1234567890 // 30) == "005924"
    assert totp.verify(secret, "005 924", None, now=1234567890) == 1234567890 // 30
    assert totp.verify(secret, "005924", 1234567890 // 30, now=1234567890) is None  # ya usado
    assert totp.verify(secret, "12345", None, now=1234567890) is None


def test_owner_login_needs_code_and_codes_are_single_use(world, db, capsys):
    owner, secret = _ready_owner(db, capsys)
    used = db.scalar(select(SystemOwner.totp_last_step).where(SystemOwner.email == OWNER_EMAIL))
    assert owner.post("/api/owner/auth/logout").status_code == 204
    assert owner.get("/api/owner/clinics").status_code == 401

    again = OwnerClient()
    assert again.login(OWNER_EMAIL, NEW_PASSWORD).status_code == 401                         # sin código
    assert again.login(OWNER_EMAIL, NEW_PASSWORD, totp.code_at(secret, used)).status_code == 401  # repetido
    assert again.login(OWNER_EMAIL, "otra-clave-equivocada", totp.code_at(secret, used + 1)).status_code == 401
    r = again.login(OWNER_EMAIL, NEW_PASSWORD, totp.code_at(secret, used + 1))
    assert r.status_code == 200, r.text
    assert r.json()["owner"] == {"email": OWNER_EMAIL, "full_name": "Dueña Ficticia",
                                 "must_change_password": False, "totp_enabled": True}
    actions = set(db.scalars(select(OwnerAuditEvent.action)).all())
    assert {"owner.created", "owner.login", "owner.login_failed", "owner.password_changed",
            "owner.totp_enabled", "owner.logout"} <= actions


def test_owner_lockout_after_failed_attempts(world, db, capsys):
    _, secret = _ready_owner(db, capsys)
    client = OwnerClient()
    for _ in range(5):
        assert client.login(OWNER_EMAIL, "equivocada-equivocada").status_code == 401
    good = totp.code_at(secret, totp.current_step() + 1)
    assert client.login(OWNER_EMAIL, NEW_PASSWORD, good).status_code == 401  # bloqueada


def test_clinic_and_owner_sessions_are_separate(world, db, capsys, login):
    owner, _ = _ready_owner(db, capsys)
    admin = login(world.admin_a)
    assert admin.get("/api/owner/clinics").status_code == 401
    assert admin.post("/api/owner/clinics", json={}).status_code == 401
    assert owner.get("/api/patients").status_code == 401
    assert owner.get("/api/auth/me").status_code == 401
    # Una cuenta de clínica no sirve para entrar como dueño.
    assert OwnerClient().login(world.admin_a.email, PASSWORD).status_code == 401
    # Sin la cabecera CSRF no se puede cambiar nada.
    r = owner.http.post(f"/api/owner/clinics/{world.clinic_a.id}/suspend", json={})
    assert r.status_code == 403


def test_clinic_list_shows_counts_but_never_patients(world, db, capsys):
    owner, _ = _ready_owner(db, capsys)
    r = owner.get("/api/owner/clinics")
    assert r.status_code == 200
    clinics = {c["name"]: c for c in r.json()}
    a = clinics["Clínica A (prueba)"]
    assert (a["branches"], a["users"], a["active_patients"]) == (1, 4, 1)
    assert [x["email"] for x in a["admins"]] == ["admin@a.test"]
    assert a["suspended_at"] is None and a["last_activity"] is None
    # Ningún dato de pacientes: ni nombres ni documentos.
    assert "Ana" not in r.text and "Beto" not in r.text
    assert set(a) == {"id", "name", "kind", "created_at", "suspended_at", "purged_at", "branches", "users",
                      "active_patients",
                      "paused_patients", "paused_with_sessions", "last_activity", "admins"}  # solo cantidades
    assert a["kind"] == "clinic"  # tipo de espacio (clínica o profesional independiente)


def test_create_clinic_with_its_first_admin(world, db, capsys):
    owner, _ = _ready_owner(db, capsys)
    body = {"name": "Centro Ejemplo", "admin_full_name": "Admin Ejemplo Ficticio",
            "admin_email": "Admin@Ejemplo.TEST", "admin_document": "1.234.567-2"}
    r = owner.post("/api/owner/clinics", body)
    assert r.status_code == 201, r.text
    data = r.json()
    assert data["clinic"]["name"] == "Centro Ejemplo" and data["clinic"]["branches"] == 1
    assert data["admin"]["email"] == "admin@ejemplo.test"
    temp = data["admin"]["temporary_password"]

    clinic = db.scalar(select(Clinic).where(Clinic.name == "Centro Ejemplo"))
    assert db.scalar(select(Branch.name).where(Branch.clinic_id == clinic.id)) == "Central"
    assert len(db.scalars(select(Specialty).where(Specialty.clinic_id == clinic.id)).all()) == 3
    # El administrador entra con la contraseña temporal, la cambia y ve la auditoría.
    client = TestClient(app)
    r = client.post("/api/auth/login", json={"email": "admin@ejemplo.test", "password": temp})
    assert r.status_code == 200 and r.json()["user"]["must_change_password"] is True
    csrf = r.json()["csrf_token"]
    assert client.post("/api/auth/change-password", headers={"X-CSRF-Token": csrf},
                       json={"current_password": temp, "new_password": "una-clave-del-admin-1"}).status_code == 204
    events = client.get("/api/audit").json()
    created = [e for e in events if e["action"] == "system.clinic_create"]
    assert created and created[0]["actor_name"] == "Soporte de Lumen"

    assert owner.post("/api/owner/clinics", {**body, "admin_email": "otro@ejemplo.test"}).status_code == 409
    assert owner.post("/api/owner/clinics", {**body, "name": "Otra", "admin_email": "admin@a.test"}).status_code == 409


def test_suspend_blocks_the_whole_clinic_and_reactivate(world, db, capsys, login):
    owner, _ = _ready_owner(db, capsys)
    admin_a = login(world.admin_a)
    lucia = login(world.lucia)
    admin_b = login(world.admin_b)
    r = owner.post(f"/api/owner/clinics/{world.clinic_a.id}/suspend", {"reason": "Prueba de suspensión"})
    assert r.status_code == 200 and r.json()["suspended_at"]
    for client in (admin_a, lucia):
        r = client.get("/api/patients")
        assert r.status_code == 401
    # Al entrar con la contraseña correcta se explica; con una incorrecta, no se revela nada.
    r = TestClient(app).post("/api/auth/login", json={"email": world.admin_a.email, "password": PASSWORD})
    assert r.status_code == 403 and "suspendido" in r.json()["detail"]
    r = TestClient(app).post("/api/auth/login", json={"email": world.admin_a.email, "password": "incorrecta-123"})
    assert r.status_code == 401 and "suspendido" not in r.json()["detail"]
    assert admin_b.get("/api/patients").status_code == 200  # la otra clínica sigue igual
    assert owner.post(f"/api/owner/clinics/{world.clinic_a.id}/suspend").status_code == 409

    assert owner.post(f"/api/owner/clinics/{world.clinic_a.id}/reactivate").status_code == 200
    assert login(world.admin_a).get("/api/patients").status_code == 200
    reason = db.scalar(select(OwnerAuditEvent.details).where(OwnerAuditEvent.action == "owner.clinic_suspend"))
    assert reason == {"reason": "Prueba de suspensión", "count": 2}


def test_reset_admin_password_only_for_admins(world, db, capsys, login):
    owner, _ = _ready_owner(db, capsys)
    world.admin_b.is_active = False
    world.admin_b.failed_login_count = 3
    db.commit()
    url = f"/api/owner/clinics/{world.clinic_b.id}/admins/{world.admin_b.id}/reset-password"
    r = owner.post(url)
    assert r.status_code == 200, r.text
    temp = r.json()["temporary_password"]
    db.expire_all()
    admin_b = db.get(User, world.admin_b.id)
    assert admin_b.is_active and admin_b.must_change_password and admin_b.failed_login_count == 0
    r = TestClient(app).post("/api/auth/login", json={"email": world.admin_b.email, "password": temp})
    assert r.status_code == 200
    # Profesionales no, y el administrador tiene que ser de esa clínica.
    assert owner.post(f"/api/owner/clinics/{world.clinic_b.id}/admins/{world.bruno.id}/reset-password").status_code == 404
    assert owner.post(f"/api/owner/clinics/{world.clinic_b.id}/admins/{world.admin_a.id}/reset-password").status_code == 404
    audit = owner.get("/api/owner/audit").json()
    reset = next(e for e in audit if e["action"] == "owner.admin_password_reset")
    assert reset["clinic_name"] == "Clínica B (prueba)" and reset["target_name"] == world.admin_b.full_name
    assert reset["details"] == {"is_active": True}


def test_owner_audit_is_append_only(world, db, capsys):
    _ready_owner(db, capsys)
    with pytest.raises(DBAPIError):
        db.execute(text("UPDATE owner_audit_log SET action = 'x'"))
    db.rollback()
    with pytest.raises(DBAPIError):
        db.execute(text("DELETE FROM owner_audit_log"))
    db.rollback()


def test_command_reset_clears_the_phone_code(world, db, capsys):
    owner, _ = _ready_owner(db, capsys)
    with pytest.raises(SystemExit):
        dueno_sistema.crear(OWNER_EMAIL, "Repetida")
    dueno_sistema.restablecer(OWNER_EMAIL)
    temp = _temp_password(capsys)
    assert owner.get("/api/owner/clinics").status_code == 401  # se cerraron las sesiones
    db.expire_all()
    account = db.scalar(select(SystemOwner).where(SystemOwner.email == OWNER_EMAIL))
    assert not account.totp_enabled and account.totp_secret is None and account.must_change_password
    r = OwnerClient().login(OWNER_EMAIL, temp)  # sin código: hay que configurarlo de nuevo
    assert r.status_code == 200 and r.json()["owner"]["totp_enabled"] is False
    dueno_sistema.listar()
    assert "SIN código del celular" in capsys.readouterr().out
