"""Exportación completa de los datos de UNA clínica (o de un espacio de profesional
independiente) en un archivo .zip, para entregárselo cuando deja de usar Nordeste.

La genera solo el dueño del sistema (``routers/owner_export.py``). Lleva TODO lo de esa clínica
y nada de otra: cada consulta filtra por ``clinic_id`` (y la base, con sus claves foráneas
compuestas, ya impide que una fila de una clínica apunte a datos de otra).

Qué hay adentro (el LEEME.txt que se genera lo explica para la clínica):

* ``planillas/``: una planilla Excel por tipo de dato, para mirar y filtrar. Una celda de Excel
  admite hasta 32.767 caracteres: lo que pase se corta con un aviso (el texto completo está en
  el CSV y en los documentos de cada paciente). Las planillas muy grandes se parten en varias.
* ``datos-csv/``: las mismas tablas en CSV (UTF-8, texto completo), para pasarlas a otro sistema.
* ``pacientes/<Apellido, Nombre (id)>/``: historia clínica completa, anamnesis e informes en HTML
  (se abren con el navegador y se imprimen o guardan como PDF) y los archivos adjuntos con su
  nombre original.
* ``clinica/``: logo y títulos de los profesionales.
* ``LEEME.txt`` y ``huellas-sha256.txt`` (para comprobar que nada se dañó al copiarlo).

Qué NO lleva nunca: contraseñas (ni sus hashes), sesiones, tokens, códigos del celular, ni
nada del dueño del sistema ni de otras clínicas.

El .zip se escribe en un archivo, no en memoria: los adjuntos se copian de a pedazos.
"""

import csv
import hashlib
import html
import json
import re
import unicodedata
import uuid
import zipfile
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from urllib.parse import quote
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.anamnesis_form import MAX_SIBLINGS, SECTIONS as ANAMNESIS_SECTIONS, sibling_keys
from app.audit_labels import AUDIT_ACTION_LABELS
from app.branches import AFFILIATION_LABELS
from app.config import get_settings
from app.features import FEATURES
from app.models import (
    AnamnesisVersion, Appointment, AuditEvent, Availability, Branch, CashMovement, CashRegister, Clinic,
    ClinicalNote, ClinicKind, GoalUpdate, Notice, NoticeRecipient, Patient, PatientAccess, PatientFile,
    PatientGuardian, PatientInstitution, ProfessionalDegree, Report, ReportSectionVersion, Specialty,
    TreatmentGoal, User, UserBranch,
)
from app.xlsx import build_xlsx

EXCEL_MAX_CHARS = 32767   # límite de Excel por celda
EXCEL_KEEP = 32000        # lo que se deja antes del aviso de "texto cortado"
ROWS_PER_SHEET = 200_000  # planillas más grandes se parten (Excel admite ~1 millón de filas)
CHUNK = 1024 * 1024
# PDF, PNG y JPG ya vienen comprimidos: se guardan tal cual (más rápido, mismo tamaño).
_ALREADY_COMPRESSED = {"application/pdf", "image/png", "image/jpeg"}
_EXTENSIONS = {"application/pdf": ".pdf", "image/png": ".png", "image/jpeg": ".jpg"}

# ---------- Textos en español (los mismos que muestra la interfaz) ----------

KIND_LABELS = {ClinicKind.clinic.value: "Clínica o centro",
               ClinicKind.independent.value: "Profesional independiente"}
ROLE_LABELS = {"admin": "Administración", "reception": "Recepción", "professional": "Profesional"}
STATUS_LABELS = {"active": "Activo", "paused": "En pausa", "discharged": "Alta", "inactive": "Inactivo"}
SEX_LABELS = {"male": "Masculino", "female": "Femenino", "unspecified": "No especificar"}
ACCESS_LABELS = {"responsible": "Responsable", "collaborator": "Colaborador/a"}
APPOINTMENT_LABELS = {"scheduled": "Programado", "completed": "Realizado", "no_show": "Ausente",
                      "cancelled": "Cancelado", "rescheduled": "Reprogramado"}
NOTE_KIND_LABELS = {"session": "Nota de sesión", "background": "Antecedentes", "progress": "Evolución",
                    "anamnesis": "Anamnesis", "interview": "Entrevista", "evaluation": "Evaluación",
                    "institution": "Reporte de institución"}
INSTITUTION_LEVEL_LABELS = {"inicial": "Inicial (jardín)", "primaria": "Primaria", "secundaria": "Secundaria",
                            "utu": "UTU / técnica", "universidad": "Universidad", "otra": "Otra"}
GOAL_STATUS_LABELS = {"active": "En curso", "achieved": "Logrado", "discontinued": "Discontinuado"}
REPORT_STATUS_LABELS = {"draft": "Borrador", "final": "Finalizado"}
SECTION_LABELS = {"antecedentes": "Antecedentes", "diagnostico": "Diagnóstico", "encuadre": "Encuadre",
                  "abordaje": "Abordaje"}
SECTION_FIELDS = {"antecedentes": ("texto",), "diagnostico": ("texto",), "encuadre": ("texto",),
                  "abordaje": ("abordaje", "en_suma", "sugerencias")}
SECTION_FIELD_LABELS = {"texto": "Texto", "abordaje": "Abordaje", "en_suma": "En suma",
                        "sugerencias": "Sugerencias"}
CASH_KIND_LABELS = {"income": "Entrada", "expense": "Salida"}
WEEKDAYS = ("Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo")
SUPPORT = "Soporte de Nordeste / sistema"  # acciones sin cuenta de la clínica (las del dueño)

_UNSAFE_NAME = re.compile(r'[\x00-\x1f\x7f/\\:*?"<>|]+')


# ---------- Utilidades ----------


def _safe_name(text: str, limit: int = 80) -> str:
    """Nombre de carpeta o archivo válido en Mac, Windows y Linux."""
    name = unicodedata.normalize("NFC", text or "")
    name = _UNSAFE_NAME.sub("_", name)
    name = re.sub(r"\s+", " ", name).strip(" .")
    return name[:limit].strip(" .") or "sin nombre"


def _slug(text: str) -> str:
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-")[:40] or "clinica"


def _join(*parts: str | None) -> str:
    return " ".join(p.strip() for p in parts if p and p.strip())


def patient_full_name(p: Patient) -> str:
    return _join(p.first_name, p.middle_name, p.last_name, p.second_last_name)


def patient_folder(p: Patient) -> str:
    """'Pérez García, Ana María (1a2b3c4d)': ordena por apellido y no se repite."""
    last = _join(p.last_name, p.second_last_name)
    first = _join(p.first_name, p.middle_name)
    return _safe_name(f"{last}, {first}", 70) + f" ({str(p.id)[:8]})"


def _yes_no(value: bool | None) -> str:
    return "" if value is None else ("Sí" if value else "No")


def _fmt_date(value: date | None) -> str:
    return value.strftime("%d/%m/%Y") if value else "—"


def _fmt_dt(value: datetime | None) -> str:
    return value.strftime("%d/%m/%Y %H:%M") if value else "—"


def _iso_to_date(value: str) -> date | None:
    try:
        return date.fromisoformat(value[:10])
    except (TypeError, ValueError):
        return None


def age_text(birth: date | None, at: date) -> str:
    """Igual que la interfaz: '7 años y 3 meses' (desde los 18, solo los años)."""
    if not birth:
        return "—"
    months = (at.year - birth.year) * 12 + (at.month - birth.month)
    if at.day < birth.day:
        months -= 1
    if months < 0:
        return "—"
    years, rest = divmod(months, 12)
    y_text = "1 año" if years == 1 else f"{years} años"
    if years >= 18 or rest == 0:
        return y_text
    return f"{y_text} y {'1 mes' if rest == 1 else f'{rest} meses'}"


def is_heading_line(line: str) -> bool:
    """Igual que la hoja impresa: una línea en mayúsculas (al menos 3 letras) es un título."""
    head = line.strip().split(" — ")[0]
    if not head or len(head) > 120:
        return False
    letters = [ch for ch in head if ch.isalpha()]
    return len(letters) >= 3 and head == head.upper()


