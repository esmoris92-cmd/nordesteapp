"""Exportar el "Cronograma de Actividades de Ayudas Extraordinarias" del BPS (.xlsx).

Se completa la planilla oficial del BPS (``app/forms/cronograma_bps.xlsx``, vacía) con:

* PROV: los datos de la clínica como proveedor (los mismos del formulario AYEX).
* TÉCNICOS: los profesionales que atienden a esos pacientes, con los datos que cada uno
  completa en "Mi cuenta" (nombres, apellidos, formación y quién expidió el título).
* USUARIOS: los pacientes AYEX activos (en la planilla, "usuarios" son los pacientes).
  Administración exporta los de toda la clínica; Recepción, los de su sucursal (son los
  únicos AYEX que puede ver).
* LUN a SAB: los horarios según los turnos de la Agenda (un renglón por paciente, profesional
  y horario). Ver ``bps.weekly_appointments``: 4 semanas antes y después de la actual, sin
  cancelados ni reprogramados. La actividad sale de la especialidad del profesional
  (Administración la asocia en Especialidades).

Lo que falta se deja en blanco para completar a mano. Las listas desplegables y los controles
de C.I. de la planilla quedan intactos. Cada descarga queda en la auditoría.
"""

import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import audit
from app.bps import ACTIVITIES, DEGREE_ISSUERS, TRAININGS, activity_cell, activity_for, weekly_appointments
from app.db import get_db
from app.deps import CurrentUser, get_current_user, require_staff_or_titular
from app.features import require_feature
from app.models import (
    AffiliationType, Clinic, Patient, PatientAccess, PatientStatus,
    Role, Specialty, User,
)
from app.permissions import visible_patients
from app.xlsx_template import XlsxTemplate

router = APIRouter(prefix="/api/bps-schedule", tags=["cronograma BPS"])

TEMPLATE = Path(__file__).resolve().parent.parent / "forms" / "cronograma_bps.xlsx"
DAY_SHEETS = ["LUN", "MAR", "MIE", "JUE", "VIE", "SAB"]  # el BPS no usa domingo
FIRST_DAY_ROW = 5


def _document(value: str | None):
    """La C.I. solo con números y como número (así la controla la planilla). Un documento
    extranjero con letras se deja como texto."""
    if not value:
        return None
    digits = re.sub(r"\D", "", value)
    if digits and re.fullmatch(r"[\d.\-\s]+", value):
        return int(digits)
    return value


def _address(p: Patient) -> str:
    street = " ".join(x for x in [p.address_street, p.address_number] if x)
    if p.address_apartment:
        street += f" apto {p.address_apartment}"
    parts = [street.strip(), p.address_locality, p.address_department]
    return ", ".join(x for x in parts if x)


def _tech_names(u: User) -> tuple[str, str, str, str]:
    """(primer nombre, segundo nombre, primer apellido, segundo apellido). Si la persona
    todavía no los completó en "Mi cuenta", se separa el nombre completo como se pueda."""
    if u.first_name or u.last_name:
        return u.first_name or "", u.middle_name or "", u.last_name or "", u.second_last_name or ""
    words = u.full_name.split()
    if len(words) == 1:
        return words[0], "", "", ""
    return words[0], "", words[1], " ".join(words[2:])


