"""Consulta del registro de auditoría (solo administración de la clínica).

Filtros: persona, acción, paciente y rango de fechas (días de la clínica). Los eventos se
devuelven de a páginas, del más nuevo al más viejo: para "Cargar más" se pide con
``before_id`` = el id del último evento recibido.
"""

import uuid
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import CurrentUser, require_admin_or_titular
from app.models import AuditEvent, Clinic, Patient, User
from app.schemas import AuditOut

router = APIRouter(prefix="/api/audit", tags=["auditoría"])


@router.get("", response_model=list[AuditOut])
def list_audit(
    patient_id: uuid.UUID | None = None,
    actor_id: uuid.UUID | None = None,
    action: str | None = Query(default=None, max_length=60),
    date_from: date | None = None,
    date_to: date | None = None,
    before_id: int | None = Query(default=None, ge=1),
    limit: int = Query(default=200, ge=1, le=1000),
    user: CurrentUser = Depends(require_admin_or_titular),
    db: Session = Depends(get_db),
):
    if date_from and date_to and date_from > date_to:
        raise HTTPException(422, detail="La fecha \"desde\" no puede ser posterior a la fecha \"hasta\".")
    query = (
        select(AuditEvent, User.full_name, Patient.first_name, Patient.last_name)
        .outerjoin(User, (User.id == AuditEvent.actor_id) & (User.clinic_id == AuditEvent.clinic_id))
        .outerjoin(Patient, (Patient.id == AuditEvent.patient_id) & (Patient.clinic_id == AuditEvent.clinic_id))
        .where(AuditEvent.clinic_id == user.clinic_id)
    )
    if patient_id:
        query = query.where(AuditEvent.patient_id == patient_id)
    if actor_id:
        query = query.where(AuditEvent.actor_id == actor_id)
    if action:
        query = query.where(AuditEvent.action == action)
    if date_from or date_to:
        tz = ZoneInfo(db.get(Clinic, user.clinic_id).timezone)
        if date_from:
            query = query.where(AuditEvent.created_at >= datetime.combine(date_from, time(0), tzinfo=tz))
        if date_to:
            query = query.where(AuditEvent.created_at
                                < datetime.combine(date_to + timedelta(days=1), time(0), tzinfo=tz))
    if before_id:
        query = query.where(AuditEvent.id < before_id)
    rows = db.execute(query.order_by(AuditEvent.id.desc()).limit(limit)).all()
    return [
        AuditOut(
            id=e.id, created_at=e.created_at, action=e.action,
            actor_name=name or ("Soporte de Nordeste" if e.action.startswith("system.") else None),
            entity_type=e.entity_type, entity_id=e.entity_id, patient_id=e.patient_id,
            patient_name=f"{last}, {first}" if last else None, details=e.details,
        )
        for e, name, first, last in rows
    ]


@router.get("/people")
def audit_people(user: CurrentUser = Depends(require_admin_or_titular), db: Session = Depends(get_db)):
    """Todas las cuentas de la clínica (también desactivadas o eliminadas), para el filtro."""
    rows = db.execute(select(User.id, User.full_name, User.archived_at).where(User.clinic_id == user.clinic_id)
                      .order_by(User.full_name)).all()
    return [{"id": i, "full_name": n + (" (eliminada)" if archived else "")} for i, n, archived in rows]
