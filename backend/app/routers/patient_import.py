"""Importación de pacientes desde un archivo CSV (por ejemplo, guardado desde Excel) o desde
la planilla del Cronograma de Actividades del BPS (.xlsx).

Cronograma BPS: se leen los pacientes de la hoja USUARIOS (documento, apellidos, nombres,
teléfono y dirección; las mismas columnas que llena "Exportar a Cronograma BPS"). Entran
como pacientes AYEX. Los que ya están en Nordeste (mismo documento) se saltean sin dar error,
porque el cronograma de cada mes repite a todos los pacientes. Los horarios de las hojas
LUN a SAB no se importan.

Flujo en dos pasos con el MISMO archivo:
1. ``dry_run=true``: revisa cada fila y devuelve qué se cargaría y qué errores hay.
   No guarda nada.
2. ``dry_run=false``: vuelve a revisar todo en el servidor (no confía en la vista previa)
   y crea solo las filas correctas, en una única operación.

Privacidad: el archivo no se guarda en disco ni en la base; solo se crean los pacientes.
La auditoría registra cada alta como "patient.import", sin copiar los datos.
"""

import csv
import io
import re
import unicodedata
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app import audit
from app.db import get_db
from app.deps import CurrentUser, require_staff_or_titular
from app.branches import allowed_branches
from app.models import AccessLevel, Patient, PatientAccess, PatientStatus, Role, User
from app.schemas import PatientAddress, PatientCreateIn, validation_message
from app.xlsx_read import XlsxReader, XlsxReadError, is_xlsx

router = APIRouter(prefix="/api/patient-import", tags=["importación de pacientes"])
staff_only = require_staff_or_titular  # también el titular de un espacio independiente

MAX_BYTES = 2 * 1024 * 1024
MAX_ROWS = 2000
IMPORT_REASON = "Asignación al importar pacientes"

# Columnas de la planilla modelo, en orden.
TEMPLATE_COLUMNS = [
    "documento", "primer_nombre", "segundo_nombre", "primer_apellido", "segundo_apellido",
    "sexo", "tipo_afiliacion", "vencimiento_ayex", "fecha_nacimiento", "telefono", "correo",
    "profesional_responsable", "sucursal",
]

# Nombre de columna (normalizado) -> campo. Acepta variantes habituales.
_ALIASES = {
    "document_number": ["documento", "cedula", "ci", "cedula_de_identidad", "numero_de_documento",
                        "nro_documento", "n_documento", "doc"],
    "first_name": ["primer_nombre", "nombre", "nombres"],
    "middle_name": ["segundo_nombre"],
    "last_name": ["primer_apellido", "apellido", "apellidos"],
    "second_last_name": ["segundo_apellido"],
    "sex": ["sexo"],
    "affiliation": ["tipo_afiliacion", "tipo_de_afiliacion", "afiliacion", "cobertura"],
    "ayex_expires_on": ["vencimiento_ayex", "vence_ayex", "fecha_vencimiento_ayex",
                        "vencimiento_del_ayex", "vencimiento"],
    "birth_date": ["fecha_nacimiento", "fecha_de_nacimiento", "nacimiento", "f_nacimiento"],
    "phone": ["telefono", "celular", "tel"],
    "email": ["correo", "correo_electronico", "email", "e_mail", "mail"],
    "responsible": ["profesional_responsable", "responsable", "profesional"],
    "branch": ["sucursal"],
    "address": ["direccion", "domicilio"],
}
_HEADER_TO_FIELD = {alias: field for field, aliases in _ALIASES.items() for alias in aliases}
_REQUIRED = {"first_name": "primer_nombre", "last_name": "primer_apellido",
             "affiliation": "tipo_afiliacion"}

