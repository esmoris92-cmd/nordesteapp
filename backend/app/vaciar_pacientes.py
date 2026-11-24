"""Borra TODOS los pacientes de la base LOCAL, para dejar Nordeste limpio antes de mostrarlo.

Uso (mejor con el script, que usa el entorno virtual):
    bash scripts/vaciar-pacientes.sh

Qué borra: los pacientes y todo lo que depende de ellos (turnos, historia clínica, objetivos,
informes, archivos adjuntos, responsables o tutores, instituciones educativas, accesos) y el
registro de auditoría.
Qué conserva: la clínica, las sucursales, las especialidades, los usuarios y sus horarios.

Por seguridad:
* No funciona con ENVIRONMENT=production (un servidor con datos reales).
* No funciona si Nordeste está encendido (hay que detenerlo con Ctrl + C).
* Antes de borrar hace una copia de seguridad completa en ~/MedFlow-copias, que se puede
  restaurar con:  bash scripts/copia-seguridad.sh restaurar <archivo>
* Pide escribir BORRAR PACIENTES para confirmar.

La historia clínica, los informes, los accesos, los archivos y la auditoría están protegidos
para que no se borren fila por fila; este comando vacía esas tablas completas (TRUNCATE).
"""

import sys
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError

from app.backup import BackupError, _server_running, create_backup
from app.config import get_settings

# Todas las tablas que guardan datos de pacientes (o apuntan a ellos). El orden no importa:
# se vacían juntas en una sola instrucción.
PATIENT_TABLES = (
    "audit_log", "goal_updates", "treatment_goals", "reports", "patient_files",
    "clinical_notes", "anamnesis_versions", "report_section_versions", "appointments", "patient_access", "patient_guardians",
    "patient_institutions", "patients",
)
CONFIRMATION = "BORRAR PACIENTES"

_LABELS = {
    "patients": "pacientes", "appointments": "turnos", "clinical_notes": "notas de historia clínica",
    "treatment_goals": "objetivos", "goal_updates": "avances de objetivos", "reports": "informes",
    "patient_files": "archivos adjuntos", "patient_guardians": "responsables o tutores",
    "patient_access": "accesos de profesionales", "audit_log": "registros de auditoría",
    "patient_institutions": "instituciones educativas",
    "anamnesis_versions": "versiones de anamnesis",
    "report_section_versions": "antecedentes, diagnóstico, encuadre y abordajes",
}


def _counts(conn) -> dict[str, int]:
    return {t: conn.execute(text(f"SELECT count(*) FROM {t}")).scalar_one() for t in PATIENT_TABLES}


def main(argv: list[str] | None = None) -> int:
    settings = get_settings()
    if settings.is_production:
        print("❌ Esto es un servidor (ENVIRONMENT=production): no se borran pacientes desde aquí.")
        return 1
    if _server_running():
        print("❌ Nordeste está encendido. Detenelo (Control + C en su Terminal) y volvé a intentarlo.")
        return 1

    database = make_url(settings.database_url).database
    engine = create_engine(settings.database_url)
    try:
        with engine.connect() as conn:
            before = _counts(conn)
        if before["patients"] == 0:
            print("ℹ️  No hay pacientes en la base. No se cambió nada.")
            return 0

        print(f"Base de datos: {database}")
        print("Se van a BORRAR:")
        for table in PATIENT_TABLES:
            print(f"   · {before[table]:>6} {_LABELS[table]}")
        print("Se CONSERVAN: la clínica, las sucursales, las especialidades, los usuarios y sus horarios.")
        print("")
        print("Antes de borrar se hace una copia de seguridad completa…")
        backup = create_backup(prefix="medflow-antes-de-vaciar")
        print(f"✅ Copia guardada: {backup}")
        print("")
        answer = input(f"Escribí {CONFIRMATION} (en mayúsculas) para continuar: ")
        if answer.strip() != CONFIRMATION:
            print("Cancelado. No se borró nada (la copia de seguridad igual quedó guardada).")
            return 1

        with engine.begin() as conn:
            # Si otro programa tiene la base abierta, no esperar para siempre.
            conn.execute(text("SET LOCAL lock_timeout = '10s'"))
            keys = conn.execute(text("SELECT storage_key FROM patient_files")).scalars().all()
            conn.execute(text(f"TRUNCATE {', '.join(PATIENT_TABLES)}"))
            after = _counts(conn)

        # Archivos adjuntos en disco: solo los que pertenecían a esos pacientes.
        files_dir = Path(settings.files_dir)
        removed = 0
        for key in keys:
            path = files_dir / key
            if path.parent == files_dir and path.is_file():
                path.unlink()
                removed += 1
    except BackupError as exc:
        print(f"❌ No se pudo hacer la copia de seguridad, así que no se borró nada: {exc}")
        return 1
    except OperationalError:
        print("❌ Otro programa está usando la base de datos (¿Nordeste abierto en otra Terminal?).")
        print("   Cerralo y volvé a intentarlo. No se borró nada.")
        return 1
    finally:
        engine.dispose()

    print("")
    print(f"✅ Listo: se borraron {before['patients']} pacientes y {removed} archivos adjuntos.")
    if any(after.values()):
        print(f"⚠️  Quedaron datos en: {', '.join(t for t, n in after.items() if n)}")
    print("   Usuarios, sucursales y horarios siguen igual. Ya podés iniciar Nordeste.")
    print(f"   Para deshacerlo: bash scripts/copia-seguridad.sh restaurar {backup}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
