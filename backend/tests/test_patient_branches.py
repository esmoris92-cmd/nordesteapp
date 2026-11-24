"""Pacientes por sucursal: recepción ve los de su sucursal más los privados de todas;
AYEX y militar solo en su sucursal; filtro, paginación, importación y exportación."""

import io
import zipfile

from fastapi.testclient import TestClient

from app.main import app
from tests.conftest import PASSWORD


def _client(email, branch_id=None):
    c = TestClient(app)
    r = c.post("/api/auth/login", json={"email": email, "password": PASSWORD})
    assert r.status_code == 200, r.text
    c.headers["X-CSRF-Token"] = r.json()["csrf_token"]
    if branch_id:
        assert c.post("/api/auth/branch", json={"branch_id": branch_id}).status_code == 200
    return c


def _setup(world, login):
    """Clínica A con Central y Pando; recepción de Pando; pacientes de prueba en cada una."""
    admin = login(world.admin_a)
    pando = admin.post("/api/branches", json={"name": "Pando"}).json()["id"]
    central = str(world.branch_a.id)
    r = admin.post("/api/users", json={
        "email": "recepcion.pando@a.test", "full_name": "Recepción Pando", "role": "reception",
        "document_number": "1.111.111-1", "branch_ids": [pando]})
    assert r.status_code == 201, r.text
    # La cuenta nueva entra con la contraseña temporal y la cambia (obligatorio al primer ingreso).
    temporary = r.json()["temporary_password"]
    first = TestClient(app)
    r = first.post("/api/auth/login", json={"email": "recepcion.pando@a.test", "password": temporary})
    assert r.status_code == 200, r.text
    r = first.post("/api/auth/change-password", headers={"X-CSRF-Token": r.json()["csrf_token"]},
                   json={"current_password": temporary, "new_password": PASSWORD})
    assert r.status_code in (200, 204), r.text
    admin_c = _client("admin@a.test", pando)
    for first, aff in (("Pia", "private"), ("Ramon", "ayex"), ("Mili", "military")):
        r = admin_c.post("/api/patients", json={"first_name": first, "last_name": "Pando",
                                                "affiliation": aff, "ayex_expires_on": "2030-12-31"})  # sin sucursal: la activa (Pando)
        assert r.status_code == 201 and r.json()["branch_id"] == pando, r.text
    admin_c.post("/api/patients", json={"first_name": "Cora", "last_name": "Central",
                                         "affiliation": "ayex", "ayex_expires_on": "2030-12-31", "branch_id": central})
    return central, pando


def _names(client, **params):
    return sorted(p["first_name"] for p in client.get("/api/patients", params=params).json())


def test_reception_sees_own_branch_plus_private(world, login):
    central, pando = _setup(world, login)
    rec_central = login(world.reception_a)
    # Central: Ana (privado) y Cora (AYEX) son de Central; Pía es privada de Pando.
    assert _names(rec_central) == ["Ana", "Cora"]
    assert _names(rec_central, branch="all") == ["Ana", "Cora", "Pia"]
    rec_pando = _client("recepcion.pando@a.test")
    assert _names(rec_pando) == ["Mili", "Pia", "Ramon"]
    assert _names(rec_pando, branch="all") == ["Ana", "Mili", "Pia", "Ramon"]  # Cora es AYEX de Central
    # Ni siquiera abriendo el paciente directamente.
    ramon = next(p for p in _client("admin@a.test", pando).get("/api/patients").json() if p["first_name"] == "Ramon")
    assert rec_central.get(f"/api/patients/{ramon['id']}").status_code == 404
    assert rec_pando.get(f"/api/patients/{ramon['id']}").json()["branch_name"] == "Pando"


def test_branch_on_create_and_update(world, login):
    central, pando = _setup(world, login)
    rec_central = login(world.reception_a)
    r = rec_central.post("/api/patients", json={"first_name": "X", "last_name": "Y",
                                                "affiliation": "ayex", "ayex_expires_on": "2030-12-31", "branch_id": pando})
    assert r.status_code == 422  # recepción de Central no carga pacientes en Pando
    admin = _client("admin@a.test", central)
    pid = admin.post("/api/patients", json={"first_name": "Mover", "last_name": "Ficticio",
                                            "affiliation": "ayex", "ayex_expires_on": "2030-12-31"}).json()["id"]
    assert rec_central.patch(f"/api/patients/{pid}", json={"branch_id": pando}).status_code == 422
    assert admin.patch(f"/api/patients/{pid}", json={"branch_id": pando}).status_code == 200
    assert rec_central.get(f"/api/patients/{pid}").status_code == 404  # ahora es de Pando
    assert admin.patch(f"/api/patients/{pid}", json={"branch_id": None}).status_code == 422


def test_admin_filters_and_professional_sees_own_patients(world, login):
    central, pando = _setup(world, login)
    admin = _client("admin@a.test", central)
    assert _names(admin) == ["Ana", "Cora"]  # por defecto: la sucursal activa
    assert _names(admin, branch=pando) == ["Mili", "Pia", "Ramon"]
    assert len(_names(admin, branch="all")) == 5
    # Profesional: ve a sus pacientes estén en la sucursal que estén.
    lucia = login(world.lucia)
    assert _names(lucia) == ["Ana"]


def test_pagination(world, login):
    admin = login(world.admin_a)
    for i in range(7):
        admin.post("/api/patients", json={"first_name": f"P{i}", "last_name": f"Pag{i:02d}",
                                          "affiliation": "private"})
    r = admin.get("/api/patients", params={"page_size": 3})
    assert r.headers["X-Total-Count"] == "8" and len(r.json()) == 3
    seen = []
    for page in (1, 2, 3):
        seen += [p["id"] for p in admin.get("/api/patients", params={"page_size": 3, "page": page}).json()]
    assert len(seen) == 8 and len(set(seen)) == 8
    assert admin.get("/api/patients", params={"page_size": 500}).status_code == 422


def test_import_and_export_with_branch(world, login):
    central, pando = _setup(world, login)
    rec_central = login(world.reception_a)
    csv = ("primer_nombre;primer_apellido;tipo_afiliacion;sucursal\n"
           "Uno;Importado;Privado;\n"           # sin sucursal: la activa (Central)
           "Dos;Importado;AYEX;Central\n"
           "Tres;Importado;AYEX;Pando\n")       # Pando no es de esta recepción
    r = rec_central.post("/api/patient-import?dry_run=false", content=csv.encode(),
                         headers={"Content-Type": "application/octet-stream"})
    data = r.json()
    assert data["created"] == 2
    assert "Sucursal no encontrada" in " ".join(data["rows"][2]["errors"])
    assert {r["branch_name"] for r in data["rows"][:2]} == {"Central"}
    content = _client("admin@a.test", pando).get("/api/patient-export").content
    with zipfile.ZipFile(io.BytesIO(content)) as zf:
        sheet = zf.read("xl/worksheets/sheet1.xml").decode()
    assert "sucursal" in sheet and "Pando" in sheet and "Central" not in sheet
