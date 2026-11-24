"""Funciones de Nordeste que el dueño del sistema puede habilitar o deshabilitar por clínica.

Lo básico (pacientes, agenda, usuarios, auditoría, historia clínica, informes) está siempre
activo. Las funciones de esta lista se pueden apagar para una clínica que no las contrató:

* En la base se guarda la lista de funciones **deshabilitadas** (``clinics.disabled_features``).
  Así las clínicas existentes y las nuevas empiezan con todo activado, y una función que se
  agregue a Nordeste en el futuro también empieza activada.
* Deshabilitar **no borra nada**: la función desaparece del menú y la API la rechaza, pero sus
  datos quedan guardados. Al volver a habilitarla, todo sigue como estaba.
"""

from collections.abc import Callable
from dataclasses import dataclass

from fastapi import Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import CurrentUser, get_current_user
from app.models import Clinic


@dataclass(frozen=True)
class Feature:
    key: str
    label: str
    description: str


# El orden es el que se muestra en la pantalla del dueño.
FEATURES: tuple[Feature, ...] = (
    Feature("caja", "Caja", "Caja diaria por sucursal: apertura, entradas y salidas, cierre y balances."),
    Feature("bps", "BPS y AYEX",
            "Pagos BPS, formulario AYEX del paciente y Cronograma BPS (exportar e importar). "
            "El tipo de afiliación AYEX y sus vencimientos siguen estando."),
    Feature("avisos", "Avisos", "Avisos de Recepción y Administración a los profesionales."),
    Feature("informe_mensual", "Informe mensual", "Resumen mensual de sesiones por profesional y su Excel."),
    Feature("objetivos", "Objetivos", "Pestaña Objetivos (plan de tratamiento) en la ficha del paciente."),
    Feature("archivos", "Archivos", "Pestaña Archivos de la ficha: subir y ver PDFs e imágenes del paciente."),
)
FEATURE_KEYS: tuple[str, ...] = tuple(f.key for f in FEATURES)

FEATURE_DISABLED = ("Esta función no está habilitada para tu clínica. Si la necesitás, "
                    "comunicate con el responsable de Nordeste.")


def enabled_features(disabled: list[str] | None) -> list[str]:
    """Las funciones activas, a partir de la lista de deshabilitadas guardada en la clínica."""
    off = set(disabled or [])
    return [key for key in FEATURE_KEYS if key not in off]


def require_feature(key: str) -> Callable[..., None]:
    """Dependencia para los routers de una función: 403 si la clínica la tiene deshabilitada."""
    if key not in FEATURE_KEYS:
        raise ValueError(f"Función desconocida: {key}")

    def dependency(user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)) -> None:
        disabled = db.scalar(select(Clinic.disabled_features).where(Clinic.id == user.clinic_id)) or []
        if key in disabled:
            raise HTTPException(status.HTTP_403_FORBIDDEN, detail=FEATURE_DISABLED)

    return dependency
