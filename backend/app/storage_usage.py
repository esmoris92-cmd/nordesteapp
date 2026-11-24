"""Cuánto ocupa cada clínica en la base de datos (para la pantalla del dueño del sistema).

PostgreSQL no separa el espacio por clínica: todas comparten las mismas tablas. Por eso el
tamaño de cada clínica es una **estimación**:

1. De cada tabla con ``clinic_id`` se suma cuánto ocupan las filas de cada clínica
   (``pg_column_size`` de la fila completa).
2. El tamaño real de la tabla en disco (``pg_total_relation_size``: datos, índices y TOAST) se
   reparte entre las clínicas en esa misma proporción.

Lo que no es de ninguna clínica (cuentas y sesiones del dueño, su auditoría, el catálogo de
PostgreSQL y el espacio libre que todavía no se reutilizó) se informa aparte como "compartido".

Los archivos adjuntos (PDF e imágenes) NO están en la base: se guardan en disco y se informan
aparte, sumando el tamaño que quedó registrado al subir cada uno.
"""

import re
import uuid
from dataclasses import dataclass, field

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.models import PatientFile, ProfessionalDegree

_IDENT = re.compile(r"^[a-z_][a-z0-9_]*$")

TABLE_LABELS = {
    "clinics": "Datos de la clínica",
    "branches": "Sucursales",
    "user_branches": "Sucursales de cada cuenta",
    "specialties": "Especialidades",
    "users": "Cuentas",
    "auth_sessions": "Sesiones de ingreso",
    "patients": "Pacientes",
    "patient_guardians": "Responsables",
    "patient_access": "Accesos a pacientes",
    "patient_institutions": "Instituciones",
    "availability": "Disponibilidad de profesionales",
    "appointments": "Turnos",
    "clinical_notes": "Historia clínica (notas)",
    "anamnesis_versions": "Anamnesis",
    "report_section_versions": "Antecedentes, diagnóstico, encuadre y abordajes",
    "reports": "Informes",
    "patient_files": "Archivos (solo sus datos)",
    "treatment_goals": "Objetivos",
    "goal_updates": "Avances de objetivos",
    "professional_degrees": "Títulos profesionales (solo sus datos)",
    "notices": "Avisos",
    "notice_recipients": "Destinatarios de avisos",
    "cash_registers": "Cajas",
    "cash_movements": "Movimientos de caja",
    "audit_log": "Auditoría",
}


@dataclass
class TableUsage:
    table: str
    label: str
    rows: int
    bytes: int


@dataclass
class ClinicUsage:
    database_bytes: int = 0
    rows: int = 0
    tables: list[TableUsage] = field(default_factory=list)
    files_count: int = 0
    files_bytes: int = 0


@dataclass
class Usage:
    database_bytes: int  # tamaño total de la base (pg_database_size)
    clinics: dict[uuid.UUID, ClinicUsage]

    @property
    def shared_bytes(self) -> int:
        return max(self.database_bytes - sum(c.database_bytes for c in self.clinics.values()), 0)


def _clinic_tables(db: Session) -> list[str]:
    """Tablas con datos de una clínica (las del dueño del sistema se cuentan como compartidas)."""
    names = db.scalars(text(
        "SELECT table_name FROM information_schema.columns "
        "WHERE table_schema = 'public' AND column_name = 'clinic_id' "
        "AND table_name NOT LIKE 'owner\\_%' ORDER BY table_name"
    )).all()
    return ["clinics", *[n for n in names if n != "clinics"]]


def measure(db: Session) -> Usage:
    """Recorre las tablas una vez y reparte su tamaño entre las clínicas."""
    clinics: dict[uuid.UUID, ClinicUsage] = {}
    for table in _clinic_tables(db):
        if not _IDENT.match(table):  # el nombre va dentro del SQL: solo nombres simples
            continue
        key = "id" if table == "clinics" else "clinic_id"
        total = db.scalar(text("SELECT pg_total_relation_size(CAST(:t AS regclass))"), {"t": table}) or 0
        rows = db.execute(text(
            f'SELECT t.{key}, count(*), COALESCE(sum(pg_column_size(t.*)), 0) FROM "{table}" t '
            f"WHERE t.{key} IS NOT NULL GROUP BY t.{key}"
        )).all()
        row_bytes = sum(int(r[2]) for r in rows)
        for clinic_id, count, size in rows:
            share = round(total * int(size) / row_bytes) if row_bytes else 0
            usage = clinics.setdefault(clinic_id, ClinicUsage())
            usage.database_bytes += share
            usage.rows += int(count)
            usage.tables.append(TableUsage(table=table, label=TABLE_LABELS.get(table, table),
                                           rows=int(count), bytes=share))
    for model in (PatientFile, ProfessionalDegree):
        for clinic_id, count, size in db.execute(
                select(model.clinic_id, func.count(), func.coalesce(func.sum(model.size_bytes), 0))
                .group_by(model.clinic_id)).all():
            usage = clinics.setdefault(clinic_id, ClinicUsage())
            usage.files_count += int(count)
            usage.files_bytes += int(size)
    for usage in clinics.values():
        usage.tables.sort(key=lambda t: t.bytes, reverse=True)
    database = db.scalar(text("SELECT pg_database_size(current_database())")) or 0
    return Usage(database_bytes=int(database), clinics=clinics)
