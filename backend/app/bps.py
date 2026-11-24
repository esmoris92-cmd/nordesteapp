"""Listas del BPS que usa el Cronograma de Ayudas Extraordinarias (tal como figuran en la
planilla oficial, para que las listas desplegables de Excel las reconozcan)."""

import unicodedata
import uuid
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Appointment, AppointmentStatus

# Formación académica del técnico (hoja TÉCNICOS, columna F).
TRAININGS = [
    "FISIOTERAPIA", "FONOAUDIOLOGIA", "HIDROTERAPIA", "MAESTRA", "MAESTRA ESPECIALIZADA",
    "PSICOLOGIA", "PSICOMOTRICIDAD", "PSICOPEDAGOGÍA", "TERAPIA OCUPACIONAL", "TALLERISTA",
    "LICENCIATURA", "TITULO TECNICO", "OTRA FORMACION",
]

# Quién expidió el título (hoja TÉCNICOS, columna G).
DEGREE_ISSUERS = [
    "ANEP", "CEDIIAP", "CETP", "UDELAR", "Universidad Catolica", "Univ. de la Empresa", "UTU", "Otros",
]

# Actividades (hojas de cada día, columna "TIPO"). En la planilla llevan un espacio adelante.
ACTIVITIES = [
    "FISIOTERAPIA", "FONOAUDIOLOGIA", "HIDROTERAPIA", "MAESTRA ESPECIALIZADA", "PSICOLOGÍA",
    "PSICOMOTRICIDAD", "PSICOPEDAGOGIA", "TALLER DE HABILITACIÓN OCUPACIONAL", "TERAPIA OCUPACIONAL",
    "ARTESANIA, MANUALIDADES Y LABORES", "BRAILLE", "CANTO / CORO", "CARPINTERIA", "CERAMICA",
    "CESTERIA", "COSTURA", "DANZA", "ECONOMIA DOMESTICA", "EDUCACION FISICA / DEPORTES",
    "ENSEÑANZA CURRICULAR (CENTROS EDUCATIVOS)", "EXPRESION CORPORAL", "FORMACION ARTISTICA/CULTURAL",
    "GASTRONOMIA", "HABILIDADES COTIDIANAS", "HOGAR", "HUERTA", "INFORMATICA", "JARDINERIA",
    "JUEGOS / RECREACION", "MAESTRA", "MANUALIDADES", "MURGA", "MUSICA", "MUSICOTERAPIA", "PANADERIA",
    "PELUQUERIA", "PLASTICA", "PRODUCCION", "TAPIZ", "TEATRO",
    "TECNOLOGÍAS PARA LA ACCESIBILIDAD Y LA INCLUSIÓN", "TELAR", "OTROS…",
]


def activity_cell(name: str) -> str:
    """Como figura en la lista de la planilla: con un espacio adelante (" PSICOLOGÍA")."""
    return f" {name}"


def _plain(text: str) -> str:
    """Sin tildes y en mayúsculas, para comparar nombres: "Psicología" → "PSICOLOGIA"."""
    text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode()
    return " ".join(text.upper().split())


_ACTIVITY_BY_PLAIN = {_plain(a): a for a in ACTIVITIES}


def activity_by_name(name: str) -> str | None:
    """La actividad de la lista del BPS con el mismo nombre (ej. "Psicología" → "PSICOLOGÍA")."""
    return _ACTIVITY_BY_PLAIN.get(_plain(name))


def activity_for(specialty) -> str | None:
    """La actividad que Administración asoció a la especialidad; si no hay, la de la lista
    del BPS con el mismo nombre; si tampoco, ninguna (queda en blanco en la planilla)."""
    if specialty is None:
        return None
    return specialty.bps_activity or activity_by_name(specialty.name)


WEEKS_BACK = 4  # semanas anteriores a la actual que se miran en la Agenda
WEEKS_AHEAD = 4  # semanas siguientes a la actual


def weekly_appointments(db: Session, clinic_id: uuid.UUID, patient_ids, tz: ZoneInfo) -> list[Appointment]:
    """Turnos de la Agenda que forman el horario semanal de esos pacientes (para el BPS).

    Se miran las 4 semanas anteriores a la actual, la actual y las 4 siguientes, sin contar
    los cancelados ni los reprogramados. Solo de lunes a sábado (el BPS no usa domingo). Si un
    paciente se atiende con el mismo profesional el mismo día de la semana en varias semanas,
    vale la fecha más reciente o próxima (así un cambio de horario no aparece repetido).
    """
    patient_ids = list(patient_ids)
    if not patient_ids:
        return []
    today = datetime.now(tz).date()
    monday = today - timedelta(days=today.weekday())
    start = datetime.combine(monday - timedelta(weeks=WEEKS_BACK), time(0), tzinfo=tz)
    end = datetime.combine(monday + timedelta(weeks=WEEKS_AHEAD + 1), time(0), tzinfo=tz)
    appts = db.scalars(select(Appointment).where(
        Appointment.clinic_id == clinic_id, Appointment.patient_id.in_(patient_ids),
        Appointment.status.in_([AppointmentStatus.scheduled.value, AppointmentStatus.completed.value,
                                AppointmentStatus.no_show.value]),
        Appointment.starts_at >= start, Appointment.starts_at < end,
    ).order_by(Appointment.starts_at)).all()
    latest: dict[tuple, date] = {}
    for a in appts:
        day = a.starts_at.astimezone(tz)
        latest[(a.patient_id, a.professional_id, day.weekday())] = day.date()
    return [a for a in appts
            if a.starts_at.astimezone(tz).weekday() <= 5
            and latest[(a.patient_id, a.professional_id, a.starts_at.astimezone(tz).weekday())]
            == a.starts_at.astimezone(tz).date()]
