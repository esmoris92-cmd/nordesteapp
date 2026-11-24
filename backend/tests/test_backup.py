"""Copias de seguridad: crear, verificar (restaurando de verdad), detectar daños y restaurar.

Todo ocurre sobre la base de pruebas y carpetas temporales; nunca sobre datos reales.
"""

import io
import json
import os
import stat
import tarfile
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import func, select

from app import backup
from app.config import BACKEND_DIR, get_settings
from app.models import Patient
from tests.conftest import TEST_URL


@pytest.fixture
def backup_env(tmp_path, monkeypatch):
    """Carpeta de copias temporal; al terminar, la base de pruebas vuelve a tener sus tablas."""
    monkeypatch.setenv("BACKUP_DIR", str(tmp_path / "copias"))
    monkeypatch.setenv("FILES_DIR", str(tmp_path / "adjuntos"))
    get_settings.cache_clear()
    yield tmp_path / "copias"
    get_settings.cache_clear()
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    cfg.set_main_option("sqlalchemy.url", TEST_URL.replace("%", "%%"))
    command.upgrade(cfg, "head")


def _add_file(name: str, content: bytes) -> None:
    files_dir = Path(get_settings().files_dir)
    files_dir.mkdir(parents=True, exist_ok=True)
    (files_dir / name).write_bytes(content)


def test_create_and_verify_roundtrip(world, backup_env):
    _add_file("adjunto-ficticio", b"%PDF-1.4 ficticio")
    archive = backup.create_backup()
    assert archive.parent == backup_env and archive.name.startswith("medflow-copia-")
    assert stat.S_IMODE(archive.stat().st_mode) == 0o600
    assert stat.S_IMODE(backup_env.stat().st_mode) == 0o700

    manifest = backup.verify_backup(archive, target_url=TEST_URL)
    assert manifest["tablas"]["patients"] == 2
    assert manifest["tablas"]["users"] == 6
    assert "adjunto-ficticio" in manifest["archivos"]
    assert manifest["version_base"]
    assert backup.latest_backup() == archive


def _rewrite(archive: Path, change) -> Path:
    """Copia el .tar.gz aplicando un cambio a sus miembros (para simular daños)."""
    out = archive.with_name("modificada.tar.gz")
    with tarfile.open(archive, "r:gz") as src, tarfile.open(out, "w:gz") as dst:
        for m in src.getmembers():
            data = src.extractfile(m).read() if m.isfile() else None
            m, data = change(m, data)
            dst.addfile(m, io.BytesIO(data) if data is not None else None)
    return out


def test_damaged_or_malicious_copies_are_rejected(world, backup_env):
    archive = backup.create_backup()

    def corrupt(m, data):
        if m.name.endswith("base.dump"):
            data = data[:-10] + b"0123456789"
        return m, data
    with pytest.raises(backup.BackupError, match="dañada"):
        backup.verify_backup(_rewrite(archive, corrupt), target_url=TEST_URL)

    def escape(m, data):
        if m.name.endswith("manifiesto.json"):
            m.name = "../fuera.json"
        return m, data
    with pytest.raises(backup.BackupError, match="rutas no permitidas"):
        backup.verify_backup(_rewrite(archive, escape), target_url=TEST_URL)

    truncated = archive.with_name("cortada.tar.gz")
    truncated.write_bytes(archive.read_bytes()[: archive.stat().st_size // 2])
    with pytest.raises(backup.BackupError):
        backup.verify_backup(truncated, target_url=TEST_URL)


def test_restore_returns_to_backup_state_and_keeps_previous(world, backup_env, db):
    _add_file("original", b"contenido original")
    archive = backup.create_backup()
    # Cambios posteriores a la copia.
    db.add(Patient(clinic_id=world.clinic_a.id, first_name="Nuevo", last_name="Despues", affiliation="private", branch_id=world.branch_a.id,
                   created_by=world.admin_a.id))
    db.commit()
    _add_file("posterior", b"agregado despues")
    db.close()

    safety, set_aside = backup.restore_backup(archive, confirmed=True)

    with get_settings_session() as session:
        assert session.scalar(select(func.count()).select_from(Patient)) == 2
    files_dir = Path(get_settings().files_dir)
    assert sorted(p.name for p in files_dir.iterdir()) == ["original"]
    assert set_aside is not None and (set_aside / "posterior").exists()  # no se borró nada
    assert safety.exists() and safety.name.startswith("medflow-antes-de-restaurar-")
    with pytest.raises(backup.BackupError):
        backup.restore_backup(archive)  # sin confirmación no hace nada


def get_settings_session():
    from app.db import get_sessionmaker
    return get_sessionmaker()()


def test_command_line(world, backup_env, monkeypatch, capsys):
    assert backup.main(["crear"]) == 0
    out = capsys.readouterr().out
    assert "✅ Copia creada" in out and "2 pacientes" in out
    assert "PGPASSWORD" not in out and "postgresql" not in out  # nunca muestra la conexión

    archive = backup.latest_backup()
    monkeypatch.setattr(backup, "_server_running", lambda port=8000: False)
    monkeypatch.setattr("builtins.input", lambda prompt="": "no")
    assert backup.main(["restaurar", str(archive)]) == 1
    assert "Cancelado" in capsys.readouterr().out

    monkeypatch.setattr(backup, "_server_running", lambda port=8000: True)
    assert backup.main(["restaurar", str(archive)]) == 1
    assert "en funcionamiento" in capsys.readouterr().err


def test_backups_never_inside_the_project(world, backup_env):
    with pytest.raises(backup.BackupError, match="dentro de la carpeta del proyecto"):
        backup.create_backup(folder=BACKEND_DIR / "storage" / "copias")


def test_keep_only_latest_copies(world, backup_env):
    backup_env.mkdir(parents=True, exist_ok=True)
    for day in range(1, 6):
        (backup_env / f"medflow-copia-2026-09-0{day}_030000.tar.gz").write_bytes(b"x")
    (backup_env / "medflow-antes-de-restaurar-2026-09-01_100000.tar.gz").write_bytes(b"x")
    (backup_env / "otro-archivo.txt").write_text("no tocar")
    removed = backup.prune_backups(3)
    assert sorted(p.name for p in removed) == ["medflow-copia-2026-09-01_030000.tar.gz",
                                               "medflow-copia-2026-09-02_030000.tar.gz"]
    left = sorted(p.name for p in backup_env.iterdir())
    assert left == ["medflow-antes-de-restaurar-2026-09-01_100000.tar.gz",
                    "medflow-copia-2026-09-03_030000.tar.gz", "medflow-copia-2026-09-04_030000.tar.gz",
                    "medflow-copia-2026-09-05_030000.tar.gz", "otro-archivo.txt"]
    assert backup.main(["crear", "--conservar", "2"]) == 0
    assert len(list(backup_env.glob("medflow-copia-*.tar.gz"))) == 2