def build_schedule(db: Session, user: CurrentUser) -> tuple[bytes, dict]:
    clinic = db.get(Clinic, user.clinic_id)
    tz = ZoneInfo(clinic.timezone)
    today = datetime.now(tz)
    book = XlsxTemplate(TEMPLATE.read_bytes())

    # PROV: datos del proveedor (la clínica)
    provider = clinic.bps_provider_number or ""
    book.set("PROV", "C2", int(provider) if provider.isdigit() else provider or None)
    book.set("PROV", "E2", clinic.name.upper())
    book.set("PROV", "C3", clinic.phone)
    book.set("PROV", "E3", " ".join(x for x in [clinic.address_street, clinic.address_number] if x) or None)
    book.set("PROV", "G3", clinic.address_department)
    book.set("PROV", "C4", today.strftime("%d/%m/%Y"))
    book.set("PROV", "E4", clinic.email)
    book.set("PROV", "G4", clinic.address_locality)
    book.set("PROV", "G8", today.year)

    # USUARIOS: pacientes AYEX activos que el usuario puede ver
    patients = db.scalars(visible_patients(user).where(
        Patient.affiliation == AffiliationType.ayex.value, Patient.status == PatientStatus.active.value,
    ).order_by(Patient.last_name, Patient.first_name)).all()
    by_id = {p.id: p for p in patients}
    for row, p in enumerate(patients, start=2):
        book.set_row("USUARIOS", row, "A", [
            _document(p.document_number), p.last_name, p.second_last_name, p.first_name, p.middle_name,
            p.phone, _address(p) or None,
        ])

    # Turnos de la Agenda de esos pacientes (el horario semanal)
    appts = weekly_appointments(db, user.clinic_id, by_id, tz)

    # TÉCNICOS: quienes atienden a esos pacientes (acceso vigente) o tienen turnos con ellos
    prof_ids = set(db.scalars(select(PatientAccess.user_id).where(
        PatientAccess.clinic_id == user.clinic_id, PatientAccess.patient_id.in_(by_id),
        PatientAccess.revoked_at.is_(None),
    )).all()) if by_id else set()
    prof_ids |= {a.professional_id for a in appts}
    profs = db.scalars(select(User).where(
        User.clinic_id == user.clinic_id, User.id.in_(prof_ids), User.role == Role.professional.value,
        User.archived_at.is_(None),
    )).all() if prof_ids else []
    profs = sorted(profs, key=lambda u: (_tech_names(u)[2].lower(), _tech_names(u)[0].lower()))
    specialties = {s.id: s for s in db.scalars(select(Specialty).where(Specialty.clinic_id == user.clinic_id))}
    tech_label: dict = {}
    activity: dict = {}
    for row, u in enumerate(profs, start=2):
        first, middle, last, second_last = _tech_names(u)
        book.set_row("TÉCNICOS", row, "A", [
            _document(u.document_number), last or None, second_last or None, first or None, middle or None,
            u.bps_training, u.degree_issuer,
        ])
        # Igual que la columna I de TÉCNICOS (la lista desplegable de las hojas de cada día)
        tech_label[u.id] = f"{first} {last} - {u.bps_training or ''}"
        activity[u.id] = activity_for(specialties.get(u.specialty_id))

    # LUN a SAB: un renglón por paciente, profesional y horario
    slots: dict[int, set] = {d: set() for d in range(6)}
    for a in appts:
        start = a.starts_at.astimezone(tz)
        if a.professional_id not in tech_label:
            continue
        slots[start.weekday()].add((start.strftime("%H:%M"), a.ends_at.astimezone(tz).strftime("%H:%M"),
                                    a.patient_id, a.professional_id))
    rows_written = 0
    for weekday, sheet in enumerate(DAY_SHEETS):
        ordered = sorted(slots[weekday], key=lambda s: (
            s[0], by_id[s[2]].last_name.lower(), by_id[s[2]].first_name.lower()))
        for i, (start, end, patient_id, prof_id) in enumerate(ordered, start=1):
            p = by_id[patient_id]
            doc = _document(p.document_number)
            act = activity[prof_id]
            book.set_row(sheet, FIRST_DAY_ROW + i - 1, "A", [
                i, f"{p.last_name} {p.first_name} - {doc if doc is not None else ''}",
                f"{start} a {end}", activity_cell(act) if act else None, tech_label[prof_id],
            ])
        rows_written += len(ordered)
    return book.save(), {"patients": len(patients), "technicians": len(profs), "rows": rows_written}


@router.get("", dependencies=[Depends(require_feature("bps"))])
def bps_schedule(
    request: Request,
    user: CurrentUser = Depends(require_staff_or_titular),
    db: Session = Depends(get_db),
):
    content, counts = build_schedule(db, user)
    audit.record(db, clinic_id=user.clinic_id, actor_id=user.id, action="patient.bps_schedule",
                 entity_type="patient", details={"count": counts["patients"]}, request=request)
    db.commit()
    today = datetime.now(ZoneInfo(db.get(Clinic, user.clinic_id).timezone))
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="cronograma-bps-{today:%Y-%m-%d}.xlsx"',
                 "X-Content-Type-Options": "nosniff"},
    )


@router.get("/lists")
def bps_lists(_: CurrentUser = Depends(get_current_user)):
    """Opciones de las listas del BPS (formación, quién expidió el título y actividades)."""
    return {"trainings": TRAININGS, "degree_issuers": DEGREE_ISSUERS, "activities": ACTIVITIES}
