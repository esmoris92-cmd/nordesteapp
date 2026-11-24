"""Espacio de profesional independiente: el dueño lo da de alta desde /sistema con una sola
cuenta (el profesional titular), que atiende como cualquier profesional y además carga sus
pacientes y los datos del consultorio. No puede crear cuentas ni sucursales. Datos ficticios."""

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.main import app
from app.models import (
    AccessLevel, Branch, Clinic, ClinicKind, PatientAccess, Role, Specialty, User, UserBranch,
)
from tests.conftest import PASSWORD, _PW_HASH
from tests.test_dueno_sistema import _ready_owner

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
OCTET = {"Content-Type": "application/octet-stream"}
NEW_PATIENT = {"first_name": "Nina", "last_name": "Ficticia", "affiliation": "private"}


def _independent_space(db) -> tuple[Clinic, User, Branch]:
    """Un espacio independiente armado como lo deja el alta de /sistema."""
    clinic = Clinic(name="Consultorio Demo (prueba)", kind=ClinicKind.independent.value,
                    disabled_features=["caja", "bps", "avisos"])
    db.add(clinic)
    db.flush()
    branch = Branch(clinic_id=clinic.id, name="Consultorio")
    specialty = Specialty(clinic_id=clinic.id, name="Fonoaudiología", is_active=True)
    db.add_all([branch, specialty])
    db.flush()
    titular = User(clinic_id=clinic.id, email="titular@independiente.test", full_name="Titular Ficticia",
                   role=Role.professional.value, specialty_id=specialty.id, password_hash=_PW_HASH)
    db.add(titular)
    db.flush()
    db.add(UserBranch(user_id=titular.id, branch_id=branch.id, clinic_id=clinic.id))
    db.commit()
    return clinic, titular, branch


def test_owner_creates_an_independent_space(world, db, capsys):
    owner, _ = _ready_owner(db, capsys)
    body = {"kind": "independent", "name": "Consultorio Lic. Ejemplo", "admin_full_name": "Lic. Ejemplo Ficticia",
            "admin_email": "Lic@Ejemplo.TEST", "admin_document": "1.234.567-2"}
    r = owner.post("/api/owner/clinics", body)
    assert r.status_code == 422  # falta la profesión
    r = owner.post("/api/owner/clinics", {**body, "profession": "Psicopedagogía"})
    assert r.status_code == 201, r.text
    data = r.json()
    assert data["clinic"]["kind"] == "independent" and data["clinic"]["branches"] == 1
    # El titular aparece donde el dueño ve a los administradores (para darle soporte).
    assert [a["email"] for a in data["clinic"]["admins"]] == ["lic@ejemplo.test"]
    temp = data["admin"]["temporary_password"]

    clinic = db.scalar(select(Clinic).where(Clinic.name == "Consultorio Lic. Ejemplo"))
    assert clinic.kind == "independent"
    assert sorted(clinic.disabled_features) == ["avisos", "bps", "caja"]
    branch = db.scalar(select(Branch).where(Branch.clinic_id == clinic.id))
    assert branch.name == "Consultorio"
    specialties = db.scalars(select(Specialty).where(Specialty.clinic_id == clinic.id)).all()
    assert [s.name for s in specialties] == ["Psicopedagogía"]
    titular = db.scalar(select(User).where(User.clinic_id == clinic.id))
    assert titular.role == "professional" and titular.specialty_id == specialties[0].id
    assert db.scalar(select(UserBranch.branch_id).where(UserBranch.user_id == titular.id)) == branch.id

    # Entra con la contraseña temporal: la sesión dice que es un espacio independiente.
    client = TestClient(app)
    r = client.post("/api/auth/login", json={"email": "lic@ejemplo.test", "password": temp})
    assert r.status_code == 200, r.text
    session = r.json()
    assert session["clinic"]["kind"] == "independent"
    assert session["user"]["role"] == "professional" and session["user"]["must_change_password"]
    assert set(session["clinic"]["features"]) == {"informe_mensual", "objetivos", "archivos"}
    assert session["active_branch"]["name"] == "Consultorio"  # una sola: se elige sola

    # Una clínica común sigue igual.
    r = owner.post("/api/owner/clinics", {"name": "Centro Común", "admin_full_name": "Admin Común Ficticio",
                                          "admin_email": "admin@comun.test", "admin_document": "2.345.678-3"})
    assert r.status_code == 201 and r.json()["clinic"]["kind"] == "clinic"
    common = db.scalar(select(Clinic).where(Clinic.name == "Centro Común"))
    assert common.disabled_features == [] and db.scalar(
        select(Branch.name).where(Branch.clinic_id == common.id)) == "Central"