_FIELD_LABELS = {
    "document_number": "Documento", "first_name": "Primer nombre", "middle_name": "Segundo nombre",
    "last_name": "Primer apellido", "second_last_name": "Segundo apellido", "sex": "Sexo",
    "affiliation": "Tipo de afiliación", "ayex_expires_on": "Vencimiento del AYEX",
    "branch_id": "Sucursal",
    "birth_date": "Fecha de nacimiento", "phone": "Teléfono", "email": "Correo",
    "responsible": "Profesional responsable",
    **{f"address_{part}": "Dirección" for part in
       ("department", "locality", "street", "number", "apartment", "solar", "block")},
}

_SEX = {
    "m": "male", "masc": "male", "masculino": "male", "hombre": "male", "varon": "male",
    "f": "female", "fem": "female", "femenino": "female", "mujer": "female",
    "x": "unspecified", "otro": "unspecified", "sin_indicar": "unspecified",
    "no_indica": "unspecified", "sin_especificar": "unspecified", "no_especifica": "unspecified",
}
_AFFILIATION = {
    "privado": "private", "privada": "private", "particular": "private", "private": "private",
    "ayex": "ayex",
    "tutela_militar": "military", "militar": "military", "convenio_militar": "military",
    "sanidad_militar": "military", "military": "military",
    "tutela_policial": "police", "policial": "police", "sanidad_policial": "police",
    "police": "police",
}
_DATE_FORMATS = ("%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%Y-%m-%d")


class ImportRowOut(BaseModel):
    line: int
    status: str  # "ok", "error", "created" o "skipped" (ya está en Nordeste; solo Cronograma BPS)
    document_number: str | None = None
    full_name: str = ""
    affiliation: str | None = None
    branch_name: str | None = None
    birth_date: date | None = None
    ayex_expires_on: date | None = None
    responsible_name: str | None = None
    errors: list[str] = []
    note: str | None = None


class ImportResultOut(BaseModel):
    total: int
    valid: int
    invalid: int
    created: int
    skipped: int = 0
    ignored_columns: list[str]
    rows: list[ImportRowOut]


# ---------- Lectura del archivo ----------


def _normalize(text: str) -> str:
    """'Fecha de Nacimiento ' -> 'fecha_de_nacimiento' (sin tildes ni mayúsculas)."""
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def _decode(data: bytes) -> str:
    """UTF-8 (con o sin BOM) o, si no, la codificación de Excel en Windows o Mac."""
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        pass
    candidates = [data.decode(enc, errors="replace") for enc in ("cp1252", "mac_roman")]
    return max(candidates, key=lambda t: sum(t.count(c) for c in "áéíóúñÁÉÍÓÚÑü"))


def _read_rows(data: bytes) -> tuple[list[str], list[tuple[int, list[str]]], str]:
    """Encabezado, filas (número de línea, valores) y origen: "bps" (Excel del Cronograma) o "csv"."""
    if is_xlsx(data):
        header, rows = _read_bps_rows(data)
        return header, rows, "bps"
    header, rows = _read_csv_rows(data)
    return header, rows, "csv"


def _read_csv_rows(data: bytes) -> tuple[list[str], list[tuple[int, list[str]]]]:
    text = _decode(data)
    first_line = text.split("\n", 1)[0]
    delimiter = max((";", ",", "\t"), key=first_line.count)
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    try:
        header = next(reader)
    except StopIteration:
        raise HTTPException(422, detail="El archivo está vacío.") from None
    rows = []
    for values in reader:
        if not any(v.strip() for v in values):
            continue  # filas vacías: se ignoran
        if len(rows) >= MAX_ROWS:
            raise HTTPException(413, detail=f"El archivo tiene más de {MAX_ROWS} pacientes. Dividilo en partes.")
        rows.append((reader.line_num, values))
    return header, rows


