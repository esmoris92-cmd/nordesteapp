"""Borrar TODOS los datos de una clínica (o espacio independiente) que dejó de usar Nordeste.

Lo hace solo el dueño del sistema, desde /sistema (``routers/owner_lifecycle.py``), con varios
candados que se controlan allá (clínica suspendida hace al menos 30 días, exportación entregada
o motivo, confirmación escrita y código del celular). Acá está el borrado en sí:

1. **Copia de seguridad completa** antes de tocar nada (la misma de las copias nocturnas). Si la
   copia falla, no se borra nada.
2. En **una sola operación** de la base se borran todas las filas de esa clínica, tabla por tabla.
   Las tablas de historia clínica, informes, accesos, archivos, objetivos, caja y auditoría tienen
   disparadores que impiden borrar filas (son de "solo agregar"): se apagan por un instante
   **solo dentro de esta operación** (``ALTER TABLE … DISABLE TRIGGER USER``) y se vuelven a
   prender antes de terminarla. Mientras dura, esas tablas quedan reservadas para esta operación;
   si algo falla, la base vuelve exactamente a como estaba (y los disparadores siguen prendidos).
3. Se comprueba que no quedó **ninguna** fila de esa clínica en ninguna tabla con ``clinic_id``
   (si una tabla nueva no estuviera en la lista, la operación se cancela entera).
4. La fila de la clínica queda solo con su nombre y fechas (``purged_at``): la auditoría del dueño
   la nombra. Se borran sus datos de contacto, logo y datos del BPS.
5. Recién con la base confirmada se borran del disco los adjuntos y títulos de esa clínica.

Los datos siguen existiendo en las copias de seguridad anteriores hasta que se renuevan (14 en el
servidor, 30 en la Mac): eso se informa en la constancia.
"""

import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app import backup
from app.config import get_settings
from app.deps import utcnow
from app.models import Clinic, PatientFile, ProfessionalDegree

# Orden de borrado: primero lo que apunta a otras filas, al final lo que es apuntado.
PURGE_ORDER = (
    "notice_recipients", "notices", "cash_movements", "cash_registers", "goal_updates", "treatment_goals",
    "reports", "patient_files", "report_section_versions", "anamnesis_versions", "clinical_notes",
    "appointments", "availability", "patient_access", "patient_guardians", "patient_institutions",
    "audit_log", "patients", "professional_degrees", "auth_sessions", "user_branches", "users",
    "specialties", "branches",
)
# Tablas protegidas con disparadores de "solo agregar" o "no se borra".
PROTECTED = ("clinical_notes", "audit_log", "reports", "patient_access", "patient_files", "treatment_goals",
             "goal_updates", "cash_registers", "cash_movements")

LABELS = {
    "patients": "Pacientes", "patient_guardians": "Responsables o tutores",
    "patient_institutions": "Instituciones educativas", "patient_access": "Accesos de profesionales",
    "appointments": "Turnos", "clinical_notes": "Notas de historia clínica",
    "anamnesis_versions": "Versiones de anamnesis",
    "report_section_versions": "Antecedentes, diagnóstico, encuadre y abordajes", "reports": "Informes",
    "treatment_goals": "Objetivos", "goal_updates": "Avances de objetivos",
    "patient_files": "Archivos adjuntos (registros)", "professional_degrees": "Títulos profesionales (registros)",
    "notices": "Avisos", "notice_recipients": "Destinatarios de avisos", "cash_registers": "Cajas",
    "cash_movements": "Movimientos de caja", "availability": "Horarios de profesionales",
    "audit_log": "Registros de auditoría", "auth_sessions": "Sesiones de ingreso",
    "user_branches": "Sucursales de cada cuenta", "users": "Cuentas de usuario",
    "specialties": "Especialidades", "branches": "Sucursales",
}
_IDENT = re.compile(r"^[a-z_][a-z0-9_]*$")


class PurgeError(Exception):
    """Error explicado en español (se muestra tal cual)."""


@dataclass
class PurgeResult:
    purged_at: datetime
    backup_name: str
    counts: dict[str, int] = field(default_factory=dict)
    files_deleted: int = 0
    files_not_found: int = 0
    files_failed: int = 0
    pending_keys: list[str] = field(default_factory=list, repr=False)  # archivos a borrar del disco


def make_backup() -> Path:
    """Copia de seguridad completa (se reemplaza en las pruebas automáticas)."""
    return backup.create_backup()


def _clinic_tables(db: Session) -> list[str]:
    return db.scalars(text(
        "SELECT table_name FROM information_schema.columns WHERE table_schema = 'public' "
        "AND column_name = 'clinic_id' AND table_name <> 'clinics' AND table_name NOT LIKE 'owner\\_%' "
        "ORDER BY table_name")).all()


def purge_clinic(db: Session, clinic: Clinic) -> PurgeResult:
    """Borra todos los datos de la clínica. Quien llama controla los candados y la auditoría
    del dueño, y hace el commit final (la fila de la clínica y la auditoría van juntas)."""
    try:
        copy = make_backup()
    except Exception as exc:  # sin copia no se borra nada
        raise PurgeError("No se pudo hacer la copia de seguridad previa, así que no se borró nada. "
                         f"Detalle: {exc}") from exc

    cid = clinic.id
    keys = [k for (k,) in db.execute(select(PatientFile.storage_key).where(PatientFile.clinic_id == cid))]
    keys += [k for (k,) in db.execute(select(ProfessionalDegree.storage_key)
                                      .where(ProfessionalDegree.clinic_id == cid))]
    counts: dict[str, int] = {}
    try:
        for table in PROTECTED:
            db.execute(text(f'ALTER TABLE "{table}" DISABLE TRIGGER USER'))
        for table in PURGE_ORDER:
            counts[table] = db.execute(text(f'DELETE FROM "{table}" WHERE clinic_id = :cid'),
                                       {"cid": cid}).rowcount
        for table in PROTECTED:
            db.execute(text(f'ALTER TABLE "{table}" ENABLE TRIGGER USER'))
        left = []
        for table in _clinic_tables(db):
            if not _IDENT.match(table):
                continue
            if db.execute(text(f'SELECT 1 FROM "{table}" WHERE clinic_id = :cid LIMIT 1'), {"cid": cid}).first():
                left.append(table)
        if left:
            raise PurgeError("Quedaron datos de la clínica en: " + ", ".join(left)
                             + ". No se borró nada (hay que agregar esas tablas al borrado).")
        now = utcnow()
        clinic.purged_at = now
        for attr in ("bps_provider_number", "bps_company_number", "phone", "email", "address_street",
                     "address_number", "address_locality", "address_department", "address_annex",
                     "transport_included", "monthly_budget", "ayex_fee", "logo", "logo_content_type",
                     "logo_updated_at"):
            setattr(clinic, attr, None)
        db.flush()
    except Exception:
        db.rollback()  # todo vuelve a como estaba, disparadores incluidos
        raise
    # Los archivos se borran del disco recién después del commit (ver delete_files).
    return PurgeResult(purged_at=now, backup_name=copy.name,
                       counts={k: v for k, v in counts.items() if v}, pending_keys=keys)


def delete_files(result: PurgeResult) -> None:
    """Borra del disco los adjuntos y títulos de la clínica (después de confirmar la base)."""
    folder = Path(get_settings().files_dir)
    for key in result.pending_keys:
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", key or ""):
            result.files_failed += 1
            continue
        path = folder / key
        try:
            path.unlink()
            result.files_deleted += 1
        except FileNotFoundError:
            result.files_not_found += 1
        except OSError:
            result.files_failed += 1
