"""Fecha de hoy según la zona horaria de la clínica (no la del servidor).

En un servidor en hora UTC, entre las 21:00 y la medianoche de Montevideo el servidor ya está
en "mañana": las fechas de sesiones y avances se comparan con el día de la clínica.
"""

import uuid
from datetime import date, datetime
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models import Clinic


def clinic_today(db: Session, clinic_id: uuid.UUID) -> date:
    return datetime.now(ZoneInfo(db.get(Clinic, clinic_id).timezone)).date()


def check_not_future(db: Session, clinic_id: uuid.UUID, value: date | None) -> None:
    """422 si la fecha es posterior a hoy en la clínica."""
    if value is not None and value > clinic_today(db, clinic_id):
        raise HTTPException(422, detail="La fecha no puede estar en el futuro.")
