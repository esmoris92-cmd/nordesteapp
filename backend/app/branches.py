"""Sucursales: a cuáles puede entrar cada cuenta.

* Administración entra a todas las sucursales activas de su clínica.
* Recepción y profesionales, solo a las que tienen asignadas (tabla ``user_branches``).
"""

import uuid

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AffiliationType, Branch, Patient, Role, UserBranch


# Nombres para mostrar de cada tipo de afiliación (mensajes, informes y exportaciones).
AFFILIATION_LABELS = {
    AffiliationType.private.value: "Privado",
    AffiliationType.ayex.value: "AYEX",
    AffiliationType.military.value: "Tutela Militar",
    AffiliationType.police.value: "Tutela Policial",
}


def allowed_branches(db: Session, clinic_id: uuid.UUID, user_id: uuid.UUID, role: str) -> list[Branch]:
    query = select(Branch).where(Branch.clinic_id == clinic_id, Branch.is_active.is_(True))
    if role != Role.admin.value:
        query = query.join(UserBranch, (UserBranch.branch_id == Branch.id)
                           & (UserBranch.clinic_id == Branch.clinic_id)).where(UserBranch.user_id == user_id)
    return list(db.scalars(query.order_by(Branch.created_at, Branch.name)).all())


def user_branch_ids(db: Session, clinic_id: uuid.UUID, user_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[uuid.UUID]]:
    """Sucursales asignadas (activas o no) de varias cuentas, para mostrarlas en Usuarios."""
    result: dict[uuid.UUID, list[uuid.UUID]] = {uid: [] for uid in user_ids}
    if not user_ids:
        return result
    rows = db.execute(select(UserBranch.user_id, UserBranch.branch_id).where(
        UserBranch.clinic_id == clinic_id, UserBranch.user_id.in_(user_ids))).all()
    for uid, bid in rows:
        result[uid].append(bid)
    return result


def resolve_branch(db: Session, clinic_id: uuid.UUID, user_id: uuid.UUID, role: str,
                   branch_id: uuid.UUID | None, default: uuid.UUID | None) -> uuid.UUID:
    """Sucursal elegida para un paciente: una de las permitidas para quien la elige.

    Sin elección, se usa la sucursal activa de la sesión (``default``).
    """
    wanted = branch_id or default
    if wanted is None or wanted not in {b.id for b in allowed_branches(db, clinic_id, user_id, role)}:
        raise HTTPException(422, detail="Elegí una sucursal válida (una de las tuyas).")
    return wanted


def branch_names(db: Session, clinic_id: uuid.UUID) -> dict[uuid.UUID, str]:
    return dict(db.execute(select(Branch.id, Branch.name).where(Branch.clinic_id == clinic_id)).all())


def works_in_branch(db: Session, clinic_id: uuid.UUID, user_id: uuid.UUID, branch_id: uuid.UUID) -> bool:
    """¿La cuenta (profesional o recepción) tiene asignada esta sucursal?"""
    return db.scalar(select(UserBranch.user_id).where(
        UserBranch.clinic_id == clinic_id, UserBranch.user_id == user_id,
        UserBranch.branch_id == branch_id)) is not None


def check_patient_branch(db: Session, patient: Patient, branch_id: uuid.UUID) -> None:
    """AYEX, Tutela Militar y Tutela Policial se atienden solo en la sucursal del paciente;
    privados, en cualquiera."""
    if patient.affiliation == AffiliationType.private.value or patient.branch_id == branch_id:
        return
    names = branch_names(db, patient.clinic_id)
    kind = AFFILIATION_LABELS.get(patient.affiliation, patient.affiliation)
    raise HTTPException(
        409,
        detail=f"{patient.first_name} {patient.last_name} es de {kind}: solo se atiende en la "
               f"sucursal {names.get(patient.branch_id, '')}.",
    )