def _csv_value(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return _yes_no(value)
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def _width(header: str) -> int:
    long_words = ("texto", "respuesta", "descripcion", "nota", "detalles", "mensaje", "concepto",
                  "pregunta", "motivo", "contenido", "destinatarios", "firmantes", "ruta")
    if any(w in header for w in long_words):
        return 50
    return min(max(len(header) + 2, 12), 30)


esc = html.escape


# ---------- El .zip ----------


class _Zip:
    """Escribe las entradas del .zip y anota la huella SHA-256 de cada una."""

    def __init__(self, path: Path, root: str, when: datetime):
        self.zf = zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED, allowZip64=True)
        self.root = root
        self.date_time = when.timetuple()[:6]
        self.hashes: list[tuple[str, str]] = []
        self._names: set[str] = set()

    def unique(self, name: str) -> str:
        """Si ya existe una entrada con ese nombre, agrega ' (2)', ' (3)'... antes de la extensión."""
        if name.lower() not in self._names:
            self._names.add(name.lower())
            return name
        folder, _, file = name.rpartition("/")
        stem, dot, ext = file.rpartition(".")
        if not dot or "/" in ext:
            stem, ext = file, ""
        n = 2
        while True:
            candidate = f"{folder}/{stem} ({n}){'.' + ext if ext else ''}" if folder else \
                f"{stem} ({n}){'.' + ext if ext else ''}"
            if candidate.lower() not in self._names:
                self._names.add(candidate.lower())
                return candidate
            n += 1

    def _info(self, name: str, stored: bool) -> zipfile.ZipInfo:
        info = zipfile.ZipInfo(f"{self.root}/{name}", date_time=self.date_time)
        info.compress_type = zipfile.ZIP_STORED if stored else zipfile.ZIP_DEFLATED
        info.external_attr = 0o644 << 16
        return info

    def write_bytes(self, name: str, data: bytes, stored: bool = False) -> None:
        self.zf.writestr(self._info(name, stored), data)
        self.hashes.append((hashlib.sha256(data).hexdigest(), name))

    def write_text(self, name: str, text: str) -> None:
        self.write_bytes(name, text.encode("utf-8"))

    def copy_file(self, name: str, source: Path, stored: bool) -> str:
        """Copia un archivo del disco de a pedazos y devuelve su huella SHA-256."""
        digest = hashlib.sha256()
        with open(source, "rb") as src, self.zf.open(self._info(name, stored), "w", force_zip64=True) as dst:
            while chunk := src.read(CHUNK):
                digest.update(chunk)
                dst.write(chunk)
        sha = digest.hexdigest()
        self.hashes.append((sha, name))
        return sha

    def close(self) -> None:
        self.zf.close()


class _Table:
    """Una tabla que se escribe a la vez como planilla Excel y como CSV."""

    def __init__(self, exporter: "_ClinicExporter", name: str, headers: list[str], full_text_hint: str):
        self.exporter = exporter
        self.name = name
        self.headers = headers
        self.hint = full_text_hint
        self.rows: list[list] = []
        self.count = 0
        self.parts = 0
        self.truncated = 0
        self.csv_path = exporter.workdir / f"{name}.csv"
        # utf-8-sig: con la marca inicial, Excel reconoce los acentos si alguien abre el CSV.
        self.csv_file = open(self.csv_path, "w", encoding="utf-8-sig", newline="")
        self.csv = csv.writer(self.csv_file)
        self.csv.writerow(headers)

    def _excel(self, value):
        if isinstance(value, bool):
            return _yes_no(value)
        if isinstance(value, Decimal):
            return float(value)
        if isinstance(value, uuid.UUID):
            return str(value)
        if isinstance(value, str) and len(value) > EXCEL_MAX_CHARS:
            self.truncated += 1
            return value[:EXCEL_KEEP] + f" […] TEXTO CORTADO (Excel no admite más): el texto completo está en {self.hint}."
        return value

    def add(self, row: list) -> None:
        self.csv.writerow([_csv_value(v) for v in row])
        self.rows.append([self._excel(v) for v in row])
        self.count += 1
        if len(self.rows) >= ROWS_PER_SHEET:
            self._flush()

    def _flush(self) -> None:
        self.parts += 1
        suffix = "" if self.parts == 1 else f" (parte {self.parts})"
        content = build_xlsx(self.name[3:][:31] if self.name[:2].isdigit() else self.name[:31],
                             self.headers, self.rows, [_width(h) for h in self.headers])
        self.exporter.zip.write_bytes(f"planillas/{self.name}{suffix}.xlsx", content)
        self.rows = []

    def close(self) -> None:
        if self.rows or self.parts == 0:
            self._flush()
        self.csv_file.close()
        self.exporter.zip.copy_file(f"datos-csv/{self.name}.csv", self.csv_path, stored=False)
        self.csv_path.unlink(missing_ok=True)
        self.exporter.tables.append(self)


# ---------- Páginas HTML ----------

_CSS = """
body { margin: 0; background: #f4f4f4; font: 15px/1.5 -apple-system, "Segoe UI", Roboto, Arial, sans-serif; color: #111; }
.page { max-width: 820px; margin: 0 auto; padding: 1.5rem; background: #fff; min-height: 100vh; }
.tip { background: #eef5ff; border: 1px solid #c9ddf7; padding: .5rem .75rem; font-size: .85rem; margin-bottom: 1rem; }
header { border-bottom: 2px solid #1767c8; padding-bottom: .6rem; margin-bottom: 1rem; }
.clinic { display: flex; align-items: center; gap: .75rem; }
.clinic strong { font-size: 1.1rem; color: #1767c8; }
.logo { max-height: 64px; max-width: 220px; object-fit: contain; }
h1 { font-size: 1.4rem; margin: .6rem 0 0; }
h2 { font-size: 1.05rem; margin: 1.4rem 0 .5rem; text-transform: uppercase; letter-spacing: .02em;
     border-top: 1px solid #ccc; padding-top: .6rem; }
h3 { font-size: .95rem; margin: .9rem 0 .3rem; color: #333; }
.facts { display: grid; grid-template-columns: max-content 1fr; gap: .25rem 1.25rem; margin: 0 0 1rem; }
.facts dt { color: #555; } .facts dd { margin: 0; font-weight: 500; }
.qa > div { margin: 0 0 .55rem; break-inside: avoid; }
.qa dt { font-weight: 600; font-size: .9rem; } .qa dd { margin: .1rem 0 0; white-space: pre-wrap; }
.text { white-space: pre-wrap; line-height: 1.6; overflow-wrap: anywhere; }
.block { border: 1px solid #ddd; border-radius: 4px; padding: .6rem .8rem; margin: 0 0 .8rem; break-inside: avoid-page; }
.meta { color: #555; font-size: .85rem; margin-bottom: .3rem; }
.warn { background: #fff4d6; border: 1px solid #e8c766; padding: .5rem .75rem; margin: .5rem 0 1rem; font-weight: 600; }
.muted { color: #666; }
table { width: 100%; border-collapse: collapse; font-size: .88rem; margin-bottom: .8rem; }
th, td { border-bottom: 1px solid #ccc; padding: .3rem .4rem; text-align: left; vertical-align: top; }
.signatures { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 0 2.5rem; break-inside: avoid; }
.signature { margin: 3.5rem 0 0; width: 240px; border-top: 1px solid #333; padding-top: .3rem;
             display: flex; flex-direction: column; font-size: .9rem; }
.new-page { break-before: page; }
footer { margin-top: 2rem; padding-top: .5rem; border-top: 1px solid #ccc; color: #555; font-size: .8rem; }
@media print { body { background: #fff; } .page { padding: 0; max-width: none; } .tip { display: none; } }
"""


def _facts(pairs: list[tuple[str, str]]) -> str:
    return '<dl class="facts">' + "".join(
        f"<dt>{esc(k)}</dt><dd>{esc(v or '—')}</dd>" for k, v in pairs) + "</dl>"


def _text(text: str | None) -> str:
    """Texto con sus saltos de línea; las líneas en mayúsculas, en negrita (como al imprimir)."""
    lines = (text or "").split("\n")
    return '<div class="text">' + "\n".join(
        f"<strong>{esc(line)}</strong>" if is_heading_line(line) else esc(line) for line in lines) + "</div>"


