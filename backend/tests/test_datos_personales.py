"""Datos personales de cada cuenta: C.I. obligatoria (sin repetir en la clínica) y teléfono.
Cada persona los cambia en "Mi cuenta"; Administración, en Usuarios."""

from sqlalchemy import select

from app.models import AuditEvent


def test_each_user_edits_own_personal_data(world, login, db):
    for account in (world.reception_a, world.lucia, world.admin_a):
        client = login(account)
        me = client.get("/api/auth/me").json()["user"]
        assert me["document_number"] is None  # cuentas creadas antes: la completan
        r = client.patch("/api/account", json={"full_name": f"{account.full_name} Editado",
                                               "document_number": f"{account.full_name[:1]}1.234.56{account.email[0]}",
                                               "phone": "099 000 111"})
        # (las C.I. de este ejemplo son distintas para cada cuenta)
        assert r.status_code == 200, r.text
        assert r.json()["full_name"].endswith("Editado") and r.json()["phone"] == "099 000 111"
        assert client.get("/api/auth/me").json()["user"]["document_number"] is not None
    # Solo datos personales: el rol o el correo no se cambian por aquí (se ignoran).
    lucia = login(world.lucia)
    r = lucia.patch("/api/account", json={"role": "admin", "email": "otra@a.test"})
    assert r.status_code == 200 and r.json()["role"] == "professional" and r.json()["email"] == world.lucia.email
    # La C.I. no se puede borrar y el teléfono sí.
    assert lucia.patch("/api/account", json={"document_number": None}).status_code == 422
    assert lucia.patch("/api/account", json={"document_number": "  "}).status_code == 422
    assert lucia.patch("/api/account", json={"phone": None}).json()["phone"] is None
    assert "account.update" in db.scalars(select(AuditEvent.action)).all()


def test_ci_required_and_unique(world, login):
    admin = login(world.admin_a)
    base = {"email": "nueva@a.test", "full_name": "Nueva Ficticia", "role": "reception",
            "password": "contraseña-de-prueba-123", "branch_ids": [str(world.branch_a.id)]}
    r = admin.post("/api/users", json=base)
    assert r.status_code == 422  # falta la C.I.
    r = admin.post("/api/users", json={**base, "document_number": "1.234.567-8", "phone": "099 111 222"})
    assert r.status_code == 201 and r.json()["document_number"] == "1.234.567-8"
    # Repetida en la misma clínica: no (ni al crear, ni en Mi cuenta, ni editando).
    r = admin.post("/api/users", json={**base, "email": "otra@a.test", "document_number": "1.234.567-8"})
    assert r.status_code == 409 and "C.I." in r.json()["detail"]
    assert login(world.lucia).patch("/api/account", json={"document_number": "1.234.567-8"}).status_code == 409
    assert admin.patch(f"/api/users/{world.mateo.id}", json={"document_number": "1.234.567-8"}).status_code == 409
    # Administración la carga o corrige en Usuarios, y no puede borrarla.
    r = admin.patch(f"/api/users/{world.mateo.id}", json={"document_number": "9.876.543-2", "phone": "098 765 432"})
    assert r.status_code == 200 and r.json()["document_number"] == "9.876.543-2"
    assert admin.patch(f"/api/users/{world.mateo.id}", json={"document_number": None}).status_code == 422
    # Otra clínica puede tener la misma C.I. (son cuentas distintas).
    r = login(world.admin_b).patch(f"/api/users/{world.bruno.id}", json={"document_number": "1.234.567-8"})
    assert r.status_code == 200
