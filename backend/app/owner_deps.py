"""Sesión del dueño del sistema (separada de las sesiones de las clínicas).

* Cookie propia (``lumen_owner_session``), ``HttpOnly``, ``SameSite=Strict`` y solo para
  ``/api/owner``: una sesión de clínica nunca sirve para entrar acá, ni al revés.
* Token CSRF propio, igual que en las clínicas.
* Vence antes por inactividad (30 minutos) porque es la cuenta con más poder.
* Hasta cambiar la contraseña temporal y configurar el código del celular, solo puede hacer
  eso (``require_ready_owner`` bloquea todo lo demás).
"""

import uuid
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import CSRF_HEADER, SAFE_METHODS, utcnow
from app.models import OwnerAuditEvent, OwnerSession, SystemOwner
from app.security import hash_token, tokens_equal

OWNER_COOKIE = "lumen_owner_session"
OWNER_COOKIE_PATH = "/api/owner"
OWNER_IDLE_MINUTES = 30

_NOT_AUTHENTICATED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Tu sesión no es válida o expiró. Iniciá sesión nuevamente.",
)

# Claves permitidas en "details" de la auditoría del dueño.
_ALLOWED_DETAIL_KEYS = {"reason", "count", "is_active", "role", "feature", "kind", "patients", "files", "counts", "backup"}


@dataclass(frozen=True)
class CurrentOwner:
    id: uuid.UUID
    email: str
    full_name: str
    session_id: uuid.UUID
    csrf_token: str
    must_change_password: bool
    totp_enabled: bool

    @property
    def ready(self) -> bool:
        return not self.must_change_password and self.totp_enabled


def get_owner(request: Request, db: Session = Depends(get_db)) -> CurrentOwner:
    token = request.cookies.get(OWNER_COOKIE)
    if not token:
        raise _NOT_AUTHENTICATED
    now = utcnow()
    session = db.scalar(select(OwnerSession).where(
        OwnerSession.token_hash == hash_token(token), OwnerSession.revoked_at.is_(None)))
    if (session is None or session.expires_at <= now
            or session.last_seen_at + timedelta(minutes=OWNER_IDLE_MINUTES) <= now):
        raise _NOT_AUTHENTICATED
    owner = db.get(SystemOwner, session.owner_id)
    if owner is None or not owner.is_active:
        raise _NOT_AUTHENTICATED
    if request.method not in SAFE_METHODS:
        sent = request.headers.get(CSRF_HEADER, "")
        if not sent or not tokens_equal(sent, session.csrf_token):
            raise HTTPException(status.HTTP_403_FORBIDDEN,
                                detail="Falta la verificación de seguridad (CSRF). Recargá la página.")
    if now - session.last_seen_at > timedelta(minutes=1):
        session.last_seen_at = now
        db.commit()
    return CurrentOwner(
        id=owner.id, email=owner.email, full_name=owner.full_name, session_id=session.id,
        csrf_token=session.csrf_token, must_change_password=owner.must_change_password,
        totp_enabled=owner.totp_enabled,
    )


def require_ready_owner(owner: CurrentOwner = Depends(get_owner)) -> CurrentOwner:
    if not owner.ready:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail="Antes de seguir, cambiá la contraseña temporal y configurá el código del celular.",
        )
    return owner


def record(
    db: Session,
    *,
    owner_id: uuid.UUID | None,
    action: str,
    clinic_id: uuid.UUID | None = None,
    target_user_id: uuid.UUID | None = None,
    details: dict[str, Any] | None = None,
    request: Request | None = None,
) -> None:
    """Auditoría del dueño: solo metadatos (nunca contraseñas, códigos ni datos de pacientes)."""
    db.add(OwnerAuditEvent(
        owner_id=owner_id, action=action, clinic_id=clinic_id, target_user_id=target_user_id,
        details={k: v for k, v in (details or {}).items() if k in _ALLOWED_DETAIL_KEYS},
        ip=(request.client.host if request and request.client else None),
    ))
