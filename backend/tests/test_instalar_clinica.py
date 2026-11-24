from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app import instalar_clinica
from app.main import app
from app.models import Branch, Clinic, Role, Specialty, User
from app.security import verify_password


def test_crea_clinica_sucursales_y_admin(db):
    password = instalar_clinica.install(db, "admin@nordeste.example.com", "Ana Admin")
    assert password

    clinic = db.scalars(select(Clinic)).one()
    assert clinic.name == "Centro Interdisciplinario Nordeste"
    assert clinic.timezone == "America/Montevideo"
    assert sorted(db.scalars(select(Branch.name).where(Branch.clinic_id == clinic.id))) == \
        ["Anexo", "Central", "Pando"]
    assert db.scalar(select(func.count()).select_from(Specialty)) == 3

    admin = db.scalars(select(User)).one()
    assert admin.role == Role.admin.value and admin.must_change_password
    assert verify_password(admin.password_hash, password)

    # Entra con la contraseña temporal.
    r = TestClient(app).post("/api/auth/login", json={"email": "admin@nordeste.example.com", "password": password})
    assert r.status_code == 200, r.text


def test_no_hace_nada_si_ya_hay_clinica(db):
    assert instalar_clinica.install(db, "admin@nordeste.example.com", "Ana Admin")
    assert instalar_clinica.install(db, "otro@nordeste.example.com", "Otro Admin") is None
    assert db.scalar(select(func.count()).select_from(Clinic)) == 1
    assert db.scalar(select(func.count()).select_from(User)) == 1


def test_main_rechaza_correo_invalido(capsys):
    assert instalar_clinica.main(["--correo", "no-es-un-correo"]) == 1
    assert "no válido" in capsys.readouterr().out
