"""Inicio de sesión del dueño del sistema: contraseña + código de 6 dígitos del celular.

La primera vez entra con la contraseña temporal que muestra el comando del servidor
(``python -m app.dueno_sistema crear``), elige una contraseña nueva y configura la app del
celular. Desde ahí, siempre pide los tres datos: correo, contraseña y código.
"""

from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, StringConstraints
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app import totp
from app.config import get_settings
from app.db import get_db
from app.deps import utcnow
from app.models import OwnerSession, SystemOwner
from app.owner_deps import (
    OWNER_COOKIE, OWNER_COOKIE_PATH, OWNER_IDLE_MINUTES, CurrentOwner, get_owner, record,
)
from app.schemas import ChangePasswordIn
from app.security import (
    burn_verify_time, hash_password, hash_token, new_token, password_needs_rehash, password_problem,
    verify_password,
)

router = APIRouter(prefix="/api/owner/auth", tags=["dueño del sistema"])

_LOGIN_FAILED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail=("Correo, contraseña o código incorrectos, o la cuenta está bloqueada temporalmente. "
            "Si fallaste varias veces, esperá unos minutos."),
)

Code = Annotated[str, StringConstraints(strip_whitespace=True, max_length=12)]


class OwnerLoginIn(BaseModel):
    email: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=254)]
    password: Annotated[str, StringConstraints(min_length=1, max_length=128)]
    code: Code = ""  # vacío solo la primera vez, antes de configurar la app del celular


class OwnerOut(BaseModel):
    email: str
    full_name: str
    must_change_password: bool
    totp_enabled: bool


class OwnerSessionOut(BaseModel):
    owner: OwnerOut
    csrf_token: str
    idle_minutes: int


class TotpStartOut(BaseModel):
    secret: str  # agrupada de a 4 letras, para escribirla en la app
    uri: str


class TotpConfirmIn(BaseModel):
    code: Code


def _payload(owner: SystemOwner, csrf_token: str) -> OwnerSessionOut:
    return OwnerSessionOut(
        owner=OwnerOut(email=owner.email, full_name=owner.full_name,
                       must_change_password=owner.must_change_password,
                       totp_enabled=owner.totp_enabled),
        csrf_token=csrf_token, idle_minutes=OWNER_IDLE_MINUTES,
    )


@router.post("/login", response_model=OwnerSessionOut)
def login(payload: OwnerLoginIn, request: Request, response: Response, db: Session = Depends(get_db)):
    settings = get_settings()
    now = utcnow()
    owner = db.scalar(select(SystemOwner).where(SystemOwner.email == payload.email.strip().lower()))
    if owner is None:
        burn_verify_time(payload.password)
        raise _LOGIN_FAILED
    if owner.locked_until is not None and owner.locked_until > now:
        burn_verify_time(payload.password)
        record(db, owner_id=owner.id, action="owner.login_blocked", request=request)
        db.commit()
        raise _LOGIN_FAILED

    password_ok = verify_password(owner.password_hash, payload.password)
    step = None
    if password_ok and owner.totp_enabled:
        step = totp.verify(owner.totp_secret, payload.code, owner.totp_last_step)
    code_ok = not owner.totp_enabled or step is not None
    if not (password_ok and code_ok) or not owner.is_active:
        if not (password_ok and code_ok):
            owner.failed_login_count += 1
            if owner.failed_login_count >= settings.login_max_failures:
                owner.locked_until = now + timedelta(minutes=settings.login_lock_minutes)
                owner.failed_login_count = 0
        record(db, owner_id=owner.id, action="owner.login_failed", request=request)
        db.commit()
        raise _LOGIN_FAILED

    owner.failed_login_count = 0
    owner.locked_until = None
    if step is not None:
        owner.totp_last_step = step
    if password_needs_rehash(owner.password_hash):
        owner.password_hash = hash_password(payload.password)
    token, csrf_token = new_token(), new_token()
    db.add(OwnerSession(
        token_hash=hash_token(token), csrf_token=csrf_token, owner_id=owner.id, last_seen_at=now,
        expires_at=now + timedelta(hours=settings.session_max_hours),
    ))
    record(db, owner_id=owner.id, action="owner.login", request=request)
    db.commit()
    response.set_cookie(
        key=OWNER_COOKIE, value=token, max_age=settings.session_max_hours * 3600, httponly=True,
        secure=settings.secure_cookies, samesite="strict", path=OWNER_COOKIE_PATH,
    )
    return _payload(owner, csrf_token)