def _map_columns(header: list[str]) -> tuple[dict[int, str], list[str]]:
    columns, ignored, used = {}, [], set()
    for index, name in enumerate(header):
        field = _HEADER_TO_FIELD.get(_normalize(name))
        if field and field not in used:
            columns[index] = field
            used.add(field)
        elif name.strip():
            ignored.append(name.strip()[:60])
    missing = [col for field, col in _REQUIRED.items() if field not in used]
    if missing:
        raise HTTPException(
            422,
            detail=f"Faltan columnas obligatorias: {', '.join(missing)}. "
                   "Descargá la planilla modelo para ver los nombres de las columnas.",
        )
    return columns, ignored


# ---------- Cronograma BPS (.xlsx) ----------

# Columnas A a G de la hoja USUARIOS, en orden, con los nombres que entiende la importación.
BPS_COLUMNS = ["documento", "primer_apellido", "segundo_apellido", "primer_nombre",
               "segundo_nombre", "telefono", "direccion"]
_NOT_BPS = ("Este Excel no es un Cronograma del BPS: tiene que tener la hoja USUARIOS con las "
            "columnas DOCUMENTO, 1er APELLIDO, 2do APELLIDO, 1er NOMBRE, 2do NOMBRE, TELÉFONO y "
            "DIRECCIÓN. Para otras planillas, guardalas como CSV y usá «Importar desde CSV».")


def _bps_text(value, column: str) -> str:
    if value is None:
        return ""
    if isinstance(value, int) and column == "telefono":
        text = str(value)
        # Un celular escrito como número pierde el 0: Excel guarda 099123456 como 99123456.
        return "0" + text if len(text) == 8 and text.startswith("9") else text
    return str(value).strip()


def _read_bps_rows(data: bytes) -> tuple[list[str], list[tuple[int, list[str]]]]:
    """La hoja USUARIOS como si fuera un CSV: mismas columnas que entiende la importación,
    más "tipo_afiliacion" = AYEX (todos los pacientes del cronograma son AYEX). Así el CSV de
    filas con errores se puede corregir y volver a importar como cualquier otro."""
    try:
        book = XlsxReader(data)
        sheet = next((s for s in book.sheet_names() if _normalize(s) == "usuarios"), None)
        if sheet is None:
            raise HTTPException(422, detail=_NOT_BPS)
        rows = book.rows(sheet, len(BPS_COLUMNS))
    except XlsxReadError as exc:
        raise HTTPException(422, detail=str(exc)) from None
    header = [_normalize(str(v or "")) for v in rows[0][1]] if rows and rows[0][0] == 1 else []
    if not (header and header[0].startswith(("documento", "cedula", "ci"))
            and "apellido" in header[1] and "nombre" in header[3]):
        raise HTTPException(422, detail=_NOT_BPS)
    out = []
    for line, values in rows[1:]:
        if len(out) >= MAX_ROWS:
            raise HTTPException(413, detail=f"El archivo tiene más de {MAX_ROWS} pacientes. Dividilo en partes.")
        out.append((line, [_bps_text(v, c) for v, c in zip(values, BPS_COLUMNS)] + ["AYEX"]))
    return [*BPS_COLUMNS, "tipo_afiliacion"], out


_DEPARTMENTS = {_normalize(d): d for d in (
    "Artigas", "Canelones", "Cerro Largo", "Colonia", "Durazno", "Flores", "Florida", "Lavalleja",
    "Maldonado", "Montevideo", "Paysandú", "Río Negro", "Rivera", "Rocha", "Salto", "San José",
    "Soriano", "Tacuarembó", "Treinta y Tres",
)}
_APARTMENT_RE = re.compile(r"^(.*?)[\s,]+(?:apto|apt|ap)\b\.?\s*(?:n[°º]\s*)?(\S*\d\S*)$", re.I)


