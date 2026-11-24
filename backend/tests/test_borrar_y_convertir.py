"""Desde /sistema: borrar todos los datos de una clínica que dejó Lumen (con sus candados) y
convertir un espacio independiente en clínica. Datos ficticios."""

from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from app import clinic_purge, totp
from app.config import get_settings
from app.deps import utcnow
from app.models import (
    AuditEvent, Clinic, ClinicalNote, OwnerAuditEvent, Patient, PatientFile, Role, User,
)
from tests.test_dueno_sistema import _ready_owner
from tests.test_espacio_independiente import _independent_space
from tests.test_exportacion_clinica import _export, _fill_clinic_a


def _code(secret: str, ahead: int = 1) -> str:
    """Un código del celular que todavía no se usó (el de ahora ya se usó al configurarlo)."""
    return totp.code_at(secret, totp.current_step() + ahead)


@pytest.fixture
def fake_backup(monkeypatch):
    made = []

    def _backup():
        made.append(1)
        return Path("/tmp/medflow-copia-2026-11-10_120000.tar.gz")

    monkeypatch.setattr(clinic_purge, "make_backup", _backup)
    return made


def _rows_of(db, clinic_id) -> dict[str, int]:
    tables = db.scalars(text(
        "SELECT table_name FROM information_schema.columns WHERE table_schema = 'public' "
        "AND column_name = 'clinic_id' AND table_name <> 'clinics' AND table_name NOT LIKE 'owner\\_%'")).all()
    counts = {t: db.execute(text(f'SELECT count(*) FROM "{t}" WHERE clinic_id = :c'), {"c": clinic_id}).scalar_one()
              for t in tables}
    return {t: n for t, n in counts.items() if n}


def _suspend_days_ago(db, clinic, days):
    db.execute(text("UPDATE clinics SET suspended_at = :t WHERE id = :id"),
               {"t": utcnow() - timedelta(days=days), "id": clinic.id})
    db.commit()


def test_purge_needs_every_lock(world, db, capsys, fake_backup):
    owner, secret = _ready_owner(db, capsys)
    a = world.clinic_a
    url = f"/api/owner/clinics/{a.id}/purge"
    ok = {"confirm_text": f"BORRAR {a.name}", "code": _code(secret), "reason": "La clínica no quiere sus datos"}
    status = owner.get(f"/api/owner/clinics/{a.id}/purge-status").json()
    assert status["blockers"] and status["min_days"] == 30
    assert owner.post(url, ok).status_code == 409  # no está suspendida
    assert owner.post(f"/api/owner/clinics/{a.id}/suspend", {"reason": "Fin del contrato"}).status_code == 200
    assert owner.post(url, ok).status_code == 409  # suspendida hace menos de 30 días
    assert owner.get(f"/api/owner/clinics/{a.id}/purge-status").json()["days_left"] in (29, 30)
    _suspend_days_ago(db, a, 31)
    assert owner.get(f"/api/owner/clinics/{a.id}/purge-status").json()["blockers"] == []
    assert owner.post(url, {**ok, "reason": ""}).status_code == 422  # sin exportación ni motivo
    assert owner.post(url, {**ok, "confirm_text": a.name}).status_code == 422  # falta "BORRAR"
    wrong = "000000" if ok["code"] != "000000" else "111111"
    assert owner.post(url, {**ok, "code": wrong}).status_code == 422
    assert fake_backup == []  # todavía no se hizo nada
    assert db.scalar(select(func.count()).select_from(Patient).where(Patient.clinic_id == a.id)) == 1


