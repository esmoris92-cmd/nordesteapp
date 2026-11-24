"""Qué sucursal abarcan el Inicio y el informe mensual.

* Profesional: lo SUYO en todas las sucursales donde atiende (no se filtra por sucursal).
* Recepción: solo su sucursal activa.
* Administración: la sucursal activa (sin indicar), "all" para toda la clínica o el id de
  una sucursal.
"""

import uuid
from dataclasses import dataclass

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.deps import CurrentUser
from app.models import Branch


@dataclass
class BranchScope:
    branch_id: uuid.UUID | None  # None = todas
    branch_name: str | None  # None = todas
    scope: str  # "own" (profesional), "branch" o "clinic"


def report_scope(db: Session, user: CurrentUser, branch: str | None) -> BranchScope:
    if user.is_professional:
        return BranchScope(None, None, "own")
    if branch == "all":
        if not user.is_admin:
            raise HTTPException(403, detail="Solo administración puede ver todas las sucursales juntas.")
        return BranchScope(None, None, "clinic")
    branch_id = user.branch_id
    if branch:
        try:
            branch_id = uuid.UUID(branch)
        except ValueError:
            raise HTTPException(422, detail="La sucursal indicada no es válida.") from None
        if not user.is_admin and branch_id != user.branch_id:
            raise HTTPException(403, detail="Solo podés ver los datos de tu sucursal.")
    found = db.scalar(select(Branch).where(Branch.id == branch_id, Branch.clinic_id == user.clinic_id))
    if found is None:
        raise HTTPException(404, detail="Sucursal no encontrada.")
    return BranchScope(found.id, found.name, "branch")