def _split_address(text: str) -> dict[str, str]:
    """La dirección viene en un solo texto. Si termina en un departamento (como la escribe
    Nordeste al exportar: "Calle 1234 apto 5, Localidad, Departamento") se separa en partes;
    si no, va entera en "Calle" y se puede ordenar después en la ficha del paciente."""
    text = " ".join(text.split())
    parts = [p.strip() for p in text.split(",") if p.strip()]
    out: dict[str, str] = {}
    if len(parts) >= 2 and _normalize(parts[-1]) in _DEPARTMENTS:
        out["address_department"] = _DEPARTMENTS[_normalize(parts.pop())]
        if len(parts) >= 2:
            out["address_locality"] = parts.pop()
        street = ", ".join(parts)
    else:
        street = text
    m = _APARTMENT_RE.match(street)
    if m and m.group(1):
        street, out["address_apartment"] = m.group(1).strip(), m.group(2)
    if street:
        out["address_street"] = street
    return out


# ---------- Revisión de cada fila ----------


def _doc_key(document: str) -> str:
    """Documento sin puntos, guiones ni espacios: "1.234.567-8" y "12345678" son el mismo."""
    return re.sub(r"[^0-9A-Z]", "", document.upper())


def _parse_date(text: str, label: str = "Fecha de nacimiento") -> date:
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"{label} no válida: revisá que el día exista y usá el formato DD/MM/AAAA.")


def _professional_index(db: Session, clinic_id) -> dict[str, User]:
    """Profesionales activos de la clínica, buscables por correo o por nombre completo."""
    profs = db.scalars(select(User).where(
        User.clinic_id == clinic_id, User.role == Role.professional.value, User.is_active.is_(True),
    )).all()
    index = {}
    for p in profs:
        index[p.email.lower()] = p
        index[_normalize(p.full_name)] = p
    return index


