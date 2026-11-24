"""Aviso de vencimiento del AYEX.

* Amarillo: vence dentro de los próximos 3 meses.
* Rojo: vence dentro de los próximos 2 meses, vence hoy o ya venció.

Los meses son de calendario: hoy 15/03 → amarillo hasta el 15/06, rojo hasta el 15/05.
"""

import calendar
from datetime import date, timedelta
from typing import Literal

AYEX_WARN_MONTHS = 3  # desde cuándo aparece el aviso (amarillo)
AYEX_RED_MONTHS = 2  # desde cuándo el aviso pasa a rojo

AyexLevel = Literal["red", "yellow"]


def add_months(d: date, months: int) -> date:
    """Suma meses de calendario; si el día no existe (31/04) usa el último día del mes."""
    y, m = divmod(d.month - 1 + months, 12)
    year, month = d.year + y, m + 1
    return d.replace(year=year, month=month, day=min(d.day, calendar.monthrange(year, month)[1]))


def ayex_alert_before(today: date) -> date:
    """Los AYEX que vencen ANTES de esta fecha tienen aviso (incluye el día justo a 3 meses)."""
    return add_months(today, AYEX_WARN_MONTHS) + timedelta(days=1)


def ayex_level(expires_on: date, today: date) -> AyexLevel:
    """Color del aviso para un AYEX que ya está dentro de los 3 meses."""
    return "red" if expires_on <= add_months(today, AYEX_RED_MONTHS) else "yellow"
