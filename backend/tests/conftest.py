"""Preparación común de las pruebas.

Usa la base indicada en TEST_DATABASE_URL (debe terminar en "_test").
En cada ejecución revierte y vuelve a aplicar las migraciones (comprueba que
son reversibles) y vacía las tablas antes de cada prueba.
"""

import os
import uuid
from dataclasses import dataclass
from datetime import time

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from app.config import Settings

_settings = Settings()
TEST_URL: str = _settings.test_database_url or ""
if not TEST_URL:
    pytest.exit("Falta TEST_DATABASE_URL en backend/.env (ver .env.example).", returncode=2)
if not (make_url(TEST_URL).database or "").endswith("_test"):
    pytest.exit("Por seguridad, la base de pruebas debe terminar en '_test'.", returncode=2)

# La aplicación usará la base de pruebas.
os.environ["DATABASE_URL"] = TEST_URL
os.environ["ENVIRONMENT"] = "test"
# Los archivos de prueba van a una carpeta temporal, nunca a backend/storage.
import tempfile  # noqa: E402

os.environ["FILES_DIR"] = tempfile.mkdtemp(prefix="medflow-test-files-")

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.config import BACKEND_DIR, get_settings  # noqa: E402
from app.db import get_engine, get_sessionmaker  # noqa: E402

get_settings.cache_clear()
get_engine.cache_clear()
get_sessionmaker.cache_clear()

from app.main import app  # noqa: E402
from app.models import (  # noqa: E402
    AccessLevel,
    Availability,
    Branch,
    Clinic,
    Patient,
    PatientAccess,
    Role,
    Specialty,
    User,
    UserBranch,
)
from app.security import hash_password  # noqa: E402

PASSWORD = "contraseña-de-prueba-123"
_PW_HASH = hash_password(PASSWORD)
TABLES = (
    "cash_movements, cash_registers, owner_audit_log, owner_sessions, system_owners, audit_log, notice_recipients, notices, professional_degrees, user_branches, goal_updates, treatment_goals, reports, patient_files, report_section_versions, anamnesis_versions, clinical_notes, appointments, availability, patient_access, patient_guardians, "
    "patient_institutions, patients, auth_sessions, users, specialties, branches, clinics"
)


@pytest.fixture(scope="session", autouse=True)
def migrated_database():
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    cfg.set_main_option("sqlalchemy.url", TEST_URL.replace("%", "%%"))
    # La base de PRUEBAS puede tener datos de la corrida anterior (no se limpia al terminar).
    # Se vacía antes de revertir las migraciones: algunas reversiones fallan a propósito si
    # hay historia clínica que no entra en la regla anterior (p. ej. reportes de institución).
    engine = create_engine(TEST_URL)
    with engine.begin() as conn:
        tables = conn.execute(text(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public' AND tablename <> 'alembic_version'"
        )).scalars().all()
        if tables:
            conn.execute(text("TRUNCATE " + ", ".join(f'"{t}"' for t in tables) + " RESTART IDENTITY CASCADE"))
    engine.dispose()
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    yield


@pytest.fixture(autouse=True)
def clean_tables(migrated_database):
    engine = create_engine(TEST_URL)
    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {TABLES} RESTART IDENTITY CASCADE"))
    engine.dispose()
    yield


@pytest.fixture
def db():
    with get_sessionmaker()() as session:
        yield session


@dataclass
class World:
    clinic_a: Clinic
    clinic_b: Clinic
    admin_a: User
    reception_a: User
    lucia: User  # profesional responsable de patient_a
    mateo: User  # profesional sin acceso inicial a patient_a
    admin_b: User
    bruno: User  # profesional de la clínica B
    patient_a: Patient
    patient_b: Patient
    branch_a: Branch  # sucursal "Central" de la clínica A (la única al empezar)
    branch_b: Branch


def _make_specialty(db, clinic, name):
    sp = Specialty(clinic_id=clinic.id, name=name, is_active=True)
    db.add(sp)
    db.flush()
    return sp


def _make_user(db, clinic, email, role, specialty=None):
    u = User(clinic_id=clinic.id, email=email, full_name=email.split("@")[0].title(),
             role=role.value, specialty_id=specialty.id if specialty else None,
             password_hash=_PW_HASH)
    db.add(u)
    db.flush()
    return u


