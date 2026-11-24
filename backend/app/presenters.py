"""Convierte filas de la base en respuestas de la API cuando hace falta combinar tablas."""

import uuid
from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.branches import user_branch_ids
from app.models import Specialty, User
from app.schemas import ProfessionalOut, UserOut


def specialty_names(db: Session, clinic_id: uuid.UUID) -> dict[uuid.UUID, str]:
    rows = db.execute(
        select(Specialty.id, Specialty.name).where(Specialty.clinic_id == clinic_id)
    ).all()
    return {sid: name for sid, name in rows}


def users_out(db: Session, clinic_id: uuid.UUID, users: Iterable[User]) -> list[UserOut]:
    users = list(users)
    names = specialty_names(db, clinic_id)
    branches = user_branch_ids(db, clinic_id, [u.id for u in users])
    from app.routers.degrees import current_degrees  # evita una importación circular
    degrees = current_degrees(db, clinic_id, [u.id for u in users if u.role == "professional"])
    return [
        UserOut.model_validate(u).model_copy(update={
            "specialty_name": names.get(u.specialty_id), "branch_ids": branches.get(u.id, []),
            "degree_id": degrees[u.id].id if u.id in degrees else None,
            "degree_uploaded_at": degrees[u.id].created_at if u.id in degrees else None,
        })
        for u in users
    ]


def user_out(db: Session, user: User) -> UserOut:
    return users_out(db, user.clinic_id, [user])[0]


def professionals_out(db: Session, clinic_id: uuid.UUID, users: Iterable[User]) -> list[ProfessionalOut]:
    users = list(users)
    names = specialty_names(db, clinic_id)
    branches = user_branch_ids(db, clinic_id, [u.id for u in users])
    return [
        ProfessionalOut(id=u.id, full_name=u.full_name, specialty_id=u.specialty_id,
                        specialty_name=names.get(u.specialty_id), branch_ids=branches[u.id])
        for u in users
    ]
