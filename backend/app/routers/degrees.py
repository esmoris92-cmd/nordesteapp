"""Título universitario de los profesionales (foto JPG/PNG o PDF, obligatorio).

* Cada profesional sube el suyo desde "Mi cuenta". Hasta que lo sube, Lumen le muestra un
  aviso en todas las pantallas (puede seguir trabajando).
* Lo ven el propio profesional y Administración; nadie más.
* Al subir uno nuevo, el anterior queda guardado como "reemplazado" (no se borra).
* Mismas protecciones que los archivos de pacientes: tipo comprobado por el contenido, nombre
  aleatorio en disco, descarga con ``nosniff`` y cada operación en la auditoría (sin el nombre
  del archivo).
"""

import hashlib
import secrets
import uuid
from datetime import datetime
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app import audit
from app.config import get_settings
from app.db import get_db
from app.deps import CurrentUser, get_current_user, utcnow
from app.models import ProfessionalDegree, Role, User
from app.routers.files import _clean_filename, _detect_type, _storage_dir

router = APIRouter(prefix="/api", tags=["título profesional"])

_NOT_FOUND = HTTPException(status.HTTP_404_NOT_FOUND, detail="Título no encontrado.")


class DegreeOut(BaseModel):
    id: uuid.UUID
    original_name: str
    content_type: str
    size_bytes: int
    created_at: datetime


def current_degree(db: Session, clinic_id: uuid.UUID, user_id: uuid.UUID) -> ProfessionalDegree | None:
    return db.scalar(select(ProfessionalDegree).where(
        ProfessionalDegree.clinic_id == clinic_id, ProfessionalDegree.user_id == user_id,
        ProfessionalDegree.replaced_at.is_(None),
    ).order_by(ProfessionalDegree.created_at.desc()).limit(1))


def current_degrees(db: Session, clinic_id: uuid.UUID, user_ids: list[uuid.UUID]) -> dict[uuid.UUID, ProfessionalDegree]:
    if not user_ids:
        return {}
    rows = db.scalars(select(ProfessionalDegree).where(
        ProfessionalDegree.clinic_id == clinic_id, ProfessionalDegree.user_id.in_(user_ids),
        ProfessionalDegree.replaced_at.is_(None),
    )).all()
    return {d.user_id: d for d in rows}


def _out(d: ProfessionalDegree | None) -> DegreeOut | None:
    return DegreeOut(id=d.id, original_name=d.original_name, content_type=d.content_type,
                     size_bytes=d.size_bytes, created_at=d.created_at) if d else None


@router.get("/account/degree", response_model=DegreeOut | None)
def my_degree(user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    return _out(current_degree(db, user.clinic_id, user.id))


def _save(db: Session, user: CurrentUser, data: bytes, filename: str, request: Request) -> DegreeOut:
    if not data:
        raise HTTPException(422, detail="El archivo está vacío.")
    content_type = _detect_type(data)
    if content_type is None:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                            detail="Solo se aceptan fotos JPG o PNG, o un PDF.")
    storage_key = secrets.token_hex(32)
    target = _storage_dir() / storage_key
    target.write_bytes(data)
    try:
        previous = current_degree(db, user.clinic_id, user.id)
        if previous is not None:
            previous.replaced_at = utcnow()
        d = ProfessionalDegree(
            clinic_id=user.clinic_id, user_id=user.id,
            original_name=_clean_filename(filename, content_type), content_type=content_type,
            size_bytes=len(data), sha256=hashlib.sha256(data).hexdigest(), storage_key=storage_key,
        )
        db.add(d)
        db.flush()
        audit.record(db, clinic_id=user.clinic_id, actor_id=user.id, action="degree.upload",
                     entity_type="degree", entity_id=d.id,
                     details={"replaced": previous is not None}, request=request)
        db.commit()
    except Exception:
        target.unlink(missing_ok=True)  # no dejar archivos huérfanos si falla la base
        raise
    return _out(d)


@router.post("/account/degree", response_model=DegreeOut, status_code=status.HTTP_201_CREATED)
async def upload_degree(
    request: Request,
    filename: str = Query(..., min_length=1, max_length=255),
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Sube (o reemplaza) el título del profesional. El cuerpo es el archivo tal cual."""
    if not user.is_professional:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Solo los profesionales cargan su título.")
    limit = get_settings().max_upload_mb * 1024 * 1024
    too_big = HTTPException(413, detail=f"El archivo supera el máximo de {get_settings().max_upload_mb} MB.")
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > limit:
        raise too_big
    chunks, size = [], 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > limit:
            raise too_big
        chunks.append(chunk)
    return await run_in_threadpool(_save, db, user, b"".join(chunks), filename, request)


@router.get("/users/{user_id}/degree", response_model=DegreeOut | None)
def user_degree(user_id: uuid.UUID, user: CurrentUser = Depends(get_current_user),
                db: Session = Depends(get_db)):
    """Título actual de una cuenta: lo consultan Administración o la propia persona."""
    if not (user.is_admin or user.id == user_id):
        raise _NOT_FOUND
    return _out(current_degree(db, user.clinic_id, user_id))


@router.get("/degrees/{degree_id}/download")
def download_degree(
    degree_id: uuid.UUID,
    request: Request,
    view: bool = False,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Descarga (o, con ``view=true``, muestra dentro de Lumen) un título. Solo Administración o
    su dueño; cualquier otra persona recibe 404 (no se revela que existe)."""
    d = db.scalar(select(ProfessionalDegree).where(ProfessionalDegree.id == degree_id,
                                                   ProfessionalDegree.clinic_id == user.clinic_id))
    if d is None or not (user.is_admin or d.user_id == user.id):
        raise _NOT_FOUND
    path = _storage_dir() / d.storage_key
    if not path.is_file():
        raise HTTPException(status.HTTP_410_GONE, detail="El contenido del archivo no está disponible.")
    data = path.read_bytes()
    audit.record(db, clinic_id=user.clinic_id, actor_id=user.id,
                 action="degree.view" if view else "degree.download",
                 entity_type="degree", entity_id=d.id, details={"owner_id": str(d.user_id)},
                 request=request)
    db.commit()
    ascii_name = d.original_name.encode("ascii", "ignore").decode() or "titulo"
    disposition = "inline" if view else "attachment"
    return Response(content=data, media_type=d.content_type, headers={
        "Content-Disposition": f"{disposition}; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(d.original_name)}",
        "X-Content-Type-Options": "nosniff",
    })
