"""Dependencias comunes: usuario actual, verificación CSRF y roles.

Cómo funciona la sesión
-----------------------
* Al iniciar sesión el servidor crea un token aleatorio y lo envía en una cookie
  ``HttpOnly`` (JavaScript no puede leerla, lo que limita el robo por XSS) con
  ``SameSite=Strict`` y, en producción, ``Secure`` (solo HTTPS).
* En la base solo se guarda el hash del token.
* Cada sesión tiene además un token CSRF. Toda petición que modifica datos
  (POST, PATCH, PUT, DELETE) debe enviarlo en la cabecera ``X-CSRF-Token``.
* La sesión vence a las ``SESSION_MAX_HOURS`` horas o tras
  ``SESSION_IDLE_MINUTES`` minutos sin actividad.
"""

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.branches import allowed_branches
from app.config import get_settings
from app.db import get_db
from app.models import AuthSession, Clinic, ClinicKind, Role, User
from app.security import hash_token, tokens_equal

SESSION_COOKIE = "medflow_session"
CSRF_HEADER = "X-CSRF-Token"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
PASSWORD_CHANGE_PATHS = {"/api/auth/me", "/api/auth/logout", "/api/auth/change-password"}
# Rutas que funcionan aunque todavía no se haya elegido sucursal.
BRANCH_FREE_PATHS = PASSWORD_CHANGE_PATHS | {"/api/auth/branch"}


def utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class CurrentUser:
    id: uuid.UUID
    clinic_id: uuid.UUID
    role: str
    full_name: str
    email: str
    specialty_id: uuid.UUID | None
    session_id: uuid.UUID
    csrf_token: str
    must_change_password: bool = False
    branch_id: uuid.UUID | None = None  # sucursal activa de la sesión
    clinic_kind: str = ClinicKind.clinic.value  # clínica o profesional independiente

    @property
    def is_admin(self) -> bool:
        return self.role == Role.admin.value

    @property
    def is_reception(self) -> bool:
        return self.role == Role.reception.value

    @property
    def is_professional(self) -> bool:
        return self.role == Role.professional.value

    @property
    def is_independent_space(self) -> bool:
        return self.clinic_kind == ClinicKind.independent.value

    @property
    def is_titular(self) -> bool:
        """Profesional de un espacio independiente: atiende como cualquier profesional (ve solo
        sus pacientes y su historia clínica) y además carga sus pacientes y los datos del
        consultorio, porque no hay Administración ni Recepción que lo hagan por él."""
        return self.is_professional and self.is_independent_space


CLINIC_SUSPENDED = ("El acceso a esta clínica está suspendido. Comunicate con el responsable de "
                    "Nordeste para reactivarlo.")

_NOT_AUTHENTICATED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Tu sesión no es válida o expiró. Iniciá sesión nuevamente.",
)


def get_current_user(request: Request, db: Session = Depends(get_db)) -> CurrentUser:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise _NOT_AUTHENTICATED

    settings = get_settings()
    now = utcnow()
    session = db.scalar(
        select(AuthSession).where(
            AuthSession.token_hash == hash_token(token), AuthSession.revoked_at.is_(None)
        )
    )
    if (
        session is None
        or session.expires_at <= now
        or session.last_seen_at + timedelta(minutes=settings.session_idle_minutes) <= now
    ):
        raise _NOT_AUTHENTICATED

    user = db.scalar(
        select(User).where(User.id == session.user_id, User.clinic_id == session.clinic_id)
    )
    if user is None or not user.is_active:
        raise _NOT_AUTHENTICATED
    clinic_row = db.execute(select(Clinic.suspended_at, Clinic.kind).where(Clinic.id == user.clinic_id)).one()
    if clinic_row.suspended_at is not None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=CLINIC_SUSPENDED)

    if request.method not in SAFE_METHODS:
        sent = request.headers.get(CSRF_HEADER, "")
        if not sent or not tokens_equal(sent, session.csrf_token):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Falta la verificación de seguridad (CSRF). Recargá la página.",
            )

    # Tras un restablecimiento, solo puede cambiar la contraseña (o salir) hasta elegir una nueva.
    if user.must_change_password and request.url.path not in PASSWORD_CHANGE_PATHS:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tenés que cambiar tu contraseña temporal antes de continuar.",
        )

    # Sucursal activa: debe seguir siendo una de las permitidas (pueden quitársela o
    # desactivarla mientras tanto). Si tiene una sola, se elige sola.
    allowed = [b.id for b in allowed_branches(db, user.clinic_id, user.id, user.role)]
    branch_id = session.branch_id if session.branch_id in allowed else None
    if branch_id is None and len(allowed) == 1:
        branch_id = allowed[0]
    if branch_id != session.branch_id:
        session.branch_id = branch_id
        db.commit()
    if branch_id is None and request.url.path not in BRANCH_FREE_PATHS:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Elegí una sucursal para continuar.",
        )

    # Registrar actividad (como máximo una vez por minuto para no escribir en cada petición).
    if now - session.last_seen_at > timedelta(minutes=1):
        session.last_seen_at = now
        db.commit()

    return CurrentUser(
        id=user.id,
        clinic_id=user.clinic_id,
        role=user.role,
        full_name=user.full_name,
        email=user.email,
        specialty_id=user.specialty_id,
        session_id=session.id,
        csrf_token=session.csrf_token,
        must_change_password=user.must_change_password,
        branch_id=branch_id,
        clinic_kind=clinic_row.kind,
    )


def require_admin_or_titular(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    """Administración de una clínica, o el titular de un espacio independiente."""
    if not (user.is_admin or user.is_titular):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tu rol no tiene permiso para realizar esta acción.",
        )
    return user


def require_staff_or_titular(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    """Administración y Recepción de una clínica, o el titular de un espacio independiente
    (cargar, exportar e importar pacientes, formulario AYEX, Cronograma BPS, Pagos BPS)."""
    if not (user.is_admin or user.is_reception or user.is_titular):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tu rol no tiene permiso para realizar esta acción.",
        )
    return user


def require_roles(*roles: Role) -> Callable[..., CurrentUser]:
    allowed = {r.value for r in roles}

    def dependency(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if user.role not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Tu rol no tiene permiso para realizar esta acción.",
            )
        return user

    return dependency
