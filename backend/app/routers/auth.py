"""Inicio y cierre de sesión."""

import uuid
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app import audit
from app.config import get_settings
from app.db import get_db
from app.deps import CLINIC_SUSPENDED, SESSION_COOKIE, CurrentUser, get_current_user, utcnow
from app.models import AuthSession, Clinic, User
from app.presenters import user_out
from app.branches import allowed_branches
from app.schemas import BranchChoiceIn, BranchOut, ChangePasswordIn, ClinicOut, LoginIn, SessionOut
from app.security import (
    burn_verify_time,
    hash_password,
    hash_token,
    new_token,
    password_needs_rehash,
    password_problem,
    verify_password,
)

router = APIRouter(prefix="/api/auth", tags=["autenticación"])

# Mismo mensaje para todos los fallos: no revela si el correo existe.
_LOGIN_FAILED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail=(
        "Correo o contraseña incorrectos, o la cuenta está bloqueada temporalmente. "
        "Si fallaste varias veces, esperá unos minutos."
    ),
)


def _session_payload(db: Session, user: User, csrf_token: str,
                     branch_id: uuid.UUID | None) -> SessionOut:
    clinic = db.get(Clinic, user.clinic_id)
    branches = allowed_branches(db, user.clinic_id, user.id, user.role)
    active = next((b for b in branches if b.id == branch_id), None)
    # Para avisar antes de que la sesión se cierre (por inactividad o por el máximo de horas).
    expires_at = db.scalar(select(AuthSession.expires_at).where(
        AuthSession.csrf_token == csrf_token, AuthSession.user_id == user.id))
    return SessionOut(
        user=user_out(db, user),
        clinic=ClinicOut.model_validate(clinic),
        csrf_token=csrf_token,
        branches=[BranchOut.model_validate(b) for b in branches],
        active_branch=BranchOut.model_validate(active) if active else None,
        idle_minutes=get_settings().session_idle_minutes,
        expires_at=expires_at,
    )


@router.post("/login", response_model=SessionOut)
def login(payload: LoginIn, request: Request, response: Response, db: Session = Depends(get_db)):
    settings = get_settings()
    now = utcnow()
    user = db.scalar(select(User).where(User.email == payload.email.strip().lower()))

    if user is None:
        burn_verify_time(payload.password)
        raise _LOGIN_FAILED

    if user.locked_until is not None and user.locked_until > now:
        burn_verify_time(payload.password)
        audit.record(db, clinic_id=user.clinic_id, actor_id=user.id, action="auth.login_blocked",
                     entity_type="user", entity_id=user.id, request=request)
        db.commit()
        raise _LOGIN_FAILED

    password_ok = verify_password(user.password_hash, payload.password)
    if not password_ok or not user.is_active:
        if not password_ok:
            user.failed_login_count += 1
            if user.failed_login_count >= settings.login_max_failures:
                user.locked_until = now + timedelta(minutes=settings.login_lock_minutes)
                user.failed_login_count = 0
        audit.record(db, clinic_id=user.clinic_id, actor_id=user.id, action="auth.login_failed",
                     entity_type="user", entity_id=user.id, request=request)
        db.commit()
        raise _LOGIN_FAILED

    user.failed_login_count = 0
    user.locked_until = None
    # Clínica suspendida: se avisa recién con la contraseña correcta (no revela nada a terceros).
    if db.scalar(select(Clinic.suspended_at).where(Clinic.id == user.clinic_id)) is not None:
        audit.record(db, clinic_id=user.clinic_id, actor_id=user.id, action="auth.login_suspended",
                     entity_type="user", entity_id=user.id, request=request)
        db.commit()
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail=CLINIC_SUSPENDED)
    if password_needs_rehash(user.password_hash):
        user.password_hash = hash_password(payload.password)

    token = new_token()
    csrf_token = new_token()
    branches = allowed_branches(db, user.clinic_id, user.id, user.role)
    branch_id = branches[0].id if len(branches) == 1 else None  # con una sola, entra directo
    db.add(
        AuthSession(
            token_hash=hash_token(token),
            csrf_token=csrf_token,
            clinic_id=user.clinic_id,
            user_id=user.id,
            last_seen_at=now,
            expires_at=now + timedelta(hours=settings.session_max_hours),
            branch_id=branch_id,
        )
    )
    audit.record(db, clinic_id=user.clinic_id, actor_id=user.id, action="auth.login",
                 entity_type="user", entity_id=user.id, request=request)
    db.commit()

    response.set_cookie(
        key=SESSION_COOKIE,
        value=token,
        max_age=settings.session_max_hours * 3600,
        httponly=True,
        secure=settings.secure_cookies,
        samesite="strict",
        path="/api",
    )
    return _session_payload(db, user, csrf_token, branch_id)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    request: Request,
    response: Response,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    session = db.get(AuthSession, user.session_id)
    if session is not None:
        session.revoked_at = utcnow()
    audit.record(db, clinic_id=user.clinic_id, actor_id=user.id, action="auth.logout",
                 entity_type="user", entity_id=user.id, request=request)
    db.commit()
    response.delete_cookie(SESSION_COOKIE, path="/api")


@router.get("/me", response_model=SessionOut)
def me(user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    db_user = db.get(User, user.id)
    return _session_payload(db, db_user, user.csrf_token, user.branch_id)


@router.post("/branch", response_model=SessionOut)
def choose_branch(
    payload: BranchChoiceIn,
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Elige (o cambia) la sucursal de esta sesión, entre las permitidas para la cuenta."""
    allowed = {b.id for b in allowed_branches(db, user.clinic_id, user.id, user.role)}
    if payload.branch_id not in allowed:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="No tenés acceso a esa sucursal.")
    session = db.get(AuthSession, user.session_id)
    session.branch_id = payload.branch_id
    audit.record(db, clinic_id=user.clinic_id, actor_id=user.id, action="auth.branch",
                 entity_type="branch", entity_id=payload.branch_id, request=request)
    db.commit()
    return _session_payload(db, db.get(User, user.id), user.csrf_token, payload.branch_id)


@router.post("/change-password", status_code=status.HTTP_204_NO_CONTENT)
def change_password(
    payload: ChangePasswordIn,
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    db_user = db.get(User, user.id)
    if not verify_password(db_user.password_hash, payload.current_password):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="La contraseña actual no es correcta.")
    problem = password_problem(payload.new_password)
    if problem:
        raise HTTPException(422, detail=problem)
    if payload.new_password == payload.current_password:
        raise HTTPException(422, detail="La contraseña nueva debe ser distinta de la actual.")
    db_user.password_hash = hash_password(payload.new_password)
    db_user.must_change_password = False
    # Cierra las demás sesiones abiertas de esta persona.
    db.execute(
        update(AuthSession)
        .where(AuthSession.user_id == user.id, AuthSession.id != user.session_id,
               AuthSession.revoked_at.is_(None))
        .values(revoked_at=utcnow())
    )
    audit.record(db, clinic_id=user.clinic_id, actor_id=user.id, action="auth.password_changed",
                 entity_type="user", entity_id=user.id, request=request)
    db.commit()
