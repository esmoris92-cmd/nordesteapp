"""Avisos de Recepción y Administración a los profesionales.

* Recepción y Administración dejan un aviso a un profesional o a todos:
  - Recepción: a los profesionales que trabajan en su sucursal activa.
  - Administración: a cualquier profesional de la clínica ("todos" = toda la clínica).
* El profesional lo ve en la barra amarilla de arriba hasta que toca "Entendido".
* Quien lo dejó ve quién lo leyó. Lo puede retirar quien lo dejó, Recepción de la misma
  sucursal o Administración (no se borra: queda marcado como retirado).
* Recepción ve los avisos dejados desde su sucursal; Administración, todos los de la clínica.
"""

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, StringConstraints
from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from app import audit
from app.db import get_db
from app.deps import CurrentUser, get_current_user, require_roles, utcnow
from app.features import require_feature
from app.models import Branch, Notice, NoticeRecipient, Role, User, UserBranch

router = APIRouter(prefix="/api/notices", tags=["avisos"],
                   dependencies=[Depends(require_feature("avisos"))])
staff_only = require_roles(Role.admin, Role.reception)
MAX_LIST = 100

Message = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]


class NoticeIn(BaseModel):
    message: Message
    professional_id: uuid.UUID | None = None  # None: a todos


class RecipientOut(BaseModel):
    user_id: uuid.UUID
    full_name: str
    read_at: datetime | None


class NoticeOut(BaseModel):
    id: uuid.UUID
    message: str
    author_name: str
    branch_name: str | None
    to_all: bool
    created_at: datetime
    withdrawn_at: datetime | None
    recipients: list[RecipientOut]


class MyNoticeOut(BaseModel):
    id: uuid.UUID
    message: str
    author_name: str
    author_role: str
    created_at: datetime


NOT_FOUND = HTTPException(status.HTTP_404_NOT_FOUND, detail="El aviso no existe o ya no está disponible.")


def _eligible_professionals(db: Session, user: CurrentUser):
    """Profesionales a los que este usuario puede dejar avisos."""
    query = select(User).where(
        User.clinic_id == user.clinic_id, User.role == Role.professional.value,
        User.is_active.is_(True), User.archived_at.is_(None),
    )
    if user.is_reception:
        query = query.where(exists().where(
            UserBranch.user_id == User.id, UserBranch.clinic_id == user.clinic_id,
            UserBranch.branch_id == user.branch_id,
        ))
    return query.order_by(User.full_name)


def _visible_notices(user: CurrentUser):
    # Los avisos automáticos entre profesionales (p. ej. "completó su abordaje") no se listan acá.
    staff = select(User.id).where(User.clinic_id == user.clinic_id, User.role != Role.professional.value)
    query = select(Notice).where(Notice.clinic_id == user.clinic_id, Notice.author_id.in_(staff))
    if user.is_reception:
        query = query.where(Notice.branch_id == user.branch_id)
    return query


def _out(db: Session, notices: list[Notice]) -> list[NoticeOut]:
    if not notices:
        return []
    ids = [n.id for n in notices]
    clinic_id = notices[0].clinic_id
    names = dict(db.execute(select(User.id, User.full_name).where(User.clinic_id == clinic_id)).all())
    branches = dict(db.execute(select(Branch.id, Branch.name).where(Branch.clinic_id == clinic_id)).all())
    recipients: dict[uuid.UUID, list[RecipientOut]] = {i: [] for i in ids}
    for r in db.scalars(select(NoticeRecipient).where(NoticeRecipient.clinic_id == clinic_id,
                                                      NoticeRecipient.notice_id.in_(ids))):
        recipients[r.notice_id].append(RecipientOut(user_id=r.user_id, full_name=names.get(r.user_id, "—"),
                                                    read_at=r.read_at))
    for items in recipients.values():
        items.sort(key=lambda r: r.full_name.lower())
    return [NoticeOut(id=n.id, message=n.message, author_name=names.get(n.author_id, "—"),
                      branch_name=branches.get(n.branch_id), to_all=n.to_all, created_at=n.created_at,
                      withdrawn_at=n.withdrawn_at, recipients=recipients[n.id]) for n in notices]