def _check_rows(db: Session, user: CurrentUser, data: bytes):
    header, raw_rows, source = _read_rows(data)
    columns, ignored = _map_columns(header)
    existing_docs = {_doc_key(d) for d in db.scalars(select(Patient.document_number).where(
        Patient.clinic_id == user.clinic_id, Patient.document_number.is_not(None))).all()}
    professionals = _professional_index(db, user.clinic_id)
    # Espacio independiente: el titular queda como responsable de todo lo que importa (si no,
    # no vería esos pacientes) y la columna "profesional_responsable" no se tiene en cuenta.
    titular = db.get(User, user.id) if user.is_titular else None
    # Sucursales donde quien importa puede cargar pacientes (sin columna: la sucursal activa).
    allowed = allowed_branches(db, user.clinic_id, user.id, user.role)
    branches_by_name = {_normalize(b.name): b for b in allowed}
    active_branch = next((b for b in allowed if b.id == user.branch_id), None)
    seen_docs: dict[str, int] = {}
    checked = []  # (fila de salida, datos validados o None, profesional o None)

    for line, values in raw_rows:
        raw = {field: (values[i].strip() if i < len(values) else "") for i, field in columns.items()}
        errors: list[str] = []
        fields: dict = {k: raw.get(k) or None for k in
                        ("document_number", "first_name", "middle_name", "last_name",
                         "second_last_name", "phone", "email")}
        if raw.get("address"):
            fields.update(_split_address(raw["address"]))
        if raw.get("sex"):
            sex = _SEX.get(_normalize(raw["sex"]))
            if sex is None:
                errors.append("Sexo no reconocido: usá M, F o X.")
            fields["sex"] = sex
        if raw.get("affiliation"):
            affiliation = _AFFILIATION.get(_normalize(raw["affiliation"]))
            if affiliation is None:
                errors.append("Tipo de afiliación no reconocido: usá Privado, AYEX, Tutela Militar o Tutela Policial.")
                fields["affiliation"] = None  # ya avisado: no repetir "obligatorio"
            else:
                fields["affiliation"] = affiliation
        if raw.get("birth_date"):
            try:
                fields["birth_date"] = _parse_date(raw["birth_date"])
            except ValueError as exc:
                errors.append(str(exc))
        # Vencimiento del AYEX: opcional al importar (los que queden sin fecha se avisan en
        # el Inicio); solo se guarda para pacientes AYEX.
        if raw.get("ayex_expires_on") and fields.get("affiliation") == "ayex":
            try:
                fields["ayex_expires_on"] = _parse_date(raw["ayex_expires_on"], "Fecha de vencimiento del AYEX")
            except ValueError as exc:
                errors.append(str(exc))
        branch = active_branch
        if raw.get("branch"):
            branch = branches_by_name.get(_normalize(raw["branch"]))
            if branch is None:
                errors.append("Sucursal no encontrada o no permitida para tu cuenta.")
        if branch is not None:
            fields["branch_id"] = branch.id
        prof = titular
        if titular is None and raw.get("responsible"):
            key = raw["responsible"]
            prof = professionals.get(key.lower()) or professionals.get(_normalize(key))
            if prof is None:
                errors.append("Profesional responsable no encontrado: escribí su correo o su nombre "
                              "completo tal como figura en Nordeste.")

        payload = None
        try:
            payload = PatientCreateIn(**{k: v for k, v in fields.items() if v is not None})
        except ValidationError as exc:
            for err in exc.errors():
                field = str(err["loc"][0]) if err.get("loc") else ""
                if field == "affiliation" and "affiliation" in fields:
                    continue
                errors.append(f"{_FIELD_LABELS.get(field, field)}: {validation_message(err)}")

        doc = payload.document_number if payload else None
        # Cronograma BPS: trae a todos los AYEX, también a los que ya están en Nordeste. Esos se
        # saltean (no es un error, aunque algún dato de la planilla esté mal escrito).
        known = doc or fields.get("document_number")
        skipped = source == "bps" and bool(known) and _doc_key(known) in existing_docs
        if skipped:
            errors = []
        elif doc:
            key = _doc_key(doc)
            if key in existing_docs:
                errors.append("Ya existe un paciente con ese documento en la clínica.")
            elif key in seen_docs:
                errors.append(f"Documento repetido en el archivo (también en la línea {seen_docs[key]}).")
            else:
                seen_docs[key] = line

        names = (fields.get("first_name"), fields.get("middle_name"), fields.get("last_name"),
                 fields.get("second_last_name"))
        row = ImportRowOut(
            line=line, status="error" if errors else ("skipped" if skipped else "ok"),
            document_number=doc or fields.get("document_number"),
            full_name=" ".join(n for n in names if n)[:200],
            affiliation=fields.get("affiliation"),
            birth_date=fields.get("birth_date") if isinstance(fields.get("birth_date"), date) else None,
            ayex_expires_on=payload.ayex_expires_on if payload else None,
            responsible_name=prof.full_name if prof else (raw.get("responsible") or None),
            branch_name=branch.name if branch else (raw.get("branch") or None),
            errors=errors,
            note="Ya está en Nordeste: no se vuelve a cargar." if skipped else None,
        )
        checked.append((row, None if errors or skipped else payload, prof))
    return checked, ignored, source


def _run_import(db: Session, user: CurrentUser, data: bytes, dry_run: bool,
                request: Request) -> ImportResultOut:
    checked, ignored, source = _check_rows(db, user, data)
    extra = {"details": {"kind": "bps_schedule"}} if source == "bps" else {}
    created = 0
    if not dry_run:
        for row, payload, prof in checked:
            if payload is None:
                continue
            patient = Patient(
                clinic_id=user.clinic_id, branch_id=payload.branch_id, first_name=payload.first_name,
                middle_name=payload.middle_name, last_name=payload.last_name,
                second_last_name=payload.second_last_name, document_number=payload.document_number,
                sex=payload.sex.value if payload.sex else None,
                affiliation=payload.affiliation.value, birth_date=payload.birth_date,
                ayex_expires_on=payload.ayex_expires_on,
                phone=payload.phone, email=payload.email, status=PatientStatus.active.value,
                created_by=user.id, **payload.model_dump(include=set(PatientAddress.model_fields)),
            )
            db.add(patient)
            db.flush()
            audit.record(db, clinic_id=user.clinic_id, actor_id=user.id, action="patient.import",
                         entity_type="patient", entity_id=patient.id, patient_id=patient.id,
                         request=request, **extra)
            if prof is not None:
                db.add(PatientAccess(
                    clinic_id=user.clinic_id, patient_id=patient.id, user_id=prof.id,
                    level=AccessLevel.responsible.value, reason=IMPORT_REASON, granted_by=user.id,
                ))
            row.status = "created"
            created += 1
        db.commit()
    valid = sum(1 for _, payload, _ in checked if payload is not None)
    return ImportResultOut(
        total=len(checked), valid=valid, created=created,
        invalid=sum(1 for row, _, _ in checked if row.status == "error"),
        skipped=sum(1 for row, _, _ in checked if row.status == "skipped"),
        ignored_columns=ignored, rows=[row for row, _, _ in checked],
    )


