"""Sucursales: permisos por cuenta, elección al entrar, cambio de sucursal, administración
de sucursales y verificación en el servidor en cada pedido."""

from fastapi.testclient import TestClient

from app.main import app
from tests.conftest import PASSWORD


def _login(email):
    client = TestClient(app)
    r = client.post("/api/auth/login", json={"email": email, "password": PASSWORD})
    assert r.status_code == 200, r.text
    client.headers["X-CSRF-Token"] = r.json()["csrf_token"]
    return client, r.json()


def _new_branch(admin, name):
    r = admin.post("/api/branches", json={"name": name})
    assert r.status_code == 201, r.text
    return r.json()


def test_single_branch_enters_directly(world, login):
    _, session = _login("recepcion@a.test")
    assert session["active_branch"]["name"] == "Central"
    assert [b["name"] for b in session["branches"]] == ["Central"]


def test_choose_and_switch_branch(world, login):
    admin = login(world.admin_a)
    pando = _new_branch(admin, "Pando")
    client, session = _login("admin@a.test")
    assert session["active_branch"] is None  # admin entra a todas: debe elegir
    assert [b["name"] for b in session["branches"]] == ["Central", "Pando"]
    r = client.get("/api/patients")
    assert r.status_code == 409 and "sucursal" in r.json()["detail"]
    assert client.get("/api/auth/me").status_code == 200  # puede ver a cuáles entra
    r = client.post("/api/auth/branch", json={"branch_id": pando["id"]})
    assert r.status_code == 200 and r.json()["active_branch"]["name"] == "Pando"
    assert client.get("/api/patients").status_code == 200
    r = client.post("/api/auth/branch", json={"branch_id": str(world.branch_a.id)})
    assert r.json()["active_branch"]["name"] == "Central"


def test_branch_permissions_are_checked_on_the_server(world, login):
    admin = login(world.admin_a)
    pando = _new_branch(admin, "Pando")
    reception, _ = _login("recepcion@a.test")
    r = reception.post("/api/auth/branch", json={"branch_id": pando["id"]})
    assert r.status_code == 403
    # Otra clínica no existe para esta cuenta.
    r = reception.post("/api/auth/branch", json={"branch_id": str(world.branch_b.id)})
    assert r.status_code == 403
    # Si administración le cambia la sucursal, la sesión pasa sola a la nueva (era la única).
    admin.patch(f"/api/users/{world.reception_a.id}", json={"branch_ids": [pando["id"]]})
    assert reception.get("/api/auth/me").json()["active_branch"]["name"] == "Pando"
    # Profesional con dos sucursales: elige al entrar.
    admin.patch(f"/api/users/{world.mateo.id}",
                json={"branch_ids": [str(world.branch_a.id), pando["id"]]})
    _, session = _login("mateo@a.test")
    assert session["active_branch"] is None and len(session["branches"]) == 2


def test_branch_administration(world, login):
    admin = login(world.admin_a)
    pando = _new_branch(admin, "Pando")
    assert admin.post("/api/branches", json={"name": "pando"}).status_code == 409  # sin repetir
    assert login(world.reception_a).post("/api/branches", json={"name": "Otra"}).status_code == 403
    r = admin.patch(f"/api/branches/{pando['id']}", json={"name": "Pando Centro"})
    assert r.status_code == 200 and r.json()["name"] == "Pando Centro"
    # Desactivar Pando: quien solo tenía Pando queda sin sucursal y no puede seguir.
    admin.patch(f"/api/users/{world.reception_a.id}", json={"branch_ids": [pando["id"]]})
    admin.patch(f"/api/branches/{pando['id']}", json={"is_active": False})
    reception, session = _login("recepcion@a.test")
    assert session["branches"] == [] and session["active_branch"] is None
    assert reception.get("/api/patients").status_code == 409
    # Debe quedar al menos una activa.
    r = admin.patch(f"/api/branches/{world.branch_a.id}", json={"is_active": False})
    assert r.status_code == 409
    assert login(world.admin_b).patch(f"/api/branches/{pando['id']}", json={"name": "Otro nombre"}).status_code == 404


def test_accounts_need_branches(world, login):
    admin = login(world.admin_a)
    base = {"email": "nueva@a.test", "full_name": "Nueva Ficticia", "role": "reception", "document_number": "2222222-2",
            "password": "contraseña-de-prueba-123"}
    assert admin.post("/api/users", json=base).status_code == 422
    r = admin.post("/api/users", json={**base, "branch_ids": [str(world.branch_b.id)]})
    assert r.status_code == 422  # sucursal de otra clínica
    r = admin.post("/api/users", json={**base, "branch_ids": [str(world.branch_a.id)]})
    assert r.status_code == 201 and r.json()["branch_ids"] == [str(world.branch_a.id)]
    # Administración entra a todas: no guarda lista.
    r = admin.patch(f"/api/users/{r.json()['id']}", json={"role": "admin"})
    assert r.status_code == 200 and r.json()["branch_ids"] == []
    r = admin.patch(f"/api/users/{r.json()['id']}", json={"role": "reception"})
    assert r.status_code == 422  # al dejar de ser admin necesita sucursal
