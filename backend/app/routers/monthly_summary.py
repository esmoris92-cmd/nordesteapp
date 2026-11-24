"""Informe mensual de sesiones por profesional y tipo de afiliación.

* Recepción ve su sucursal; Administración, la sucursal activa o toda la clínica; cada
  profesional, solo lo suyo en todas sus sucursales (ver ``branch_scope``).
* Las filas se separan por sucursal (donde fue el turno), profesional y afiliación.
* Cuenta los turnos que EMPIEZAN en el mes (hora de la clínica) según su estado: realizados,
  ausentes, cancelados y todavía programados. Los "reprogramados" no se cuentan: ya fueron
  reemplazados por el turno nuevo, que es el que se cuenta.
* "Pacientes atendidos" = pacientes distintos con al menos un turno realizado.
* La afiliación es la que el paciente tiene HOY en su ficha.
* Solo números: no incluye nombres de pacientes ni contenido clínico.
"""

import re
from datetime import date, datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import audit
from app.branch_scope import report_scope
from app.branches import AFFILIATION_LABELS, branch_names
from app.db import get_db
from app.deps import CurrentUser, get_current_user
from app.features import require_feature
from app.models import AffiliationType, Appointment, AppointmentStatus, Clinic, Patient, User
from app.xlsx import build_xlsx

router = APIRouter(prefix="/api/monthly-summary", tags=["informe mensual"],
                   dependencies=[Depends(require_feature("informe_mensual"))])

_MONTH_RE = re.compile(r"^(\d{4})-(\d{2})$")
_AFFILIATION_ORDER = [a.value for a in AffiliationType]
_AFFILIATION_LABELS = AFFILIATION_LABELS
_COUNTED = {
    AppointmentStatus.completed.value: "completed",
    AppointmentStatus.no_show.value: "no_show",
    AppointmentStatus.cancelled.value: "cancelled",
    AppointmentStatus.scheduled.value: "scheduled",
}


class SummaryRow(BaseModel):
    branch_id: str
    branch_name: str
    professional_id: str
    professional_name: str
    affiliation: AffiliationType
    completed: int = 0
    no_show: int = 0
    cancelled: int = 0
    scheduled: int = 0
    patients_seen: int = 0


class SummaryTotals(BaseModel):
    completed: int = 0
    no_show: int = 0
    cancelled: int = 0
    scheduled: int = 0
    patients_seen: int = 0


class BranchTotals(SummaryTotals):
    branch_id: str
    branch_name: str


class MonthlySummaryOut(BaseModel):
    month: str
    rows: list[SummaryRow]
    by_affiliation: dict[str, SummaryTotals]
    by_branch: list[BranchTotals]
    total: SummaryTotals
    only_own: bool
    scope: str  # "own", "branch" o "clinic"
    branch_name: str | None = None  # la sucursal del informe (None = todas)


def _month_range(month: str, tz: ZoneInfo) -> tuple[datetime, datetime]:
    match = _MONTH_RE.match(month or "")
    if not match or not 1 <= int(match.group(2)) <= 12 or not 2000 <= int(match.group(1)) <= 2100:
        raise HTTPException(422, detail="El mes debe tener el formato AAAA-MM.")
    year, mon = int(match.group(1)), int(match.group(2))
    start = datetime(year, mon, 1, tzinfo=tz)
    end = datetime(year + (mon == 12), 1 if mon == 12 else mon + 1, 1, tzinfo=tz)
    return start, end