def _table(headers: list[str], rows: list[list[str]], empty: str) -> str:
    if not rows:
        return f'<p class="muted">{esc(empty)}</p>'
    head = "".join(f"<th>{esc(h)}</th>" for h in headers)
    body = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in row) + "</tr>" for row in rows)
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def _signatures(items: list[tuple[str, str | None, str]]) -> str:
    return '<div class="signatures">' + "".join(
        f'<div class="signature"><span>{esc(name)}</span>'
        + (f"<span>{esc(sub)}</span>" if sub else "")
        + f'<span class="muted">{esc(caption)}</span></div>'
        for name, sub, caption in items) + "</div>"


def anamnesis_answers(data: dict) -> list[tuple[str, str | None, list[tuple[str, str, str]]]]:
    """Respuestas de una versión, en el orden de la ficha: [(sección, grupo, [(clave, pregunta,
    respuesta)])]. Solo lo respondido. Al final, "Otros datos guardados" con lo que tenga una
    clave que la ficha ya no usa (para no perder nada)."""
    result = []
    known: set[str] = set()
    for n in range(1, MAX_SIBLINGS + 1):
        known.update(sibling_keys(n))
    for section in ANAMNESIS_SECTIONS:
        for group in section.groups:
            items: list[tuple[str, str, str]] = []
            if group.siblings:
                for n in range(1, MAX_SIBLINGS + 1):
                    name_key, age_key = sibling_keys(n)
                    name, age = str(data.get(name_key) or ""), str(data.get(age_key) or "")
                    if not name and not age:
                        continue
                    age_txt = f"{age} años" if age.isdigit() else age
                    items.append((f"hermano_{n}", f"Hermano/a {n}", " · ".join(x for x in (name, age_txt) if x)))
            for field in group.fields:
                known.add(field.key)
                value = data.get(field.key)
                if value in (None, ""):
                    continue
                value = str(value)
                if field.type == "date" and _iso_to_date(value):
                    value = _fmt_date(_iso_to_date(value))
                items.append((field.key, field.label, value))
            if items:
                result.append((section.title, group.title, items))
    extra = [(k, k, str(v)) for k, v in sorted(data.items()) if k not in known and v not in (None, "")]
    if extra:
        result.append(("Otros datos guardados", None, extra))
    return result


# ---------- Exportación ----------


@dataclass
class ExportResult:
    path: Path
    filename: str
    patients: int
    files: int
    missing_files: int
    size_bytes: int


