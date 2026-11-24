"""Copias de seguridad de Nordeste: crear, verificar y restaurar.

Uso (desde la carpeta del proyecto, con el script que activa el entorno):

    bash scripts/copia-seguridad.sh                     # crea una copia
    bash scripts/copia-seguridad.sh verificar           # prueba restaurar la última copia
    bash scripts/copia-seguridad.sh verificar ARCHIVO   # prueba restaurar esa copia
    bash scripts/copia-seguridad.sh restaurar ARCHIVO   # vuelve la base a esa copia (pide confirmación)

Cada copia es un único archivo ``medflow-copia-AAAA-MM-DD_HHMMSS.tar.gz`` con:
* ``base.dump``: toda la base de datos (formato de pg_dump).
* ``archivos/``: los archivos adjuntos de los pacientes (carpeta FILES_DIR).
* ``manifiesto.json``: fecha, versión de la base, cantidad de filas por tabla y huellas
  SHA-256 para detectar si algo se dañó.

Verificar NO toca tus datos: restaura la copia en la base de PRUEBAS (la que terminan en
"_test", que las pruebas automáticas ya borran y rellenan), cuenta las filas, las compara
con el manifiesto y deja esa base vacía.

Seguridad: la copia contiene datos de pacientes. Se guarda fuera del proyecto (nunca en
Git) con permisos solo para tu usuario. La contraseña de la base nunca se muestra.
"""

import argparse
import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import tarfile
import tempfile
from datetime import datetime
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from app.config import BACKEND_DIR, get_settings

FORMAT_VERSION = 1
ROOT = "medflow-copia"
_POSTGRES_APP_BIN = Path("/Applications/Postgres.app/Contents/Versions/latest/bin")


class BackupError(Exception):
    """Error explicado en español para mostrar tal cual."""


# ---------- Utilidades ----------


def _tool(name: str) -> str:
    found = shutil.which(name)
    if found:
        return found
    candidate = _POSTGRES_APP_BIN / name
    if candidate.exists():
        return str(candidate)
    raise BackupError(f"No encuentro '{name}'. Abrí Postgres.app y revisá la instalación (docs/INSTALACION.md).")


def _pg_env(url: str) -> dict[str, str]:
    """Datos de conexión como variables de entorno: la contraseña no aparece en pantalla."""
    u = make_url(url)
    env = os.environ.copy()
    env.update({
        "PGHOST": u.host or "localhost",
        "PGPORT": str(u.port or 5432),
        "PGUSER": u.username or "",
        "PGDATABASE": u.database or "",
    })
    if u.password:
        env["PGPASSWORD"] = u.password
    return env


def _run(cmd: list[str], url: str, what: str) -> None:
    result = subprocess.run(cmd, env=_pg_env(url), capture_output=True, text=True)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip().splitlines()
        hint = detail[-1] if detail else "sin detalle"
        raise BackupError(f"Falló {what}: {hint}")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _table_counts(url: str) -> dict[str, int]:
    engine = create_engine(url)
    try:
        with engine.connect() as conn:
            tables = conn.execute(text(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'public' AND table_type = 'BASE TABLE' ORDER BY table_name"
            )).scalars().all()
            return {t: conn.execute(text(f'SELECT count(*) FROM public."{t}"')).scalar_one() for t in tables}
    finally:
        engine.dispose()


def _reset_schema(url: str) -> None:
    """Deja la base sin tablas (borra el esquema "public" y lo vuelve a crear vacío)."""
    engine = create_engine(url)
    try:
        with engine.begin() as conn:
            conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
            conn.execute(text("CREATE SCHEMA public"))
    finally:
        engine.dispose()


def _human(size: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size} B"


def backup_dir() -> Path:
    return Path(get_settings().backup_dir).expanduser()


def latest_backup(folder: Path | None = None) -> Path:
    folder = folder or backup_dir()
    copies = sorted(folder.glob("medflow-copia-*.tar.gz"))
    if not copies:
        raise BackupError(f"No hay copias en {folder}. Creá una primero.")
    return copies[-1]


# ---------- Crear ----------


def create_backup(folder: Path | None = None, prefix: str = "medflow-copia") -> Path:
    settings = get_settings()
    url = settings.database_url
    folder = (folder or backup_dir()).expanduser()
    if folder.resolve().is_relative_to(BACKEND_DIR.parent.resolve()):
        raise BackupError("Las copias no pueden guardarse dentro de la carpeta del proyecto "
                          "(podrían terminar en GitHub). Usá otra carpeta en BACKUP_DIR.")
    folder.mkdir(parents=True, exist_ok=True)
    os.chmod(folder, 0o700)
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    final = folder / f"{prefix}-{stamp}.tar.gz"
    files_dir = Path(settings.files_dir)

    with tempfile.TemporaryDirectory(prefix="medflow-copia-") as tmp:
        work = Path(tmp) / ROOT
        work.mkdir()
        dump = work / "base.dump"
        _run([_tool("pg_dump"), "--format=custom", "--no-owner", "--no-privileges", "--file", str(dump)],
             url, "la copia de la base (pg_dump)")
        counts = _table_counts(url)

        files: dict[str, str] = {}
        target_files = work / "archivos"
        target_files.mkdir()
        if files_dir.is_dir():
            for path in sorted(files_dir.iterdir()):
                if path.is_file():
                    shutil.copy2(path, target_files / path.name)
                    files[path.name] = _sha256(path)

        manifest = {
            "formato": FORMAT_VERSION,
            "creada": datetime.now().astimezone().isoformat(timespec="seconds"),
            "base": make_url(url).database,
            "version_base": _alembic_revision(url),
            "tablas": counts,
            "base_dump_sha256": _sha256(dump),
            "archivos": files,
        }
        (work / "manifiesto.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False),
                                              encoding="utf-8")
        partial = final.with_name(final.name + ".parcial")
        with tarfile.open(partial, "w:gz") as tar:
            tar.add(work, arcname=ROOT)
        os.chmod(partial, 0o600)
        partial.rename(final)  # la copia aparece completa o no aparece
    return final