def test_purge_deletes_everything_of_the_clinic_and_nothing_else(world, db, capsys, fake_backup):
    _fill_clinic_a(db, world)
    owner, secret = _ready_owner(db, capsys)
    a = world.clinic_a
    files_dir = Path(get_settings().files_dir)
    keys = db.scalars(select(PatientFile.storage_key).where(PatientFile.clinic_id == a.id)).all()
    b_before = _rows_of(db, world.clinic_b.id)
    assert owner.post(f"/api/owner/clinics/{a.id}/suspend", {"reason": "Fin"}).status_code == 200
    # Exportación después de suspenderla: entonces no hace falta motivo.
    assert _export(owner, a).status_code == 200
    _suspend_days_ago(db, a, 31)
    r = owner.post(f"/api/owner/clinics/{a.id}/purge", {"confirm_text": f"borrar  {a.name.upper()}",
                                                        "code": _code(secret)})
    assert r.status_code == 200, r.text
    cert = r.json()
    counts = {c["label"]: c["count"] for c in cert["counts"]}
    assert counts["Pacientes"] == 1 and counts["Notas de historia clínica"] == 4
    assert counts["Cuentas de usuario"] == 4 and cert["backup_name"].startswith("medflow-copia-")
    assert fake_backup == [1]

    db.expire_all()
    assert _rows_of(db, a.id) == {}  # nada de A en ninguna tabla
    assert _rows_of(db, world.clinic_b.id) == b_before  # B intacta
    clinic = db.get(Clinic, a.id)
    assert clinic.purged_at is not None and clinic.name == a.name and clinic.phone is None
    for key in keys:
        assert not (files_dir / key).exists()
    # Los candados de solo-agregar siguen prendidos para todos.
    note_b = db.scalar(select(ClinicalNote).where(ClinicalNote.clinic_id == world.clinic_b.id))
    with pytest.raises(DBAPIError):
        db.execute(text("DELETE FROM clinical_notes WHERE id = :id"), {"id": note_b.id})
    db.rollback()
    with pytest.raises(DBAPIError):
        db.execute(text("DELETE FROM audit_log WHERE clinic_id = :c"), {"c": world.clinic_b.id})
    db.rollback()

    event = db.scalar(select(OwnerAuditEvent).where(OwnerAuditEvent.action == "owner.clinic_purge"))
    assert event.clinic_id == a.id and event.details["patients"] == 1
    listed = {c["name"]: c for c in owner.get("/api/owner/clinics").json()}[a.name]
    assert listed["purged_at"] and listed["users"] == 0 and listed["active_patients"] == 0
    assert owner.get(f"/api/owner/clinics/{a.id}/purge-certificate").json()["clinic_name"] == a.name
    # Ya no se puede reactivar, exportar ni borrar de nuevo.
    assert owner.post(f"/api/owner/clinics/{a.id}/reactivate").status_code == 409
    assert owner.post(f"/api/owner/clinics/{a.id}/export",
                      {"reason": "Prueba", "confirm_name": a.name}).status_code == 409
    assert owner.post(f"/api/owner/clinics/{a.id}/purge", {"confirm_text": f"BORRAR {a.name}",
                                                           "code": _code(secret, 0)}).status_code == 409
    # El nombre queda libre para una clínica nueva.
    r = owner.post("/api/owner/clinics", {"name": a.name, "admin_full_name": "Admin Nueva",
                                          "admin_email": "nueva@a.test", "admin_document": "1.234.567-2"})
    assert r.status_code == 201, r.text


def test_nothing_is_deleted_if_the_backup_fails(world, db, capsys, monkeypatch):
    def broken():
        raise RuntimeError("disco lleno (prueba)")
    monkeypatch.setattr(clinic_purge, "make_backup", broken)
    owner, secret = _ready_owner(db, capsys)
    a = world.clinic_a
    assert owner.post(f"/api/owner/clinics/{a.id}/suspend", {"reason": "Fin"}).status_code == 200
    _suspend_days_ago(db, a, 40)
    before = _rows_of(db, a.id)
    r = owner.post(f"/api/owner/clinics/{a.id}/purge", {"confirm_text": f"BORRAR {a.name}", "code": _code(secret),
                                                        "reason": "No pidió sus datos"})
    assert r.status_code == 409 and "copia de seguridad" in r.json()["detail"]
    db.expire_all()
    assert _rows_of(db, a.id) == before and db.get(Clinic, a.id).purged_at is None


def test_convert_an_independent_space_into_a_clinic(world, db, capsys):
    clinic, titular, _ = _independent_space(db)
    owner, _ = _ready_owner(db, capsys)
    url = f"/api/owner/clinics/{clinic.id}/convert-to-clinic"
    body = {"admin_full_name": "Admin Ficticia", "admin_email": "admin@consultorio.test",
            "admin_document": "1.234.567-2", "enable_features": True, "confirm_name": clinic.name}
    assert owner.post(url, {**body, "confirm_name": "Otro"}).status_code == 422
    assert owner.post(url, {**body, "admin_email": titular.email}).status_code == 409  # otro correo
    assert owner.post(f"/api/owner/clinics/{world.clinic_a.id}/convert-to-clinic",
                      {**body, "confirm_name": world.clinic_a.name}).status_code == 409  # ya es clínica
    r = owner.post(url, body)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["clinic"]["kind"] == "clinic" and data["admin"]["temporary_password"]
    db.expire_all()
    converted = db.get(Clinic, clinic.id)
    assert converted.kind == "clinic" and converted.disabled_features == []
    admin = db.scalar(select(User).where(User.email == "admin@consultorio.test"))
    assert admin.role == Role.admin.value and admin.must_change_password and admin.clinic_id == clinic.id
    assert db.get(User, titular.id).role == Role.professional.value  # el profesional sigue igual
    assert db.scalar(select(AuditEvent).where(AuditEvent.action == "system.clinic_converted")).clinic_id == clinic.id
    assert db.scalar(select(OwnerAuditEvent).where(OwnerAuditEvent.action == "owner.clinic_convert"))
    assert owner.post(url, body).status_code == 409  # ya se convirtió


def test_convert_can_keep_features_off(world, db, capsys):
    clinic, _, _ = _independent_space(db)
    owner, _ = _ready_owner(db, capsys)
    r = owner.post(f"/api/owner/clinics/{clinic.id}/convert-to-clinic", {
        "admin_full_name": "Admin Ficticia", "admin_email": "admin2@consultorio.test",
        "admin_document": "1.234.567-2", "enable_features": False, "confirm_name": clinic.name})
    assert r.status_code == 200, r.text
    db.expire_all()
    assert sorted(db.get(Clinic, clinic.id).disabled_features) == ["avisos", "bps", "caja"]
