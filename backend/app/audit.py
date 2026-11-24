"""Registro de auditoría.

Regla: solo metadatos (quién, qué acción, sobre qué entidad, cuándo). Nunca
se copian textos clínicos, contraseñas ni tokens en ``details``.
"""

import uuid
from typing import Any

from fastapi import Request
from sqlalchemy.orm import Session

from app.models import AuditEvent

# Claves permitidas en "details". Cualquier otra se descarta para evitar
# copiar por error contenido clínico o datos personales en la auditoría.
_ALLOWED_DETAIL_KEYS = {
    "fields", "level", "status", "from_status", "to_status", "target_user_id",
    "role", "kind", "supersedes_id", "new_appointment_id", "reason_given", "count", "past",
    "professional_id", "is_active", "feature",
}


def record(
    db: Session,
    *,
    clinic_id: uuid.UUID,
    actor_id: uuid.UUID | None,
    action: str,
    entity_type: str | None = None,
    entity_id: uuid.UUID | str | None = None,
    patient_id: uuid.UUID | None = None,
    details: dict[str, Any] | None = None,
    request: Request | None = None,
) -> None:
    safe_details = {k: v for k, v in (details or {}).items() if k in _ALLOWED_DETAIL_KEYS}
    db.add(
        AuditEvent(
            clinic_id=clinic_id,
            actor_id=actor_id,
            action=action,
            entity_type=entity_type,
            entity_id=str(entity_id) if entity_id is not None else None,
            patient_id=patient_id,
            details=safe_details,
            ip=(request.client.host if request and request.client else None),
        )
    )