def _alembic_revision(url: str) -> str | None:
    engine = create_engine(url)
    try:
        with engine.connect() as conn:
            return conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
    except Exception:
        return None
    finally:
        engine.dispose()


def prune_backups(keep: int, folder: Path | None = None) -> list[Path]:
    """Borra las copias diarias más viejas y deja las ``keep`` más recientes.

    Solo toca archivos "medflow-copia-*.tar.gz" (nunca las de "antes de restaurar").
    """
    if keep < 1:
        raise BackupError("Hay que conservar al menos una copia.")
    folder = (folder or backup_dir()).expanduser()
    copies = sorted(folder.glob("medflow-copia-*.tar.gz"))  # el nombre lleva la fecha: orden cronológico
    old = copies[:-keep] if len(copies) > keep else []
    for path in old:
        path.unlink()
    return old


# ---------- Leer una copia ----------


def _extract(archive: Path, into: Path) -> tuple[Path, dict]:
    """Extrae la copia validando que no tenga rutas peligrosas y que nada esté dañado."""
    if not archive.is_file():
        raise BackupError(f"No existe el archivo {archive}.")
    try:
        with tarfile.open(archive, "r:gz") as tar:
            members = tar.getmembers()
            for m in members:
                parts = Path(m.name).parts
                if (m.name.startswith("/") or ".." in parts or not parts or parts[0] != ROOT
                        or not (m.isfile() or m.isdir())):
                    raise BackupError("La copia contiene rutas no permitidas; no se usará.")
            try:
                tar.extractall(into, members=members, filter="data")
            except TypeError:  # Python sin el parámetro "filter": ya validamos las rutas arriba
                tar.extractall(into, members=members)
    except (tarfile.TarError, EOFError, OSError) as exc:
        raise BackupError(f"No se pudo leer la copia (¿está incompleta o dañada?): {exc}") from None
    root = into / ROOT
    try:
        manifest = json.loads((root / "manifiesto.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise BackupError("A la copia le falta el manifiesto o está dañado.") from None
    if _sha256(root / "base.dump") != manifest.get("base_dump_sha256"):
        raise BackupError("La copia de la base está dañada (la huella SHA-256 no coincide).")
    for name, digest in manifest.get("archivos", {}).items():
        path = root / "archivos" / name
        if not path.is_file() or _sha256(path) != digest:
            raise BackupError("Un archivo adjunto de la copia falta o está dañado.")
    return root, manifest


def _restore_into(url: str, dump: Path) -> None:
    _reset_schema(url)
    _run([_tool("pg_restore"), "--no-owner", "--no-privileges", "--exit-on-error",
          "--dbname", make_url(url).database, str(dump)], url, "la restauración (pg_restore)")


# ---------- Verificar ----------


def verify_backup(archive: Path, target_url: str | None = None) -> dict:
    """Restaura la copia en la base de PRUEBAS, compara las filas y la deja vacía."""
    test_url = target_url or get_settings().test_database_url
    if not test_url:
        raise BackupError("Falta TEST_DATABASE_URL en backend/.env: se necesita para verificar.")
    if not (make_url(test_url).database or "").endswith("_test"):
        raise BackupError("Por seguridad, la base de verificación debe terminar en '_test'.")
    if target_url is None and \
            make_url(test_url).database == make_url(get_settings().database_url).database:
        raise BackupError("La base de pruebas no puede ser la misma que la base principal.")
    with tempfile.TemporaryDirectory(prefix="medflow-verificar-") as tmp:
        root, manifest = _extract(archive, Path(tmp))
        try:
            _restore_into(test_url, root / "base.dump")
            restored = _table_counts(test_url)
        finally:
            _reset_schema(test_url)  # la base de pruebas queda vacía, como antes
    expected = manifest.get("tablas", {})
    if restored != expected:
        different = sorted(t for t in set(restored) | set(expected) if restored.get(t) != expected.get(t))
        raise BackupError(f"La copia restaurada no coincide en: {', '.join(different)}.")
    return manifest


# ---------- Restaurar ----------


def _server_running(port: int = 8000) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def restore_backup(archive: Path, confirmed: bool = False) -> tuple[Path, Path | None]:
    """Vuelve la base PRINCIPAL y los adjuntos al estado de la copia.

    Antes guarda una copia de seguridad del estado actual. Los adjuntos actuales no se
    borran: se apartan en una carpeta "...antes-de-restaurar-FECHA".
    """
    if not confirmed:
        raise BackupError("Restaurar requiere confirmación.")
    settings = get_settings()
    with tempfile.TemporaryDirectory(prefix="medflow-restaurar-") as tmp:
        root, manifest = _extract(archive, Path(tmp))
        safety = create_backup(prefix="medflow-antes-de-restaurar")
        _restore_into(settings.database_url, root / "base.dump")

        files_dir = Path(settings.files_dir)
        set_aside = None
        if files_dir.exists() and any(files_dir.iterdir()):
            set_aside = files_dir.with_name(
                f"{files_dir.name}.antes-de-restaurar-{datetime.now():%Y-%m-%d_%H%M%S}")
            files_dir.rename(set_aside)
        files_dir.mkdir(parents=True, exist_ok=True)
        for path in (root / "archivos").iterdir():
            shutil.copy2(path, files_dir / path.name)
    restored = _table_counts(settings.database_url)
    if restored != manifest.get("tablas", {}):
        raise BackupError("La base restaurada no coincide con la copia. Podés volver al estado "
                          f"anterior restaurando {safety}.")
    return safety, set_aside


# ---------- Línea de comandos ----------


def _summary(manifest: dict) -> str:
    rows = sum(manifest.get("tablas", {}).values())
    patients = manifest.get("tablas", {}).get("patients", 0)
    return (f"{patients} pacientes, {rows} filas en {len(manifest.get('tablas', {}))} tablas, "
            f"{len(manifest.get('archivos', {}))} archivos adjuntos")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="copia-seguridad", description="Copias de seguridad de Nordeste.")
    sub = parser.add_subparsers(dest="accion")
    p_new = sub.add_parser("crear", help="crea una copia (acción por defecto)")
    p_new.add_argument("--conservar", type=int, metavar="N",
                       help="después de crear, deja solo las N copias más recientes (1 a 1000)")
    p_ver = sub.add_parser("verificar", help="prueba restaurar una copia en la base de pruebas")
    p_ver.add_argument("archivo", nargs="?", help="copia a verificar (por defecto, la última)")
    p_res = sub.add_parser("restaurar", help="vuelve la base principal al estado de una copia")
    p_res.add_argument("archivo", help="copia a restaurar")
    args = parser.parse_args(argv)
    action = args.accion or "crear"
    keep = getattr(args, "conservar", None)
    if keep is not None and not 1 <= keep <= 1000:
        parser.error("--conservar debe estar entre 1 y 1000")

    try:
        if action == "crear":
            print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] Creando copia de seguridad…")
            path = create_backup()
            with tempfile.TemporaryDirectory() as tmp:
                _, manifest = _extract(path, Path(tmp))
            print(f"✅ Copia creada: {path}")
            print(f"   Tamaño: {_human(path.stat().st_size)} · Contiene: {_summary(manifest)}")
            if keep is not None:
                removed = prune_backups(keep)
                if removed:
                    print(f"   Se borraron {len(removed)} copias antiguas (se conservan las {keep} más recientes).")
            print("   Para comprobar que se puede restaurar: bash scripts/copia-seguridad.sh verificar")
        elif action == "verificar":
            path = Path(args.archivo).expanduser() if args.archivo else latest_backup()
            print(f"Verificando {path} …")
            manifest = verify_backup(path)
            print(f"✅ La copia está completa y se restauró bien en la base de pruebas: {_summary(manifest)}.")
            print(f"   Creada: {manifest.get('creada')}. La base de pruebas quedó vacía otra vez.")
        elif action == "restaurar":
            path = Path(args.archivo).expanduser()
            if _server_running():
                raise BackupError("Nordeste está en funcionamiento. Detenelo (Ctrl + C en su Terminal) "
                                  "y volvé a intentarlo.")
            with tempfile.TemporaryDirectory() as tmp:
                _, manifest = _extract(path, Path(tmp))
            print(f"Vas a REEMPLAZAR la base de datos '{make_url(get_settings().database_url).database}' "
                  f"y los archivos adjuntos por el contenido de la copia del {manifest.get('creada')}:")
            print(f"   {_summary(manifest)}")
            print("Antes se guardará automáticamente una copia del estado actual.")
            answer = input('Escribí RESTAURAR (en mayúsculas) para continuar: ')
            if answer.strip() != "RESTAURAR":
                print("Cancelado. No se cambió nada.")
                return 1
            safety, set_aside = restore_backup(path, confirmed=True)
            print("✅ Restauración terminada.")
            print(f"   Copia del estado anterior: {safety}")
            if set_aside:
                print(f"   Los adjuntos anteriores quedaron apartados en: {set_aside}")
            print("   Luego ejecutá 'alembic upgrade head' por si la copia es de una versión anterior.")
        return 0
    except BackupError as exc:
        print(f"❌ {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