def test_titular_loads_patients_and_is_always_responsible(world, db, login):
    clinic, titular, branch = _independent_space(db)
    client = login(titular)
    # Aunque mande otro responsable (ni siquiera de su espacio), queda él.
    r = client.post("/api/patients", json={**NEW_PATIENT, "responsible_professional_id": str(world.lucia.id)})
    assert r.status_code == 201, r.text
    created = r.json()
    assert created["branch_id"] == str(branch.id)
    access = db.scalar(select(PatientAccess).where(PatientAccess.patient_id == created["id"]))
    assert access.user_id == titular.id and access.level == AccessLevel.responsible.value
    # Lo ve en su lista y puede escribir su historia clínica y editar sus datos.
    items = client.get("/api/patients").json()
    assert [p["id"] for p in items] == [created["id"]]
    detail = client.get(f"/api/patients/{created['id']}").json()
    assert detail["can_view_clinical"] and detail["can_edit"]
    assert client.patch(f"/api/patients/{created['id']}", json={"phone": "099 000 000"}).status_code == 200
    # Nada de otra clínica.
    assert client.get(f"/api/patients/{world.patient_a.id}").status_code == 404


def test_titular_edits_the_consultorio_and_its_logo(world, db, login):
    clinic, titular, _ = _independent_space(db)
    client = login(titular)
    r = client.patch("/api/clinic", json={"name": "Consultorio Renombrado", "phone": "2900 0000"})
    assert r.status_code == 200 and r.json()["name"] == "Consultorio Renombrado"
    r = client.post("/api/clinic/logo", content=PNG, headers=OCTET)
    assert r.status_code == 200 and r.json()["logo_updated_at"]
    assert client.delete("/api/clinic/logo").status_code == 200
    db.expire_all()
    assert db.get(Clinic, clinic.id).name == "Consultorio Renombrado"
    assert db.get(Clinic, world.clinic_a.id).name == "Clínica A (prueba)"  # la otra no se tocó


def test_titular_cannot_create_accounts_or_branches(world, db, login):
    _, titular, branch = _independent_space(db)
    client = login(titular)
    account = {"email": "otra@independiente.test", "full_name": "Otra Ficticia", "role": "reception",
               "document_number": "3333333-3", "password": PASSWORD, "branch_ids": [str(branch.id)]}
    assert client.post("/api/users", json=account).status_code == 403
    assert client.post("/api/branches", json={"name": "Otra sede"}).status_code == 403
    assert client.get("/api/branches").status_code == 403
    # Las funciones apagadas para el espacio no responden.
    assert client.get("/api/cash/today").status_code == 403


def test_clinic_professionals_keep_their_limits(world, login):
    """En una clínica común nada cambia: el profesional no carga pacientes ni toca la clínica."""
    lucia = login(world.lucia)
    assert lucia.post("/api/patients", json=NEW_PATIENT).status_code == 403
    assert lucia.patch("/api/clinic", json={"name": "No"}).status_code == 403
    assert lucia.post("/api/clinic/logo", content=PNG, headers=OCTET).status_code == 403


def test_owner_resets_the_titular_password(world, db, capsys):
    owner, _ = _ready_owner(db, capsys)
    clinic, titular, _ = _independent_space(db)
    r = owner.post(f"/api/owner/clinics/{clinic.id}/admins/{titular.id}/reset-password")
    assert r.status_code == 200, r.text
    temp = r.json()["temporary_password"]
    r = TestClient(app).post("/api/auth/login", json={"email": titular.email, "password": temp})
    assert r.status_code == 200
    # Los profesionales de una clínica común siguen sin poder restablecerse desde /sistema.
    assert owner.post(
        f"/api/owner/clinics/{world.clinic_a.id}/admins/{world.lucia.id}/reset-password").status_code == 404


