"""Compresión gzip: la interfaz y los datos viajan comprimidos (cargan más rápido por
internet), salvo las respuestas de inicio de sesión, que llevan el token CSRF."""

from fastapi.testclient import TestClient

from app.main import app
from tests.conftest import PASSWORD


def test_api_lists_are_compressed_but_login_is_not(world, login):
    client = TestClient(app)
    r = client.post("/api/auth/login", json={"email": "admin@a.test", "password": PASSWORD},
                    headers={"Accept-Encoding": "gzip"})
    assert r.status_code == 200 and "content-encoding" not in r.headers  # lleva el token CSRF
    admin = login(world.admin_a)
    for i in range(30):  # suficientes pacientes para superar el tamaño mínimo
        admin.post("/api/patients", json={"first_name": f"Comp{i}", "last_name": "Ficticio",
                                          "affiliation": "private"})
    r = admin.get("/api/patients", headers={"Accept-Encoding": "gzip"})
    assert r.status_code == 200 and r.headers.get("content-encoding") == "gzip"
    assert len(r.json()) >= 30  # el cliente lo descomprime sin problemas
    assert r.headers["cache-control"] == "no-store"  # las cabeceras de seguridad siguen
