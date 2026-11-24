"""Formulario del BPS "Solicitud de liquidación – Ayuda Extraordinaria" (AYEX), completado con
los datos que Lumen ya tiene del paciente.

Se usa el PDF original del BPS (``app/forms/solicitud_ayex_bps.pdf``, con sus campos
rellenables): se completan los campos conocidos y el resto queda en blanco y EDITABLE, para
terminarlo a mano (transporte, firmas, sellos). Solo para pacientes AYEX, y solo lo descargan
administración y recepción (son datos administrativos). Cada descarga queda en la auditoría.
"""

import io
import re
import unicodedata
import uuid
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pypdf import PdfReader, PdfWriter
from pypdf.generic import BooleanObject, NameObject
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import audit
from app.db import get_db
from app.deps import CurrentUser, require_staff_or_titular
from app.features import require_feature
from app.models import (
    AccessLevel, AffiliationType, Appointment, AppointmentStatus, Clinic, Patient, PatientAccess,
    PatientGuardian, Specialty, User,
)
from app.bps import weekly_appointments
from app.permissions import get_visible_patient

router = APIRouter(prefix="/api/patients", tags=["formulario AYEX"],
                   dependencies=[Depends(require_feature("bps"))])

TEMPLATE = Path(__file__).resolve().parent.parent / "forms" / "solicitud_ayex_bps.pdf"
WEEKDAY_FIELDS = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado"]  # el BPS no usa domingo
MAX_ROWS = 4  # filas de actividades del formulario


def _digits(value: str | None) -> str:
    """C.I. solo con números (el formulario la valida así): "1.234.567-8" → "12345678"."""
    return re.sub(r"\D", "", value or "")


def _upper(value: str | None) -> str:
    return (value or "").upper()


def _hhmm(dt: datetime, tz: ZoneInfo) -> str:
    return dt.astimezone(tz).strftime("%H:%M")


def _activities(db: Session, clinic_id: uuid.UUID, patient: Patient, tz: ZoneInfo) -> list[dict]:
    """Hasta 4 filas: cada profesional que atiende al paciente (responsable primero), su
    especialidad como actividad y, por día de la semana, su horario según la Agenda."""
    rows = db.execute(
        select(PatientAccess.level, User.id, User.full_name, Specialty.name)
        .join(User, (User.id == PatientAccess.user_id) & (User.clinic_id == PatientAccess.clinic_id))
        .outerjoin(Specialty, (Specialty.id == User.specialty_id) & (Specialty.clinic_id == User.clinic_id))
        .where(PatientAccess.clinic_id == clinic_id, PatientAccess.patient_id == patient.id,
               PatientAccess.revoked_at.is_(None), User.is_active.is_(True), User.archived_at.is_(None))
    ).all()
    # Días y horarios: el horario semanal según la Agenda (también turnos ya pasados).
    appts = weekly_appointments(db, clinic_id, [patient.id], tz)
    result = []
    for level, user_id, name, specialty in rows:
        days: dict[int, list[str]] = {}
        for a in appts:
            if a.professional_id != user_id:
                continue
            weekday = a.starts_at.astimezone(tz).weekday()
            start, end = _hhmm(a.starts_at, tz), _hhmm(a.ends_at, tz)
            if weekday in days:  # varios turnos el mismo día: del primero al último
                days[weekday] = [min(days[weekday][0], start), max(days[weekday][1], end)]
            else:
                days[weekday] = [start, end]
        result.append({"responsible": level == AccessLevel.responsible.value, "name": name,
                       "activity": specialty or "", "days": days})
    # Responsable primero; después quienes tienen turnos; luego por nombre.
    result.sort(key=lambda r: (not r["responsible"], not r["days"], r["name"]))
    return result[:MAX_ROWS]


def _first_session_this_year(db: Session, clinic_id: uuid.UUID, patient_id: uuid.UUID,
                             tz: ZoneInfo) -> str:
    year_start = datetime(datetime.now(tz).year, 1, 1, tzinfo=tz)
    first = db.scalar(select(Appointment.starts_at).where(
        Appointment.clinic_id == clinic_id, Appointment.patient_id == patient_id,
        Appointment.status == AppointmentStatus.completed.value, Appointment.starts_at >= year_start,
    ).order_by(Appointment.starts_at).limit(1))
    return first.astimezone(tz).strftime("%d/%m/%Y") if first else ""


