"""Vaciar pacientes de la base local: copia previa, confirmación escrita, conserva usuarios y
sucursales, borra los archivos adjuntos de esos pacientes y se niega en un servidor."""

from pathlib import Path

from sqlalchemy import func, select

from app import vaciar_pacientes
from app.config import get_settings
from app.models import Appointment, Branch, Patient, PatientFile, User
from tests.test_backup import backup_env  # noqa: F401  (fixture: copias y adjuntos temporales)


def _count(db, model):
    db.expire_all()
    n = db.scalar(select(func.count()).select_from(model))
    db.rollback()  # cierra la transacción: si no, el vaciado (TRUNCATE) espera sus bloqueos
    return n


def test_wipes_patients_and_keeps_the_rest(world, db, backup_env, monkeypatch):  # noqa: F811
    monkeypatch.setattr(vaciar_pacientes, "_server_running", lambda: False)
    files_dir = Path(get_settings().files_dir)
    files_dir.mkdir(parents=True, exist_ok=True)
    db.add(PatientFile(clinic_id=world.clinic_a.id, patient_id=world.patient_a.id, uploaded_by=world.lucia.id,
                       original_name="ficticio.pdf", content_type="application/pdf", size_bytes=3,
                       sha256="0" * 64, storage_key="clave-ficticia"))
    db.commit()
    (files_dir / "clave-ficticia").write_bytes(b"pdf")
    (files_dir / "otro").write_bytes(b"no es de un paciente")
    users, branches = _count(db, User), _count(db, Branch)

    # Respuesta equivocada: no borra nada (pero la copia queda hecha).
    monkeypatch.setattr("builtins.input", lambda _: "si")
    assert vaciar_pacientes.main() == 1
    assert _count(db, Patient) == 2 and len(list(backup_env.glob("medflow-antes-de-vaciar-*"))) == 1

    monkeypatch.setattr("builtins.input", lambda _: "BORRAR PACIENTES")
    assert vaciar_pacientes.main() == 0
    assert (_count(db, Patient), _count(db, PatientFile), _count(db, Appointment)) == (0, 0, 0)
    assert (_count(db, User), _count(db, Branch)) == (users, branches)
    assert sorted(p.name for p in files_dir.iterdir()) == ["otro"]
    assert vaciar_pacientes.main() == 0  # sin pacientes: no hace nada


def test_refuses_on_a_server_or_while_running(world, backup_env, monkeypatch):  # noqa: F811
    monkeypatch.setattr(vaciar_pacientes, "_server_running", lambda: True)
    assert vaciar_pacientes.main() == 1
    monkeypatch.setenv("ENVIRONMENT", "production")
    get_settings.cache_clear()
    assert vaciar_pacientes.main() == 1