@router.get("/me", response_model=OwnerSessionOut)
def me(owner: CurrentOwner = Depends(get_owner), db: Session = Depends(get_db)):
    return _payload(db.get(SystemOwner, owner.id), owner.csrf_token)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(request: Request, response: Response, owner: CurrentOwner = Depends(get_owner),
           db: Session = Depends(get_db)):
    session = db.get(OwnerSession, owner.session_id)
    session.revoked_at = utcnow()
    record(db, owner_id=owner.id, action="owner.logout", request=request)
    db.commit()
    response.delete_cookie(OWNER_COOKIE, path=OWNER_COOKIE_PATH)


def _revoke_other_sessions(db: Session, owner: CurrentOwner) -> None:
    db.execute(update(OwnerSession).where(
        OwnerSession.owner_id == owner.id, OwnerSession.id != owner.session_id,
        OwnerSession.revoked_at.is_(None)).values(revoked_at=utcnow()))


@router.post("/change-password", status_code=status.HTTP_204_NO_CONTENT)
def change_password(payload: ChangePasswordIn, request: Request,
                    owner: CurrentOwner = Depends(get_owner), db: Session = Depends(get_db)):
    db_owner = db.get(SystemOwner, owner.id)
    if not verify_password(db_owner.password_hash, payload.current_password):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="La contraseña actual no es correcta.")
    problem = password_problem(payload.new_password)
    if problem:
        raise HTTPException(422, detail=problem)
    if payload.new_password == payload.current_password:
        raise HTTPException(422, detail="La contraseña nueva debe ser distinta de la actual.")
    db_owner.password_hash = hash_password(payload.new_password)
    db_owner.must_change_password = False
    _revoke_other_sessions(db, owner)
    record(db, owner_id=owner.id, action="owner.password_changed", request=request)
    db.commit()


@router.post("/totp/start", response_model=TotpStartOut)
def totp_start(owner: CurrentOwner = Depends(get_owner), db: Session = Depends(get_db)):
    """Genera la clave para la app del celular (todavía no queda activa: falta confirmarla)."""
    if owner.must_change_password:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Primero cambiá la contraseña temporal.")
    if owner.totp_enabled:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            detail="El código del celular ya está configurado.")
    db_owner = db.get(SystemOwner, owner.id)
    db_owner.totp_secret = totp.new_secret()
    db.commit()
    return TotpStartOut(secret=totp.grouped(db_owner.totp_secret),
                        uri=totp.provisioning_uri(db_owner.totp_secret, db_owner.email))


@router.post("/totp/confirm", status_code=status.HTTP_204_NO_CONTENT)
def totp_confirm(payload: TotpConfirmIn, request: Request,
                 owner: CurrentOwner = Depends(get_owner), db: Session = Depends(get_db)):
    """Activa el código del celular cuando la app ya genera códigos correctos."""
    db_owner = db.get(SystemOwner, owner.id)
    if owner.totp_enabled:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            detail="El código del celular ya está configurado.")
    if owner.must_change_password or not db_owner.totp_secret:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            detail="Primero cambiá la contraseña y generá la clave para la app.")
    step = totp.verify(db_owner.totp_secret, payload.code, None)
    if step is None:
        raise HTTPException(422, detail=("El código no coincide. Revisá que la clave esté bien escrita en "
                                         "la app y que la hora del celular sea la correcta."))
    db_owner.totp_enabled = True
    db_owner.totp_last_step = step
    _revoke_other_sessions(db, owner)
    record(db, owner_id=owner.id, action="owner.totp_enabled", request=request)
    db.commit()