def form_values(db: Session, clinic: Clinic, patient: Patient) -> dict[str, str]:
    """Valores de los campos del formulario (nombre del campo en el PDF → texto)."""
    tz = ZoneInfo(clinic.timezone)
    today = datetime.now(tz)
    values = {
        "Día": f"{today.day:02d}", "Mes": f"{today.month:02d}", "Año": str(today.year),
        # 1. Beneficiario
        "Cedula1": _digits(patient.document_number),
        "PRIMER NOMBRE": _upper(patient.first_name), "PRIMER APELLIDO": _upper(patient.last_name),
        "DEPARTAMENTO": patient.address_department or "", "LOCALIDAD": patient.address_locality or "",
        "CALLE": patient.address_street or "", "NUMERO": patient.address_number or "",
        "APTO": patient.address_apartment or "", "SOLAR": patient.address_solar or "",
        "MANZANA": patient.address_block or "", "TELEFONO": patient.phone or "",
        # 2. Instituto (la clínica)
        "N DE PROVEEDOR": clinic.bps_provider_number or "", "N DE EMPRESA": clinic.bps_company_number or "",
        "NOMBRE RAZON SOCIAL": _upper(clinic.name), "TELEFONO PROVEEDOR": clinic.phone or "",
        "EMAIL PROVEEDOR": clinic.email or "", "DOMICILIO PROVEEDOR": clinic.address_street or "",
        "NUMERO PROVEEDOR": clinic.address_number or "", "LOCALIDAD PROVEEDOR": clinic.address_locality or "",
        "DEPARTAMENTO PROVEEDOR": clinic.address_department or "",
        "ANEXO PROVEEDOR": clinic.address_annex or "",
        # 5. Fecha de comienzo en el año y presupuesto mensual
        "FECHA INICIO AÑO ACTUALRow1": _first_session_this_year(db, clinic.id, patient.id, tz),
        "fill_85": clinic.monthly_budget or "",
    }
    # 3. Actividades, técnicos y horarios
    for i, row in enumerate(_activities(db, clinic.id, patient, tz), start=1):
        values[f"ACTIVIDADRow{i}"] = row["activity"]
        values[f"NOMBRE Y APELLIDO TECNICORow{i}"] = row["name"]
        for weekday, (start, end) in row["days"].items():
            day = WEEKDAY_FIELDS[weekday]
            values[f"TÉCNICO {day} desde {i}"] = start
            # Error del formulario del BPS: en la fila 4, "Sábado hasta" tiene el mismo nombre que
            # "Viernes hasta" (llenar uno llena el otro). Ese dato se deja para completar a mano.
            if not (i == 4 and weekday == 5):
                values[f"TÉCNICO {day} hasta {i}"] = end
    # 8. Responsable legal: el contacto principal (o el primero cargado)
    guardian = db.scalar(select(PatientGuardian).where(
        PatientGuardian.clinic_id == clinic.id, PatientGuardian.patient_id == patient.id,
    ).order_by(PatientGuardian.is_primary.desc(), PatientGuardian.created_at).limit(1))
    if guardian:
        values["Cedula2"] = _digits(guardian.document_number)
        values["PRIMER NOMBRERow1_2"] = _upper(guardian.first_name)
        values["PRIMER APELLIDORow1_2"] = _upper(guardian.last_name)
    return {k: v for k, v in values.items() if v}


def _set_transport(writer: PdfWriter, included: bool | None) -> None:
    """Punto 4: casillero SI (primer botón) o NO (segundo) del grupo "Group14"."""
    if included is None:
        return
    widgets = []
    for annot in writer.pages[0].get("/Annots") or []:
        a = annot.get_object()
        parent = a.get("/Parent")
        if parent is not None and parent.get_object().get("/T") == "Group14":
            widgets.append(a)
    widgets.sort(key=lambda a: float(a["/Rect"][0]))  # SI está a la izquierda de NO
    if len(widgets) != 2:
        return
    chosen = widgets[0] if included else widgets[1]
    on = next(k for k in chosen["/AP"]["/N"].keys() if k != "/Off")
    chosen["/Parent"].get_object()[NameObject("/V")] = NameObject(on)
    for a in widgets:
        a[NameObject("/AS")] = NameObject(on) if a is chosen else NameObject("/Off")


def fill_pdf(values: dict[str, str], transport_included: bool | None) -> bytes:
    writer = PdfWriter(clone_from=PdfReader(TEMPLATE))
    # Se dibuja cada campo ya completado (con tildes y "ñ") y se le indica al visor que no lo
    # vuelva a dibujar: algunos visores pierden las tildes al hacerlo. Los campos siguen
    # siendo editables en Vista Previa o Acrobat.
    writer.update_page_form_field_values(writer.pages[0], values, auto_regenerate=True)
    writer._root_object["/AcroForm"][NameObject("/NeedAppearances")] = BooleanObject(False)
    _set_transport(writer, transport_included)
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


@router.get("/{patient_id}/ayex-form")
def ayex_form(
    patient_id: uuid.UUID,
    request: Request,
    user: CurrentUser = Depends(require_staff_or_titular),
    db: Session = Depends(get_db),
):
    patient = get_visible_patient(db, user, patient_id)
    if patient.affiliation != AffiliationType.ayex.value:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            detail="El formulario de AYEX es solo para pacientes con afiliación AYEX.")
    clinic = db.get(Clinic, user.clinic_id)
    values = form_values(db, clinic, patient)
    pdf = fill_pdf(values, clinic.transport_included)
    audit.record(db, clinic_id=user.clinic_id, actor_id=user.id, action="patient.ayex_form",
                 entity_type="patient", entity_id=patient.id, patient_id=patient.id,
                 details={"fields": len(values)}, request=request)
    db.commit()
    # Nombre del archivo sin tildes: "Núñez, María José" → solicitud-ayex-nunez-maria-jose.pdf
    plain = unicodedata.normalize("NFKD", f"{patient.last_name}-{patient.first_name}")
    name = re.sub(r"[^A-Za-z0-9]+", "-", plain.encode("ascii", "ignore").decode()).strip("-").lower() or "paciente"
    return Response(pdf, media_type="application/pdf", headers={
        "Content-Disposition": f'attachment; filename="solicitud-ayex-{name}.pdf"',
    })