def _build(db: Session, user: CurrentUser, month: str, branch: str | None) -> MonthlySummaryOut:
    if not (user.is_admin or user.is_reception or user.is_professional):
        raise HTTPException(403, detail="Tu rol no tiene permiso para ver este informe.")
    scope = report_scope(db, user, branch)
    names = branch_names(db, user.clinic_id)
    tz = ZoneInfo(db.get(Clinic, user.clinic_id).timezone)
    start, end = _month_range(month, tz)
    query = (
        select(Appointment.branch_id, Appointment.professional_id, User.full_name, Patient.affiliation,
               Appointment.status, Appointment.patient_id)
        .join(Patient, (Patient.id == Appointment.patient_id) & (Patient.clinic_id == Appointment.clinic_id))
        .join(User, (User.id == Appointment.professional_id) & (User.clinic_id == Appointment.clinic_id))
        .where(Appointment.clinic_id == user.clinic_id,
               Appointment.starts_at >= start, Appointment.starts_at < end,
               Appointment.status.in_(list(_COUNTED)))
    )
    if user.is_professional:  # cada profesional ve solo lo suyo
        query = query.where(Appointment.professional_id == user.id)
    if scope.branch_id:
        query = query.where(Appointment.branch_id == scope.branch_id)

    rows: dict[tuple, SummaryRow] = {}
    seen: dict[tuple, set] = {}
    by_aff = {a: SummaryTotals() for a in _AFFILIATION_ORDER}
    seen_aff: dict[str, set] = {a: set() for a in _AFFILIATION_ORDER}
    by_branch: dict[str, BranchTotals] = {}
    seen_branch: dict[str, set] = {}
    total = SummaryTotals()
    seen_total: set = set()
    for branch_id, prof_id, prof_name, affiliation, status, patient_id in db.execute(query).all():
        bid = str(branch_id)
        bname = names.get(branch_id, "")
        key = (bid, str(prof_id), affiliation)
        row = rows.setdefault(key, SummaryRow(branch_id=bid, branch_name=bname, professional_id=str(prof_id),
                                              professional_name=prof_name, affiliation=affiliation))
        btotal = by_branch.setdefault(bid, BranchTotals(branch_id=bid, branch_name=bname))
        field = _COUNTED[status]
        for target in (row, by_aff[affiliation], btotal, total):
            setattr(target, field, getattr(target, field) + 1)
        if status == AppointmentStatus.completed.value:
            seen.setdefault(key, set()).add(patient_id)
            seen_aff[affiliation].add(patient_id)
            seen_branch.setdefault(bid, set()).add(patient_id)
            seen_total.add(patient_id)
    for key, row in rows.items():
        row.patients_seen = len(seen.get(key, ()))
    for aff, totals in by_aff.items():
        totals.patients_seen = len(seen_aff[aff])
    for bid, totals in by_branch.items():
        totals.patients_seen = len(seen_branch.get(bid, ()))
    total.patients_seen = len(seen_total)
    ordered = sorted(rows.values(), key=lambda r: (r.branch_name.lower(), r.professional_name.lower(),
                                                   _AFFILIATION_ORDER.index(r.affiliation.value)))
    return MonthlySummaryOut(month=month, rows=ordered, by_affiliation=by_aff,
                             by_branch=sorted(by_branch.values(), key=lambda b: b.branch_name.lower()),
                             total=total, only_own=user.is_professional, scope=scope.scope,
                             branch_name=scope.branch_name)


def _file_suffix(summary: MonthlySummaryOut) -> str:
    """"-central", "-todas" o "" (profesional) para el nombre del archivo, sin caracteres raros."""
    if summary.scope == "own":
        return ""
    if summary.branch_name is None:
        return "-todas"
    slug = "".join(c if c.isalnum() else "-" for c in summary.branch_name.lower())
    slug = slug.encode("ascii", "ignore").decode().strip("-")
    return f"-{slug}" if slug else ""


def _current_month() -> str:
    return f"{date.today():%Y-%m}"


@router.get("", response_model=MonthlySummaryOut)
def monthly_summary(
    month: str | None = Query(default=None, max_length=7),
    branch: str | None = Query(default=None, max_length=40),
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return _build(db, user, month or _current_month(), branch)


@router.get("/export")
def export_monthly_summary(
    request: Request,
    month: str | None = Query(default=None, max_length=7),
    branch: str | None = Query(default=None, max_length=40),
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    month = month or _current_month()
    summary = _build(db, user, month, branch)
    headers = ["Sucursal", "Profesional", "Tipo de afiliación", "Realizadas", "Ausentes", "Canceladas",
               "Programadas", "Pacientes atendidos"]
    rows = [[r.branch_name, r.professional_name, _AFFILIATION_LABELS[r.affiliation.value], r.completed,
             r.no_show, r.cancelled, r.scheduled, r.patients_seen] for r in summary.rows]
    rows.append([])
    if len(summary.by_branch) > 1:
        for b in summary.by_branch:
            rows.append([f"Total {b.branch_name}", None, None, b.completed, b.no_show, b.cancelled,
                         b.scheduled, b.patients_seen])
    for aff in _AFFILIATION_ORDER:
        t = summary.by_affiliation[aff]
        rows.append([f"Total {_AFFILIATION_LABELS[aff]}", None, None, t.completed, t.no_show, t.cancelled,
                     t.scheduled, t.patients_seen])
    t = summary.total
    rows.append(["TOTAL", None, None, t.completed, t.no_show, t.cancelled, t.scheduled, t.patients_seen])
    content = build_xlsx(f"Informe {month}", headers, rows, [18, 30, 20, 12, 12, 12, 13, 20])
    audit.record(db, clinic_id=user.clinic_id, actor_id=user.id, action="summary.export",
                 entity_type="clinic", details={"count": len(summary.rows)}, request=request)
    db.commit()
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="lumen-informe-{month}{_file_suffix(summary)}.xlsx"',
                 "X-Content-Type-Options": "nosniff"},
    )