class _ClinicExporter:
    def __init__(self, db: Session, clinic_id: uuid.UUID, workdir: Path):
        self.db = db
        self.clinic: Clinic = db.get(Clinic, clinic_id)
        if self.clinic is None:
            raise ValueError("No existe esa clínica.")
        self.cid = self.clinic.id
        self.tz = ZoneInfo(self.clinic.timezone or "America/Montevideo")
        self.now = datetime.now(self.tz)
        self.workdir = workdir
        self.independent = self.clinic.kind == ClinicKind.independent.value
        self.root = f"lumen-exportacion-{_slug(self.clinic.name)}-{self.now:%Y-%m-%d}"
        self.path = workdir / f"{self.root}.zip"
        self.zip = _Zip(self.path, self.root, self.now.replace(tzinfo=None))
        self.tables: list[_Table] = []
        self.warnings: list[str] = []
        self.files_dir = Path(get_settings().files_dir)
        self.logo_name: str | None = None
        self.files_copied = 0
        self.files_missing = 0

    # --- ayudas ---

    def local(self, value: datetime | None) -> datetime | None:
        return value.astimezone(self.tz).replace(tzinfo=None) if value else None

    def user_name(self, user_id: uuid.UUID | None) -> str:
        if user_id is None:
            return SUPPORT
        user = self.users.get(user_id)
        return user.full_name if user else str(user_id)

    def specialty_of(self, user_id: uuid.UUID | None) -> str:
        user = self.users.get(user_id) if user_id else None
        sp = self.specialties.get(user.specialty_id) if user and user.specialty_id else None
        return sp.name if sp else ""

    def patient_name(self, patient_id: uuid.UUID | None) -> str:
        p = self.patients.get(patient_id) if patient_id else None
        return patient_full_name(p) if p else ""

    def table(self, name: str, headers: list[str], hint: str = "el archivo .csv de la carpeta datos-csv") -> _Table:
        return _Table(self, name, headers, hint)

    def _all(self, model, *order):
        return self.db.scalars(select(model).where(model.clinic_id == self.cid).order_by(*order)).all()

    def _by_patient(self, rows) -> dict[uuid.UUID, list]:
        grouped: dict[uuid.UUID, list] = defaultdict(list)
        for row in rows:
            grouped[row.patient_id].append(row)
        return grouped

    # --- lectura ---

    def load(self) -> None:
        c = self.cid
        self.branches = {b.id: b for b in self._all(Branch, Branch.name)}
        self.specialties = {s.id: s for s in self._all(Specialty, Specialty.name)}
        self.users = {u.id: u for u in self._all(User, User.full_name)}
        patients = self.db.scalars(select(Patient).where(Patient.clinic_id == c).order_by(
            Patient.last_name, Patient.second_last_name, Patient.first_name, Patient.id)).all()
        self.patients = {p.id: p for p in patients}
        self.folders: dict[uuid.UUID, str] = {}
        for p in patients:
            self.folders[p.id] = self.zip.unique(f"pacientes/{patient_folder(p)}").split("/", 1)[1]
        self.guardians = self._by_patient(self._all(PatientGuardian, PatientGuardian.created_at))
        self.institutions = self._by_patient(self._all(PatientInstitution, PatientInstitution.created_at))
        self.institution_names = {i.id: i.name for rows in self.institutions.values() for i in rows}
        self.accesses = self._by_patient(self._all(PatientAccess, PatientAccess.granted_at))
        self.appointments = self._by_patient(self._all(Appointment, Appointment.starts_at))
        self.notes = self._by_patient(self._all(ClinicalNote, ClinicalNote.created_at))
        self.anamnesis = self._by_patient(self._all(AnamnesisVersion, AnamnesisVersion.created_at))
        self.sections = self._by_patient(self._all(ReportSectionVersion, ReportSectionVersion.created_at))
        self.reports = self._by_patient(self._all(Report, Report.created_at))
        self.goals = self._by_patient(self._all(TreatmentGoal, TreatmentGoal.created_at))
        goal_updates = self._all(GoalUpdate, GoalUpdate.created_at)
        self.goal_updates: dict[uuid.UUID, list[GoalUpdate]] = defaultdict(list)
        for g in goal_updates:
            self.goal_updates[g.goal_id].append(g)
        self.goal_patient = {g.id: g.patient_id for rows in self.goals.values() for g in rows}
        self.files = self._by_patient(self._all(PatientFile, PatientFile.created_at))
        self.responsible: dict[uuid.UUID, uuid.UUID] = {}
        for pid, rows in self.accesses.items():
            for a in rows:
                if a.revoked_at is None and a.level == "responsible":
                    self.responsible[pid] = a.user_id
        # Nota que corrige a cada nota (las correcciones apuntan a la anterior con supersedes_id).
        self.corrected_by = {n.supersedes_id: n for rows in self.notes.values() for n in rows if n.supersedes_id}
        # Ruta de cada informe dentro del .zip.
        self.report_paths: dict[uuid.UUID, str] = {}
        for pid, rows in self.reports.items():
            for r in rows:
                when = self.local(r.finalized_at or r.created_at)
                state = "Finalizado" if r.status == "final" else "BORRADOR"
                name = _safe_name(f"{when:%Y-%m-%d} {r.title} ({state})", 120)
                self.report_paths[r.id] = self.zip.unique(f"pacientes/{self.folders[pid]}/informes/{name}.html")

    # --- archivos ---

    def copy_patient_files(self) -> None:
        self.file_results: dict[uuid.UUID, tuple[str, str]] = {}
        for pid, rows in self.files.items():
            for f in rows:
                sub = "archivos/retirados" if f.withdrawn_at else "archivos"
                day = self.local(f.created_at)
                name = self.zip.unique(
                    f"pacientes/{self.folders[pid]}/{sub}/{day:%Y-%m-%d} {_safe_name(f.original_name, 120)}")
                self.file_results[f.id] = (name, self._copy(name, f.storage_key, f.sha256, f.content_type))

    def _copy(self, name: str, storage_key: str, sha: str, content_type: str) -> str:
        source = self.files_dir / storage_key
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", storage_key or "") or not source.is_file():
            self.files_missing += 1
            self.warnings.append(f"No se encontró en el servidor el archivo que iba en: {name}")
            return "No estaba en el servidor"
        got = self.zip.copy_file(name, source, stored=content_type in _ALREADY_COMPRESSED)
        self.files_copied += 1
        if got != sha:
            self.warnings.append(f"La huella no coincide con la que se guardó al subirlo: {name}")
            return "Copiado, pero su huella no coincide con la de la subida"
        return "Copiado"

    def copy_clinic_files(self) -> None:
        if self.clinic.logo:
            self.logo_name = "logo" + _EXTENSIONS.get(self.clinic.logo_content_type or "", ".png")
            self.zip.write_bytes(f"clinica/{self.logo_name}", self.clinic.logo, stored=True)
        t = self.table("19-titulos-profesionales", [
            "id", "id_usuario", "profesional", "nombre_original", "tipo", "tamano_bytes", "subido",
            "reemplazado", "sha256", "ruta_en_el_zip", "estado_de_la_copia"])
        for d in self._all(ProfessionalDegree, ProfessionalDegree.created_at):
            user = self.users.get(d.user_id)
            folder = _safe_name(user.full_name if user else "sin nombre", 60) + f" ({str(d.user_id)[:8]})"
            suffix = " (reemplazado)" if d.replaced_at else ""
            original = _safe_name(d.original_name, 120)
            stem, dot, ext = original.rpartition(".")
            file = f"{stem}{suffix}.{ext}" if dot else f"{original}{suffix}"
            name = self.zip.unique(
                f"clinica/titulos-profesionales/{folder}/{self.local(d.created_at):%Y-%m-%d} {file}")
            state = self._copy(name, d.storage_key, d.sha256, d.content_type)
            t.add([d.id, d.user_id, self.user_name(d.user_id), d.original_name, d.content_type, d.size_bytes,
                   self.local(d.created_at), self.local(d.replaced_at), d.sha256,
                   name if state != "No estaba en el servidor" else "", state])
        t.close()

    # --- planillas ---

    def write_tables(self) -> None:
        c = self.clinic
        disabled = set(c.disabled_features or [])
        t = self.table("01-clinica", ["campo", "valor"])
        for k, v in [
            ("id", c.id), ("Nombre", c.name), ("Tipo de espacio", KIND_LABELS.get(c.kind, c.kind)),
            ("Zona horaria", c.timezone), ("Teléfono", c.phone), ("Correo", c.email),
            ("Calle", c.address_street), ("Número", c.address_number), ("Localidad", c.address_locality),
            ("Departamento", c.address_department), ("Anexo", c.address_annex),
            ("N.º de proveedor BPS", c.bps_provider_number), ("N.º de empresa BPS", c.bps_company_number),
            ("Incluye transporte", _yes_no(c.transport_included)), ("Presupuesto mensual", c.monthly_budget),
            ("Arancel AYEX", c.ayex_fee),
            ("Funciones deshabilitadas", ", ".join(f.label for f in FEATURES if f.key in disabled) or "Ninguna"),
            ("Alta en Nordeste", self.local(c.created_at)), ("Suspendida desde", self.local(c.suspended_at)),
            ("Logo", f"clinica/{self.logo_name}" if self.logo_name else "Sin logo"),
        ]:
            t.add([k, v])
        t.close()

        t = self.table("02-sucursales", ["id", "nombre", "activa", "creada"])
        for b in self.branches.values():
            t.add([b.id, b.name, b.is_active, self.local(b.created_at)])
        t.close()

        t = self.table("03-especialidades", ["id", "nombre", "actividad_cronograma_bps", "activa", "creada"])
        for s in self.specialties.values():
            t.add([s.id, s.name, s.bps_activity, s.is_active, self.local(s.created_at)])
        t.close()

        branches_of: dict[uuid.UUID, list[str]] = defaultdict(list)
        for ub in self.db.scalars(select(UserBranch).where(UserBranch.clinic_id == self.cid)):
            branch = self.branches.get(ub.branch_id)
            branches_of[ub.user_id].append(branch.name if branch else str(ub.branch_id))
        t = self.table("04-usuarios", [
            "id", "nombre_completo", "correo", "documento", "telefono", "primer_nombre", "segundo_nombre",
            "primer_apellido", "segundo_apellido", "rol", "especialidad", "formacion_bps", "titulo_expedido_por",
            "sucursales_asignadas", "pacientes_a_la_vez", "activa", "eliminada_el", "creada", "modificada"])
        for u in self.users.values():
            role = ROLE_LABELS.get(u.role, u.role)
            if self.independent and u.role == "professional":
                role = "Profesional independiente (titular)"
            t.add([u.id, u.full_name, u.email, u.document_number, u.phone, u.first_name, u.middle_name,
                   u.last_name, u.second_last_name, role, self.specialty_of(u.id), u.bps_training,
                   u.degree_issuer, ", ".join(sorted(branches_of.get(u.id, []))),
                   u.max_concurrent_patients if u.role == "professional" else None, u.is_active,
                   self.local(u.archived_at), self.local(u.created_at), self.local(u.updated_at)])
        t.close()

        t = self.table("05-horarios", ["id", "profesional", "sucursal", "dia", "desde", "hasta"])
        for a in self.db.scalars(select(Availability).where(Availability.clinic_id == self.cid).order_by(
                Availability.professional_id, Availability.weekday, Availability.start_time)):
            t.add([a.id, self.user_name(a.professional_id), self._branch(a.branch_id), WEEKDAYS[a.weekday],
                   a.start_time.strftime("%H:%M"), a.end_time.strftime("%H:%M")])
        t.close()

        t = self.table("06-pacientes", [
            "id", "documento", "primer_nombre", "segundo_nombre", "primer_apellido", "segundo_apellido", "sexo",
            "tipo_afiliacion", "vencimiento_ayex", "fecha_nacimiento", "telefono", "correo", "departamento",
            "localidad", "calle", "numero", "apartamento", "solar", "manzana", "sucursal", "estado",
            "profesional_responsable", "cargado_por", "fecha_registro", "ultima_modificacion", "carpeta_en_el_zip"])
        for p in self.patients.values():
            t.add([p.id, p.document_number, p.first_name, p.middle_name, p.last_name, p.second_last_name,
                   SEX_LABELS.get(p.sex or "", p.sex), AFFILIATION_LABELS.get(p.affiliation, p.affiliation),
                   p.ayex_expires_on, p.birth_date, p.phone, p.email, p.address_department, p.address_locality,
                   p.address_street, p.address_number, p.address_apartment, p.address_solar, p.address_block,
                   self._branch(p.branch_id), STATUS_LABELS.get(p.status, p.status),
                   self.user_name(self.responsible[p.id]) if p.id in self.responsible else "",
                   self.user_name(p.created_by), self.local(p.created_at), self.local(p.updated_at),
                   f"pacientes/{self.folders[p.id]}"])
        t.close()

        t = self.table("07-responsables", [
            "id", "id_paciente", "paciente", "nombre_completo", "primer_nombre", "segundo_nombre",
            "primer_apellido", "segundo_apellido", "documento", "vinculo", "telefono", "correo",
            "contacto_principal", "notas", "cargado_por", "creado", "modificado"])
        for g in self._each(self.guardians):
            t.add([g.id, g.patient_id, self.patient_name(g.patient_id), g.full_name, g.first_name, g.middle_name,
                   g.last_name, g.second_last_name, g.document_number, g.relationship, g.phone, g.email,
                   g.is_primary, g.notes, self.user_name(g.created_by), self.local(g.created_at),
                   self.local(g.updated_at)])
        t.close()

        t = self.table("08-instituciones", [
            "id", "id_paciente", "paciente", "nombre", "nivel", "telefono", "correo", "actual", "cargada_por",
            "creada", "modificada"])
        for i in self._each(self.institutions):
            t.add([i.id, i.patient_id, self.patient_name(i.patient_id), i.name,
                   INSTITUTION_LEVEL_LABELS.get(i.level, i.level), i.phone, i.email, i.is_current,
                   self.user_name(i.created_by), self.local(i.created_at), self.local(i.updated_at)])
        t.close()

        t = self.table("09-accesos-profesionales", [
            "id", "id_paciente", "paciente", "profesional", "nivel", "motivo", "otorgado_por", "otorgado",
            "retirado_por", "retirado", "motivo_del_retiro"])
        for a in self._each(self.accesses):
            t.add([a.id, a.patient_id, self.patient_name(a.patient_id), self.user_name(a.user_id),
                   ACCESS_LABELS.get(a.level, a.level), a.reason, self.user_name(a.granted_by),
                   self.local(a.granted_at), self.user_name(a.revoked_by) if a.revoked_by else "",
                   self.local(a.revoked_at), a.revoke_reason])
        t.close()

        t = self.table("10-turnos", [
            "id", "id_paciente", "paciente", "profesional", "sucursal", "inicio", "fin", "estado",
            "motivo_de_cancelacion", "motivo_de_reprogramacion", "reprogramado_al_turno", "motivo_de_ausencia",
            "cargado_por", "creado", "modificado"])
        for a in self._each(self.appointments):
            t.add([a.id, a.patient_id, self.patient_name(a.patient_id), self.user_name(a.professional_id),
                   self._branch(a.branch_id), self.local(a.starts_at), self.local(a.ends_at),
                   APPOINTMENT_LABELS.get(a.status, a.status), a.cancel_reason, a.reschedule_reason,
                   a.rescheduled_to_id, a.no_show_reason, self.user_name(a.created_by),
                   self.local(a.created_at), self.local(a.updated_at)])
        t.close()

        t = self.table("11-notas-clinicas", [
            "id", "id_paciente", "paciente", "tipo", "fecha_de_sesion", "autor", "institucion", "texto",
            "corrige_a_la_nota", "motivo_de_la_correccion", "corregida_por_la_nota", "creada"],
            "la historia-clinica-completa.html del paciente y en datos-csv")
        for n in self._each(self.notes):
            fixed = self.corrected_by.get(n.id)
            t.add([n.id, n.patient_id, self.patient_name(n.patient_id), NOTE_KIND_LABELS.get(n.kind, n.kind),
                   n.session_date, self.user_name(n.author_id), self.institution_names.get(n.institution_id, ""),
                   n.content, n.supersedes_id, n.correction_reason, fixed.id if fixed else None,
                   self.local(n.created_at)])
        t.close()

        t = self.table("12-anamnesis", [
            "id_version", "id_paciente", "paciente", "guardada", "autor", "vigente", "seccion", "grupo",
            "pregunta", "clave", "respuesta"], "la anamnesis.html del paciente y en datos-csv")
        for pid, versions in self.anamnesis.items():
            latest = versions[-1].id if versions else None
            for v in versions:
                for section, group, items in anamnesis_answers(v.data or {}):
                    for key, label, value in items:
                        t.add([v.id, pid, self.patient_name(pid), self.local(v.created_at),
                               self.user_name(v.author_id), v.id == latest, section, group, label, key, value])
        t.close()

        t = self.table("13-antecedentes-diagnostico-encuadre-abordajes", [
            "id_version", "id_paciente", "paciente", "seccion", "profesional_del_abordaje", "autor", "guardada",
            "vigente", "campo", "texto"], "la historia-clinica-completa.html del paciente y en datos-csv")
        for pid, versions in self.sections.items():
            latest = {}
            for v in versions:
                latest[(v.section, v.owner_id)] = v.id
            for v in versions:
                for key in SECTION_FIELDS.get(v.section, tuple((v.data or {}).keys())):
                    t.add([v.id, pid, self.patient_name(pid), SECTION_LABELS.get(v.section, v.section),
                           self.user_name(v.owner_id) if v.owner_id else "", self.user_name(v.author_id),
                           self.local(v.created_at), latest[(v.section, v.owner_id)] == v.id,
                           SECTION_FIELD_LABELS.get(key, key), (v.data or {}).get(key, "")])
        t.close()

        t = self.table("14-informes", [
            "id", "id_paciente", "paciente", "titulo", "estado", "autor", "firmantes", "creado", "modificado",
            "finalizado", "texto", "documento_en_el_zip"], "el documento del informe (columna documento_en_el_zip)")
        for r in self._each(self.reports):
            t.add([r.id, r.patient_id, self.patient_name(r.patient_id), r.title,
                   REPORT_STATUS_LABELS.get(r.status, r.status), self.user_name(r.author_id),
                   ", ".join(s.get("name", "") for s in (r.signers or []) if isinstance(s, dict)),
                   self.local(r.created_at), self.local(r.updated_at), self.local(r.finalized_at), r.content,
                   self.report_paths[r.id]])
        t.close()

        t = self.table("15-objetivos", [
            "id", "id_paciente", "paciente", "area", "descripcion", "fecha_objetivo", "estado", "progreso",
            "creado_por", "creado"])
        for g in self._each(self.goals):
            t.add([g.id, g.patient_id, self.patient_name(g.patient_id), g.area, g.description, g.target_date,
                   GOAL_STATUS_LABELS.get(g.status, g.status), g.progress, self.user_name(g.created_by),
                   self.local(g.created_at)])
        t.close()

        t = self.table("16-avances-de-objetivos", [
            "id", "id_objetivo", "id_paciente", "paciente", "fecha_de_sesion", "progreso", "nuevo_estado", "nota",
            "autor", "creado"])
        for rows in self.goal_updates.values():
            for u in rows:
                pid = self.goal_patient.get(u.goal_id)
                t.add([u.id, u.goal_id, pid, self.patient_name(pid), u.session_date, u.progress,
                       GOAL_STATUS_LABELS.get(u.new_status or "", u.new_status), u.note,
                       self.user_name(u.author_id), self.local(u.created_at)])
        t.close()

        t = self.table("17-archivos", [
            "id", "id_paciente", "paciente", "nombre_original", "tipo", "tamano_bytes", "descripcion",
            "institucion", "subido_por", "subido", "retirado", "retirado_por", "motivo_del_retiro", "sha256",
            "ruta_en_el_zip", "estado_de_la_copia"])
        for f in self._each(self.files):
            path, state = self.file_results[f.id]
            t.add([f.id, f.patient_id, self.patient_name(f.patient_id), f.original_name, f.content_type,
                   f.size_bytes, f.description, self.institution_names.get(f.institution_id, ""),
                   self.user_name(f.uploaded_by), self.local(f.created_at), self.local(f.withdrawn_at),
                   self.user_name(f.withdrawn_by) if f.withdrawn_by else "", f.withdraw_reason, f.sha256,
                   path if state != "No estaba en el servidor" else "", state])
        t.close()

        t = self.table("18-avisos", [
            "id", "autor", "sucursal", "para_todos", "mensaje", "creado", "retirado", "destinatarios"])
        readers: dict[uuid.UUID, list[str]] = defaultdict(list)
        for r in self.db.scalars(select(NoticeRecipient).where(NoticeRecipient.clinic_id == self.cid)):
            read = f"leído el {_fmt_dt(self.local(r.read_at))}" if r.read_at else "sin leer"
            readers[r.notice_id].append(f"{self.user_name(r.user_id)} ({read})")
        for n in self._all(Notice, Notice.created_at):
            t.add([n.id, self.user_name(n.author_id), self._branch(n.branch_id) if n.branch_id else "", n.to_all,
                   n.message, self.local(n.created_at), self.local(n.withdrawn_at), "; ".join(readers.get(n.id, []))])
        t.close()

        registers = self._all(CashRegister, CashRegister.business_date)
        register_info = {r.id: r for r in registers}
        t = self.table("20-cajas", [
            "id", "sucursal", "dia", "monto_inicial", "abierta_por", "abierta", "contado_al_cerrar",
            "esperado_al_cerrar", "diferencia", "nota_de_cierre", "cerrada_por", "cerrada", "veces_reabierta"])
        for r in registers:
            diff = (r.counted_amount - r.expected_amount) if r.counted_amount is not None and \
                r.expected_amount is not None else None
            t.add([r.id, self._branch(r.branch_id), r.business_date, r.opening_amount, self.user_name(r.opened_by),
                   self.local(r.opened_at), r.counted_amount, r.expected_amount, diff, r.closing_note,
                   self.user_name(r.closed_by) if r.closed_by else "", self.local(r.closed_at), r.reopen_count])
        t.close()

        t = self.table("21-movimientos-de-caja", [
            "id", "id_caja", "sucursal", "dia_de_la_caja", "tipo", "monto", "concepto", "cargado_por", "creado",
            "anulado", "anulado_por", "motivo_de_anulacion"])
        for m in self._all(CashMovement, CashMovement.created_at):
            reg = register_info.get(m.register_id)
            t.add([m.id, m.register_id, self._branch(reg.branch_id) if reg else "", reg.business_date if reg else None,
                   CASH_KIND_LABELS.get(m.kind, m.kind), m.amount, m.concept, self.user_name(m.created_by),
                   self.local(m.created_at), self.local(m.voided_at),
                   self.user_name(m.voided_by) if m.voided_by else "", m.void_reason])
        t.close()

        t = self.table("22-auditoria", [
            "id", "fecha", "quien", "accion", "descripcion", "tipo_de_dato", "id_del_dato", "id_paciente",
            "paciente", "detalles", "ip"])
        query = (select(AuditEvent).where(AuditEvent.clinic_id == self.cid).order_by(AuditEvent.id)
                 .execution_options(yield_per=5000))
        for e in self.db.scalars(query):
            t.add([e.id, self.local(e.created_at), self.user_name(e.actor_id), e.action,
                   AUDIT_ACTION_LABELS.get(e.action, ""), e.entity_type,
                   e.entity_id, e.patient_id, self.patient_name(e.patient_id),
                   json.dumps(e.details, ensure_ascii=False) if e.details else "", e.ip])
        t.close()

    def _branch(self, branch_id: uuid.UUID | None) -> str:
        b = self.branches.get(branch_id) if branch_id else None
        return b.name if b else ""

    @staticmethod
    def _each(grouped: dict[uuid.UUID, list]):
        for rows in grouped.values():
            yield from rows

    # --- documentos de cada paciente ---

    def _page(self, title: str, body: str, depth: int) -> str:
        logo = (f'<img class="logo" src="{"../" * depth}clinica/{quote(self.logo_name)}" alt="Logo">'
                if self.logo_name else "")
        return (
            '<!DOCTYPE html><html lang="es"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1">'
            f"<title>{esc(title)} · {esc(self.clinic.name)}</title><style>{_CSS}</style></head><body>"
            '<div class="page"><p class="tip">Para imprimir o guardar como PDF: Cmd + P (Mac) o Ctrl + P '
            '(Windows) y elegí «Guardar como PDF».</p>'
            f'<header><div class="clinic">{logo}<strong>{esc(self.clinic.name)}</strong></div>'
            f"<h1>{esc(title)}</h1></header>{body}"
            f"<footer>Exportado de Nordeste el {self.now:%d/%m/%Y %H:%M}. Documento confidencial: contiene datos "
            "personales y de salud.</footer></div></body></html>"
        )

    def _patient_facts(self, p: Patient) -> list[tuple[str, str]]:
        return [("Paciente", patient_full_name(p)), ("Documento", p.document_number or "—"),
                ("Fecha de nacimiento", _fmt_date(p.birth_date)),
                ("Tipo de afiliación", AFFILIATION_LABELS.get(p.affiliation, p.affiliation))]

    def _schools(self, pid: uuid.UUID) -> str:
        return " · ".join(i.name for i in self.institutions.get(pid, []) if i.is_current) or "—"

    def _anamnesis_body(self, data: dict) -> str:
        parts = []
        for section, group, items in anamnesis_answers(data):
            if section == "Persona entrevistada":
                continue
            parts.append(
                (f"<h3>{esc(section)}{' — ' + esc(group) if group else ''}</h3>")
                + '<dl class="qa">' + "".join(
                    f"<div><dt>{esc(label)}</dt><dd>{esc(value)}</dd></div>" for _, label, value in items) + "</dl>")
        return "".join(parts) or '<p class="muted">Sin respuestas.</p>'

    def write_patient_documents(self) -> None:
        for pid, p in self.patients.items():
            folder = f"pacientes/{self.folders[pid]}"
            versions = self.anamnesis.get(pid, [])
            if versions:
                self.zip.write_text(f"{folder}/anamnesis.html", self._anamnesis_page(p, versions))
            for r in self.reports.get(pid, []):
                self.zip.write_text(self.report_paths[r.id], self._report_page(p, r))
            self.zip.write_text(f"{folder}/historia-clinica-completa.html", self._history_page(p))

    def _anamnesis_page(self, p: Patient, versions: list[AnamnesisVersion]) -> str:
        parts = []
        newest_first = list(reversed(versions))
        for i, v in enumerate(newest_first):
            data = v.data or {}
            created = self.local(v.created_at)
            label = "Versión vigente" if i == 0 else f"Versión anterior {i} de {len(newest_first) - 1}"
            interviewee = " · ".join(x for x in (data.get("entrevistado_nombre"), data.get("entrevistado_parentesco")) if x)
            parts.append(
                f'<section class="{"new-page" if i else ""}"><h2>{label}</h2>'
                + _facts([("Nombre y apellidos", patient_full_name(p)), ("Documento", p.document_number or "—"),
                          ("Fecha de nacimiento", _fmt_date(p.birth_date)),
                          ("Edad a la fecha de esta versión", age_text(p.birth_date, created.date())),
                          ("Escuela (actual)", self._schools(p.id)),
                          ("Guardada", f"{_fmt_dt(created)} por {self.user_name(v.author_id)}")])
                + self._anamnesis_body(data)
                + _signatures([(interviewee or "Persona entrevistada", "Persona entrevistada" if interviewee else None,
                                "Firma"), ("Profesional", None, "Firma y aclaración")])
                + "</section>")
        return self._page("Ficha de anamnesis multidisciplinaria", "".join(parts), depth=2)

    def _signers(self, r: Report) -> list[tuple[str, str | None]]:
        signers = [(s.get("name") or "", s.get("specialty")) for s in (r.signers or []) if isinstance(s, dict)]
        return signers or [(self.user_name(r.author_id), self.specialty_of(r.author_id) or None)]

    def _report_page(self, p: Patient, r: Report) -> str:
        signers = self._signers(r)
        body = ""
        if r.status != "final":
            body += ('<p class="warn">BORRADOR: este informe no se finalizó en Nordeste. Puede estar incompleto '
                     "y no fue firmado.</p>")
        body += _facts(self._patient_facts(p) + [
                        ("Profesionales" if len(signers) > 1 else "Profesional", ", ".join(n for n, _ in signers)),
                        ("Estado", REPORT_STATUS_LABELS.get(r.status, r.status)),
                        ("Finalizado", _fmt_dt(self.local(r.finalized_at))),
                        ("Última modificación", _fmt_dt(self.local(r.updated_at)))])
        body += f'<div style="border-top:1px solid #ccc;padding-top:1rem">{_text(r.content)}</div>'
        if r.status == "final":
            body += _signatures([(name, specialty, "Firma") for name, specialty in signers])
        return self._page(f"Informe: {r.title}", body, depth=3)

    def _history_page(self, p: Patient) -> str:
        pid = p.id
        out: list[str] = []
        address = ", ".join(x for x in (
            _join(p.address_street, p.address_number),
            f"apto. {p.address_apartment}" if p.address_apartment else "",
            f"solar {p.address_solar}" if p.address_solar else "",
            f"manzana {p.address_block}" if p.address_block else "",
            p.address_locality, p.address_department) if x)
        out.append("<h2>Datos del paciente</h2>" + _facts([
            ("Nombre completo", patient_full_name(p)), ("Documento", p.document_number or "—"),
            ("Sexo", SEX_LABELS.get(p.sex or "", "—")), ("Fecha de nacimiento", _fmt_date(p.birth_date)),
            ("Edad hoy", age_text(p.birth_date, self.now.date())),
            ("Tipo de afiliación", AFFILIATION_LABELS.get(p.affiliation, p.affiliation)),
            ("Vencimiento AYEX", _fmt_date(p.ayex_expires_on)),
            ("Sucursal", self._branch(p.branch_id) or "—"), ("Estado", STATUS_LABELS.get(p.status, p.status)),
            ("Teléfono", p.phone or "—"), ("Correo", p.email or "—"), ("Domicilio", address or "—"),
            ("Profesional responsable", self.user_name(self.responsible[pid]) if pid in self.responsible else "Sin asignar"),
            ("Fecha de registro", _fmt_dt(self.local(p.created_at)))]))

        out.append("<h2>Responsables</h2>" + _table(
            ["Nombre", "Vínculo", "Documento", "Teléfono", "Correo", "Notas"],
            [[esc(g.full_name) + (" (contacto principal)" if g.is_primary else ""), esc(g.relationship),
              esc(g.document_number or "—"), esc(g.phone or "—"), esc(g.email or "—"), esc(g.notes or "")]
             for g in self.guardians.get(pid, [])], "Sin responsables cargados."))

        out.append("<h2>Instituciones educativas</h2>" + _table(
            ["Nombre", "Nivel", "Teléfono", "Correo", "Actual"],
            [[esc(i.name), esc(INSTITUTION_LEVEL_LABELS.get(i.level, i.level)), esc(i.phone or "—"),
              esc(i.email or "—"), _yes_no(i.is_current)] for i in self.institutions.get(pid, [])],
            "Sin instituciones cargadas."))

        out.append("<h2>Profesionales con acceso (historial)</h2>" + _table(
            ["Profesional", "Nivel", "Desde", "Hasta", "Motivo"],
            [[esc(self.user_name(a.user_id)), esc(ACCESS_LABELS.get(a.level, a.level)),
              _fmt_dt(self.local(a.granted_at)), _fmt_dt(self.local(a.revoked_at)) if a.revoked_at else "Vigente",
              esc(" / ".join(x for x in (a.reason, a.revoke_reason) if x))] for a in self.accesses.get(pid, [])],
            "Sin accesos registrados."))

        versions = self.anamnesis.get(pid, [])
        out.append("<h2>Anamnesis (versión vigente)</h2>")
        if versions:
            v = versions[-1]
            out.append(f'<p class="meta">Guardada el {_fmt_dt(self.local(v.created_at))} por '
                       f'{esc(self.user_name(v.author_id))}. Todas las versiones, con firmas, en '
                       f'<a href="anamnesis.html">anamnesis.html</a> ({len(versions)} en total).</p>')
            out.append(self._anamnesis_body(v.data or {}))
        else:
            out.append('<p class="muted">Sin anamnesis estructurada (si hay una anamnesis en texto libre, está '
                       "entre las notas).</p>")

        sections = self.sections.get(pid, [])
        latest: dict[tuple[str, uuid.UUID | None], ReportSectionVersion] = {}
        for v in sections:
            latest[(v.section, v.owner_id)] = v
        for key in ("antecedentes", "diagnostico", "encuadre"):
            v = latest.get((key, None))
            out.append(f"<h2>{SECTION_LABELS[key]}</h2>")
            out.append(self._section_block(v) if v else '<p class="muted">Sin cargar.</p>')
        abordajes = [v for (section, _), v in latest.items() if section == "abordaje"]
        out.append("<h2>Abordajes</h2>")
        if not abordajes:
            out.append('<p class="muted">Sin abordajes cargados.</p>')
        for v in sorted(abordajes, key=lambda x: (self.specialty_of(x.owner_id), self.user_name(x.owner_id))):
            out.append(f"<h3>Abordaje de {esc(self.specialty_of(v.owner_id) or 'profesional')} — "
                       f"{esc(self.user_name(v.owner_id))}</h3>" + self._section_block(v))

        out.append("<h2>Historia clínica (notas)</h2>")
        notes = self.notes.get(pid, [])
        if not notes:
            out.append('<p class="muted">Sin notas.</p>')
        for n in notes:
            meta = [NOTE_KIND_LABELS.get(n.kind, n.kind)]
            if n.session_date:
                meta.append(f"sesión del {_fmt_date(n.session_date)}")
            if n.institution_id:
                meta.append(f"institución: {self.institution_names.get(n.institution_id, '')}")
            meta.append(f"escrita el {_fmt_dt(self.local(n.created_at))} por {self.user_name(n.author_id)}")
            extra = ""
            if n.supersedes_id:
                extra += (f'<p class="meta"><strong>Corrección</strong> de una nota anterior. Motivo: '
                          f"{esc(n.correction_reason or '')}</p>")
            fixed = self.corrected_by.get(n.id)
            if fixed:
                extra += (f'<p class="meta"><strong>Esta nota fue corregida</strong> el '
                          f"{_fmt_dt(self.local(fixed.created_at))} (la corrección está más abajo). Se conserva "
                          "tal como se escribió.</p>")
            out.append(f'<div class="block"><p class="meta">{esc(" · ".join(meta))}</p>{extra}{_text(n.content)}</div>')

        out.append("<h2>Plan de tratamiento (objetivos)</h2>")
        goals = self.goals.get(pid, [])
        if not goals:
            out.append('<p class="muted">Sin objetivos.</p>')
        for g in goals:
            updates = self.goal_updates.get(g.id, [])
            rows = [[_fmt_date(u.session_date) if u.session_date else _fmt_dt(self.local(u.created_at)),
                     f"{u.progress} %", esc(GOAL_STATUS_LABELS.get(u.new_status or "", "") or ""),
                     esc(u.note), esc(self.user_name(u.author_id))] for u in updates]
            out.append(
                f'<div class="block"><p class="meta">{esc(g.area)} · {esc(GOAL_STATUS_LABELS.get(g.status, g.status))}'
                f" · {g.progress} % · fecha objetivo {_fmt_date(g.target_date)} · creado el "
                f"{_fmt_dt(self.local(g.created_at))} por {esc(self.user_name(g.created_by))}</p>{_text(g.description)}"
                + (_table(["Fecha", "Progreso", "Nuevo estado", "Nota", "Autor"], rows, "") if rows else "") + "</div>")

        out.append("<h2>Informes</h2>")
        reports = self.reports.get(pid, [])
        if not reports:
            out.append('<p class="muted">Sin informes.</p>')
        for r in reports:
            link = self.report_paths[r.id].split("/", 2)[2]  # relativo a la carpeta del paciente
            state = REPORT_STATUS_LABELS.get(r.status, r.status)
            out.append(
                f'<div class="block"><h3>{esc(r.title)}</h3><p class="meta">{esc(state)} · de '
                f"{esc(', '.join(n for n, _ in self._signers(r)))} · "
                f"{'finalizado el ' + _fmt_dt(self.local(r.finalized_at)) if r.finalized_at else 'última modificación ' + _fmt_dt(self.local(r.updated_at))}"
                f' · <a href="{esc(quote(link))}">documento para imprimir</a></p>{_text(r.content)}</div>')

        out.append("<h2>Turnos</h2>" + _table(
            ["Fecha y hora", "Profesional", "Sucursal", "Estado", "Motivo"],
            [[_fmt_dt(self.local(a.starts_at)), esc(self.user_name(a.professional_id)), esc(self._branch(a.branch_id)),
              esc(APPOINTMENT_LABELS.get(a.status, a.status)),
              esc(a.cancel_reason or a.reschedule_reason or a.no_show_reason or "")]
             for a in self.appointments.get(pid, [])], "Sin turnos."))

        rows = []
        for f in self.files.get(pid, []):
            path, state = self.file_results[f.id]
            name = esc(f.original_name)
            if state != "No estaba en el servidor":
                name = f'<a href="{esc(quote(path.split("/", 2)[2]))}">{name}</a>'
            rows.append([name, _fmt_dt(self.local(f.created_at)), esc(f.description or ""),
                         esc(f"Retirado: {f.withdraw_reason or ''}" if f.withdrawn_at else state)])
        out.append("<h2>Archivos adjuntos</h2>" + _table(["Archivo", "Subido", "Descripción", "Estado"], rows,
                                                           "Sin archivos."))

        history = [v for v in sections if latest.get((v.section, v.owner_id)) is not v]
        if history:
            out.append('<h2 class="new-page">Versiones anteriores de antecedentes, diagnóstico, encuadre y abordajes</h2>')
            for v in reversed(history):
                who = f" de {self.user_name(v.owner_id)}" if v.owner_id else ""
                out.append(f"<h3>{SECTION_LABELS.get(v.section, v.section)}{esc(who)}</h3>" + self._section_block(v))

        return self._page(f"Historia clínica completa: {patient_full_name(p)}", "".join(out), depth=2)

    def _section_block(self, v: ReportSectionVersion) -> str:
        data = v.data or {}
        fields = SECTION_FIELDS.get(v.section, tuple(data.keys()))
        inner = "".join(
            (f"<p><strong>{SECTION_FIELD_LABELS.get(k, k)}</strong></p>" if len(fields) > 1 else "")
            + _text(str(data.get(k) or "—")) for k in fields)
        return (f'<div class="block"><p class="meta">Guardado el {_fmt_dt(self.local(v.created_at))} por '
                f"{esc(self.user_name(v.author_id))}</p>{inner}</div>")

    # --- LEEME y huellas ---

    def write_readme(self) -> None:
        c = self.clinic
        kind = "espacio de profesional independiente" if self.independent else "clínica"
        counts = {t.name: t.count for t in self.tables}
        L: list[str] = []
        L += [f"EXPORTACIÓN COMPLETA DE DATOS — {c.name}", "=" * 60, "",
              f"Generada por Nordeste el {self.now:%d/%m/%Y a las %H:%M} (hora de Uruguay).",
              f"Contiene todos los datos de esta {kind} guardados en Nordeste hasta ese momento, y ningún dato",
              "de otras clínicas.", "",
              "CONFIDENCIAL: este archivo contiene datos personales y de salud de pacientes. Guardalo en un",
              "lugar seguro (por ejemplo, una carpeta o disco cifrado) y no lo envíes por correo común.", "",
              "RESUMEN", "-------",
              f"Pacientes: {len(self.patients)}",
              f"Notas de historia clínica: {counts.get('11-notas-clinicas', 0)}",
              f"Versiones de anamnesis: {sum(len(v) for v in self.anamnesis.values())}",
              f"Informes: {counts.get('14-informes', 0)}",
              f"Turnos: {counts.get('10-turnos', 0)}",
              f"Archivos copiados (adjuntos de pacientes y títulos): {self.files_copied}"
              + (f" (faltaban en el servidor: {self.files_missing})" if self.files_missing else ""),
              f"Cuentas de usuario: {len(self.users)}", "",
              "QUÉ HAY EN CADA CARPETA", "-----------------------",
              "pacientes/", "  Una carpeta por paciente: «Apellido, Nombre (código)». El código son los primeros",
              "  caracteres del identificador del paciente (columna «id» de las planillas). Adentro:",
              "  - historia-clinica-completa.html: todo lo del paciente en un solo documento (datos,",
              "    responsables, instituciones, accesos, anamnesis vigente, antecedentes, diagnóstico,",
              "    encuadre, abordajes, notas con sus correcciones, objetivos, informes, turnos y archivos).",
              "  - anamnesis.html: la ficha de anamnesis vigente y todas sus versiones anteriores, con firmas.",
              "  - informes/: un documento por informe, con firmas. Los que dicen BORRADOR no se finalizaron.",
              "  - archivos/: los adjuntos con su nombre original y la fecha en que se subieron.",
              "    archivos/retirados/: los que alguien retiró en Nordeste (no se borraban, solo se ocultaban).",
              "  Los .html se abren con doble clic en cualquier navegador. Para guardarlos como PDF:",
              "  Cmd + P (Mac) o Ctrl + P (Windows) y elegir «Guardar como PDF».", "",
              "planillas/", "  Una planilla Excel (.xlsx) por tipo de dato, para mirar, ordenar y filtrar. Se abren",
              "  con Excel, Numbers, LibreOffice o Google Sheets. Todas las fechas y horas están en hora de",
              "  Uruguay. Las columnas «id_...» sirven para relacionar una planilla con otra.", "",
              "datos-csv/", "  Las mismas tablas en formato CSV (texto UTF-8 separado por comas), con el texto",
              "  completo. Es el formato para importar los datos en otro sistema. Para MIRAR los datos usá",
              "  las planillas: si abrís un CSV con Excel, puede mostrar mal algunos textos.", "",
              "clinica/", "  Logo de la clínica y títulos de los profesionales (cada uno en su carpeta).", "",
              "huellas-sha256.txt", "  Una «huella» de cada archivo. Sirve para comprobar que nada se dañó o cambió: en",
              "  una Mac, en la Terminal, `shasum -a 256 ARCHIVO`; en Windows, `certutil -hashfile ARCHIVO",
              "  SHA256`. El resultado tiene que ser igual al que figura en la lista.", "",
              "PLANILLAS", "---------"]
        descriptions = {
            "01-clinica": "datos de la clínica",
            "02-sucursales": "sucursales (consultorios)",
            "03-especialidades": "especialidades o profesiones",
            "04-usuarios": "cuentas de la clínica (sin contraseñas)",
            "05-horarios": "horarios de atención de cada profesional",
            "06-pacientes": "pacientes (datos administrativos)",
            "07-responsables": "responsables o tutores de cada paciente",
            "08-instituciones": "instituciones educativas de cada paciente",
            "09-accesos-profesionales": "qué profesional tuvo acceso a cada paciente, desde y hasta cuándo",
            "10-turnos": "turnos de la agenda",
            "11-notas-clinicas": "notas de historia clínica; las correcciones son filas nuevas que dicen "
                                 "a qué nota corrigen y por qué",
            "12-anamnesis": "una fila por respuesta y por versión de la anamnesis",
            "13-antecedentes-diagnostico-encuadre-abordajes": "todas las versiones de esas secciones",
            "14-informes": "informes (borradores y finalizados)",
            "15-objetivos": "objetivos del plan de tratamiento",
            "16-avances-de-objetivos": "avances registrados de cada objetivo",
            "17-archivos": "índice de los archivos adjuntos y dónde quedó cada uno",
            "18-avisos": "avisos a los profesionales",
            "19-titulos-profesionales": "índice de los títulos subidos por los profesionales",
            "20-cajas": "cajas diarias",
            "21-movimientos-de-caja": "entradas y salidas de cada caja",
            "22-auditoria": "registro de auditoría: quién hizo qué y cuándo («Soporte de Nordeste» son las "
                            "acciones del responsable de Nordeste)",
        }
        for t in sorted(self.tables, key=lambda t: t.name):
            line = f"- {t.name}: {descriptions.get(t.name, '')} ({t.count} {'fila' if t.count == 1 else 'filas'})"
            if t.parts > 1:
                line += f". Partida en {t.parts} planillas por su tamaño"
            if t.truncated:
                line += (f". {t.truncated} {'texto muy largo se cortó' if t.truncated == 1 else 'textos muy largos se cortaron'}"
                         " en Excel (completos en el CSV)")
            L.append(line)
        L += ["", "SIGNIFICADO DE LOS VALORES", "--------------------------",
              "Estado del paciente: " + " · ".join(STATUS_LABELS.values()) + ".",
              "Tipo de afiliación: " + " · ".join(AFFILIATION_LABELS.values()) + ".",
              "Estado del turno: " + " · ".join(APPOINTMENT_LABELS.values()) + ".",
              "Tipo de nota: " + " · ".join(NOTE_KIND_LABELS.values()) + ".",
              "Acceso a un paciente: Responsable (profesional a cargo) · Colaborador/a (acceso compartido).",
              "Rol de una cuenta: " + " · ".join(ROLE_LABELS.values()) + ".",
              "Estado de un objetivo: " + " · ".join(GOAL_STATUS_LABELS.values()) + ".",
              "Las notas clínicas, anamnesis y secciones nunca se editaban ni se borraban en Nordeste: cada cambio",
              "es una versión o corrección nueva, y acá están todas.", ""]
        if self.warnings:
            L += ["AVISOS", "------", *[f"- {w}" for w in self.warnings], ""]
        self.zip.write_text("LEEME.txt", "\n".join(L) + "\n")

    def write_hashes(self) -> None:
        lines = [f"{sha}  {name}" for sha, name in sorted(self.zip.hashes, key=lambda x: x[1])]
        self.zip.write_text("huellas-sha256.txt", "\n".join(lines) + "\n")

    def run(self) -> ExportResult:
        try:
            self.load()
            self.copy_patient_files()
            self.copy_clinic_files()
            self.write_tables()
            self.write_patient_documents()
            self.write_readme()
            self.write_hashes()
        finally:
            self.zip.close()
        return ExportResult(path=self.path, filename=self.path.name, patients=len(self.patients),
                            files=self.files_copied, missing_files=self.files_missing,
                            size_bytes=self.path.stat().st_size)


def build_clinic_export(db: Session, clinic_id: uuid.UUID, workdir: Path) -> ExportResult:
    """Arma el .zip de la clínica dentro de ``workdir`` (una carpeta temporal que borra quien llama)."""
    return _ClinicExporter(db, clinic_id, workdir).run()