@pytest.fixture
def world(db) -> World:
    a = Clinic(name="Clínica A (prueba)")
    b = Clinic(name="Clínica B (prueba)")
    db.add_all([a, b])
    db.flush()
    psy_a = _make_specialty(db, a, "Psicología")
    ot_a = _make_specialty(db, a, "Terapia ocupacional")
    psy_b = _make_specialty(db, b, "Psicología")
    admin_a = _make_user(db, a, "admin@a.test", Role.admin)
    reception_a = _make_user(db, a, "recepcion@a.test", Role.reception)
    lucia = _make_user(db, a, "lucia@a.test", Role.professional, psy_a)
    mateo = _make_user(db, a, "mateo@a.test", Role.professional, ot_a)
    admin_b = _make_user(db, b, "admin@b.test", Role.admin)
    bruno = _make_user(db, b, "bruno@b.test", Role.professional, psy_b)
    branch_a = Branch(clinic_id=a.id, name="Central")
    branch_b = Branch(clinic_id=b.id, name="Central")
    db.add_all([branch_a, branch_b])
    db.flush()
    for u, br in ((reception_a, branch_a), (lucia, branch_a), (mateo, branch_a), (bruno, branch_b)):
        db.add(UserBranch(user_id=u.id, branch_id=br.id, clinic_id=br.clinic_id))
    pa = Patient(clinic_id=a.id, first_name="Ana", last_name="Prueba", affiliation="private",
                 created_by=reception_a.id, branch_id=branch_a.id)
    pb = Patient(clinic_id=b.id, first_name="Beto", last_name="Prueba", affiliation="ayex",
                 created_by=admin_b.id, branch_id=branch_b.id)
    db.add_all([pa, pb])
    db.flush()
    db.add_all([
        PatientAccess(clinic_id=a.id, patient_id=pa.id, user_id=lucia.id,
                      level=AccessLevel.responsible.value, granted_by=admin_a.id),
        PatientAccess(clinic_id=b.id, patient_id=pb.id, user_id=bruno.id,
                      level=AccessLevel.responsible.value, granted_by=admin_b.id),
    ])
    # Disponibilidad todos los días 08:00-20:00 (hora de la clínica).
    for prof, clinic, br in ((lucia, a, branch_a), (mateo, a, branch_a), (bruno, b, branch_b)):
        for wd in range(7):
            db.add(Availability(clinic_id=clinic.id, professional_id=prof.id, branch_id=br.id, weekday=wd,
                                start_time=time(8), end_time=time(20)))
    db.commit()
    return World(a, b, admin_a, reception_a, lucia, mateo, admin_b, bruno, pa, pb, branch_a, branch_b)


class ApiClient:
    """Cliente de pruebas con sesión iniciada y cabecera CSRF."""

    def __init__(self, email: str):
        self.http = TestClient(app)
        response = self.http.post("/api/auth/login", json={"email": email, "password": PASSWORD})
        assert response.status_code == 200, response.text
        self.csrf = response.json()["csrf_token"]

    def get(self, url, **kw):
        return self.http.get(url, **kw)

    def _write(self, method, url, **kw):
        headers = {"X-CSRF-Token": self.csrf, **kw.pop("headers", {})}
        return self.http.request(method, url, headers=headers, **kw)

    def post(self, url, **kw):
        return self._write("POST", url, **kw)

    def patch(self, url, **kw):
        return self._write("PATCH", url, **kw)

    def delete(self, url, **kw):
        return self._write("DELETE", url, **kw)


@pytest.fixture
def login():
    def _login(user: User) -> ApiClient:
        return ApiClient(user.email)

    return _login


def new_id() -> str:
    return str(uuid.uuid4())


def workday(days_ahead: int = 7, after=None):
    """Un día hábil para dar turnos en las pruebas: ``days_ahead`` días después de hoy (o un día
    después de ``after``), salteando el domingo (la clínica no atiende ese día)."""
    from datetime import date, timedelta
    d = (after + timedelta(days=1)) if after is not None else date.today() + timedelta(days=days_ahead)
    return d + timedelta(days=1) if d.weekday() == 6 else d