@router.get("/recipients")
def list_recipients(user: CurrentUser = Depends(staff_only), db: Session = Depends(get_db)):
    """Profesionales a quienes se les puede dejar un aviso (para elegir en el formulario)."""
    return [{"id": u.id, "full_name": u.full_name} for u in db.scalars(_eligible_professionals(db, user))]


@router.post("", response_model=NoticeOut, status_code=status.HTTP_201_CREATED)
def create_notice(payload: NoticeIn, request: Request, user: CurrentUser = Depends(staff_only),
                  db: Session = Depends(get_db)):
    eligible = db.scalars(_eligible_professionals(db, user)).all()
    if payload.professional_id is None:
        targets = eligible
        if not targets:
            raise HTTPException(status.HTTP_409_CONFLICT,
                                detail="No hay profesionales activos a quienes dejarles el aviso.")
    else:
        targets = [u for u in eligible if u.id == payload.professional_id]
        if not targets:
            raise HTTPException(422,
                                detail="Elegí un profesional activo de la lista.")
    notice = Notice(clinic_id=user.clinic_id, author_id=user.id, branch_id=user.branch_id,
                    to_all=payload.professional_id is None, message=payload.message)
    db.add(notice)
    db.flush()
    for u in targets:
        db.add(NoticeRecipient(notice_id=notice.id, user_id=u.id, clinic_id=user.clinic_id))
    audit.record(db, clinic_id=user.clinic_id, actor_id=user.id, action="notice.create",
                 entity_type="notice", entity_id=notice.id, details={"count": len(targets)}, request=request)
    db.commit()
    return _out(db, [notice])[0]


@router.get("", response_model=list[NoticeOut])
def list_notices(user: CurrentUser = Depends(staff_only), db: Session = Depends(get_db)):
    """Avisos dejados (los más nuevos primero)."""
    notices = db.scalars(_visible_notices(user).order_by(Notice.created_at.desc()).limit(MAX_LIST)).all()
    return _out(db, list(notices))


@router.post("/{notice_id}/withdraw", response_model=NoticeOut)
def withdraw_notice(notice_id: uuid.UUID, request: Request, user: CurrentUser = Depends(staff_only),
                    db: Session = Depends(get_db)):
    notice = db.scalar(_visible_notices(user).where(Notice.id == notice_id))
    if notice is None:
        raise NOT_FOUND
    if notice.withdrawn_at is None:
        notice.withdrawn_at = utcnow()
        audit.record(db, clinic_id=user.clinic_id, actor_id=user.id, action="notice.withdraw",
                     entity_type="notice", entity_id=notice.id, request=request)
        db.commit()
    return _out(db, [notice])[0]


@router.get("/mine", response_model=list[MyNoticeOut])
def my_notices(user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    """Avisos sin leer del profesional (para la barra amarilla). Otros roles: lista vacía."""
    if not user.is_professional:
        return []
    rows = db.execute(
        select(Notice, User.full_name, User.role)
        .join(NoticeRecipient, (NoticeRecipient.notice_id == Notice.id)
              & (NoticeRecipient.clinic_id == Notice.clinic_id))
        .join(User, (User.id == Notice.author_id) & (User.clinic_id == Notice.clinic_id))
        .where(Notice.clinic_id == user.clinic_id, NoticeRecipient.user_id == user.id,
               NoticeRecipient.read_at.is_(None), Notice.withdrawn_at.is_(None))
        .order_by(Notice.created_at)
    ).all()
    return [MyNoticeOut(id=n.id, message=n.message, author_name=name, author_role=role, created_at=n.created_at)
            for n, name, role in rows]


@router.post("/{notice_id}/read", status_code=status.HTTP_204_NO_CONTENT)
def mark_read(notice_id: uuid.UUID, request: Request, user: CurrentUser = Depends(get_current_user),
              db: Session = Depends(get_db)):
    recipient = db.scalar(select(NoticeRecipient).where(
        NoticeRecipient.clinic_id == user.clinic_id, NoticeRecipient.notice_id == notice_id,
        NoticeRecipient.user_id == user.id,
    ))
    if recipient is None:
        raise NOT_FOUND
    if recipient.read_at is None:
        recipient.read_at = utcnow()
        audit.record(db, clinic_id=user.clinic_id, actor_id=user.id, action="notice.read",
                     entity_type="notice", entity_id=notice_id, request=request)
        db.commit()