# ---------- Fase 2: BPS y AYEX, auditoría, exportar e importar ----------

AYEX_PATIENT = {"first_name": "Teo", "last_name": "Ficticio", "affiliation": "ayex",
                "ayex_expires_on": "2030-12-31", "document_number": "4.567.890-1"}


def test_titular_uses_bps_and_ayex_only_when_enabled(world, db, login):
    clinic, titular, _ = _independent_space(db)
    client = login(titular)
    pid = client.post("/api/patients", json=AYEX_PATIENT).json()["id"]
    # Empieza apagado: ni Cronograma ni formulario AYEX ni Pagos BPS.
    assert client.get("/api/bps-schedule").status_code == 403
    assert client.get(f"/api/patients/{pid}/ayex-form").status_code == 403
    # El dueño habilita "BPS y AYEX" para el espacio.
    clinic.disabled_features = ["caja", "avisos"]
    db.commit()
    client = login(titular)
    r = client.get("/api/bps-schedule")
    assert r.status_code == 200 and r.content[:2] == b"PK"  # un .xlsx
    r = client.get(f"/api/patients/{pid}/ayex-form")
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf"
    # Pagos BPS: puede usarlo (sin arancel cargado, avisa que falta).
    r = client.post("/api/bps-payments/check", content=b"%PDF-1.4 ficticio", headers=OCTET)
    assert r.status_code == 409
    # En una clínica común, el profesional sigue sin poder.
    assert login(world.lucia).post("/api/bps-payments/check", content=b"%PDF-1.4 ficticio",
                                   headers=OCTET).status_code == 403


def test_titular_sees_the_audit_of_his_space_only(world, db, login):
    _, titular, _ = _independent_space(db)
    client = login(titular)
    client.post("/api/patients", json=NEW_PATIENT)
    login(world.admin_a).get(f"/api/patients/{world.patient_a.id}")  # algo en la otra clínica
    r = client.get("/api/audit")
    assert r.status_code == 200, r.text
    events = r.json()
    assert any(e["action"] == "patient.create" and e["patient_name"] == "Ficticia, Nina" for e in events)
    assert all(e["patient_name"] != "Prueba, Ana" for e in events)
    people = client.get("/api/audit/people").json()
    assert [p["full_name"] for p in people] == ["Titular Ficticia"]
    # Un profesional de una clínica común no ve la auditoría.
    assert login(world.lucia).get("/api/audit").status_code == 403


def test_titular_exports_and_imports_patients(world, db, login):
    _, titular, branch = _independent_space(db)
    client = login(titular)
    client.post("/api/patients", json=NEW_PATIENT)
    r = client.get("/api/patient-export")
    assert r.status_code == 200 and r.content[:2] == b"PK"
    assert client.get("/api/patient-import/template").status_code == 200
    # El responsable del archivo (de otra clínica) no cuenta: queda el titular, sin error.
    csv = ("documento;primer_nombre;primer_apellido;tipo_afiliacion;profesional_responsable\n"
           "5.123.456-7;Lola;Ficticia;Privado;lucia@a.test\n")
    url = "/api/patient-import"
    r = client.post(f"{url}?dry_run=true", content=csv.encode(), headers=OCTET)
    assert r.status_code == 200, r.text
    row = r.json()["rows"][0]
    assert row["status"] == "ok" and row["responsible_name"] == "Titular Ficticia"
    r = client.post(f"{url}?dry_run=false", content=csv.encode(), headers=OCTET)
    assert r.status_code == 200 and r.json()["created"] == 1
    imported = next(p for p in client.get("/api/patients").json() if p["first_name"] == "Lola")
    assert imported["branch_id"] == str(branch.id)
    access = db.scalar(select(PatientAccess).where(PatientAccess.patient_id == imported["id"]))
    assert access.user_id == titular.id and access.level == AccessLevel.responsible.value
    # Un profesional de una clínica común sigue sin poder exportar ni importar.
    lucia = login(world.lucia)
    assert lucia.get("/api/patient-export").status_code == 403
    assert lucia.post(f"{url}?dry_run=true", content=csv.encode(), headers=OCTET).status_code == 403