# ---------- Endpoints ----------


@router.get("/template")
def download_template(user: CurrentUser = Depends(staff_only)):
    """Planilla modelo vacía (solo los encabezados), lista para abrir en Excel."""
    content = "﻿" + ";".join(TEMPLATE_COLUMNS) + "\r\n"
    return Response(
        content=content.encode("utf-8"), media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="lumen-pacientes-modelo.csv"',
                 "X-Content-Type-Options": "nosniff"},
    )


async def _read_body(request: Request) -> bytes:
    chunks, size = [], 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > MAX_BYTES:
            raise HTTPException(413, detail="El archivo supera el máximo de 2 MB.")
        chunks.append(chunk)
    data = b"".join(chunks)
    if not data.strip():
        raise HTTPException(422, detail="El archivo está vacío.")
    return data


def _error_rows_csv(db: Session, user: CurrentUser, data: bytes, request: Request) -> bytes:
    """Las filas con errores, tal como venían, más una columna "errores": para corregirlas en
    Excel e importar solo ese archivo (sin volver a cargar las que ya entraron)."""
    header, raw_rows, _ = _read_rows(data)
    checked, _, _ = _check_rows(db, user, data)
    errors_by_line = {row.line: row.errors for row, _, _ in checked if row.status == "error"}
    out = io.StringIO()
    writer = csv.writer(out, delimiter=";", lineterminator="\r\n")
    writer.writerow([*header, "errores"])
    for line, values in raw_rows:
        if line in errors_by_line:
            padded = values + [""] * (len(header) - len(values))
            writer.writerow([*padded[:len(header)], " | ".join(errors_by_line[line])])
    audit.record(db, clinic_id=user.clinic_id, actor_id=user.id, action="patient.import_errors",
                 entity_type="patient", details={"count": len(errors_by_line)}, request=request)
    db.commit()
    return ("\ufeff" + out.getvalue()).encode("utf-8")


@router.post("/errors")
async def download_error_rows(
    request: Request,
    user: CurrentUser = Depends(staff_only),
    db: Session = Depends(get_db),
):
    """Devuelve un CSV con las filas del archivo que tienen errores (no guarda nada)."""
    data = await _read_body(request)
    content = await run_in_threadpool(_error_rows_csv, db, user, data, request)
    return Response(
        content=content, media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="lumen-pacientes-con-errores.csv"',
                 "X-Content-Type-Options": "nosniff", "Cache-Control": "no-store"},
    )


@router.post("", response_model=ImportResultOut)
async def import_patients(
    request: Request,
    dry_run: bool = True,
    user: CurrentUser = Depends(staff_only),
    db: Session = Depends(get_db),
):
    """Revisa (``dry_run=true``) o importa (``dry_run=false``) un CSV de pacientes.

    El cuerpo de la petición es el archivo tal cual.
    """
    data = await _read_body(request)
    return await run_in_threadpool(_run_import, db, user, data, dry_run, request)
