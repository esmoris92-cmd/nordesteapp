"""Exportación completa de los datos de una clínica (o espacio independiente), desde /sistema.

Es la única función del dueño del sistema que entrega datos de pacientes: existe para cumplir
el contrato (al terminar, la clínica recibe una copia completa de sus datos). Por eso:

* Solo el dueño con su sesión completa (contraseña + código del celular).
* Hay que escribir el motivo y el nombre de la clínica para confirmar.
* Queda en la auditoría del dueño y también en la de la clínica (como "Soporte de Lumen").

Cómo se descarga (en dos pasos, para que un .zip de varios gigas no pase por la memoria del
navegador):

1. ``POST /api/owner/clinics/{id}/export`` arma el .zip en una carpeta temporal del servidor
   (solo la puede leer el usuario del servicio) y devuelve un enlace de descarga.
2. ``GET /api/owner/exports/{código}`` lo baja directo a la carpeta Descargas. El enlace sirve
   UNA sola vez (al empezar a enviarse, el archivo se aparta y al terminar se borra), solo con la
   sesión del dueño que lo generó, y vence a la hora: lo que no se bajó se borra en la próxima
   exportación.

Qué lleva el .zip: ver ``app/clinic_export.py``.
"""

import logging
import re
import secrets
import shutil
import tempfile
import time
import uuid
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, StringConstraints
from sqlalchemy.orm import Session
from starlette.background import BackgroundTask

from app import audit
from app.clinic_export import build_clinic_export
from app.db import get_db
from app.owner_deps import CurrentOwner, record, require_ready_owner
from app.routers.owner_clinics import _get_clinic

router = APIRouter(prefix="/api/owner", tags=["dueño del sistema"])
logger = logging.getLogger("medflow")

EXPIRES_SECONDS = 60 * 60  # un enlace que no se usó vence a la hora
_CODE = re.compile(r"^[A-Za-z0-9_-]{32,64}$")
_NOT_FOUND = HTTPException(status.HTTP_404_NOT_FOUND,
                           detail="El enlace de descarga ya se usó o venció. Generá la exportación de nuevo.")


class ExportIn(BaseModel):
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=300)]
    confirm_name: Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)]


class ExportReadyOut(BaseModel):
    download_url: str
    filename: str
    size_bytes: int
    patients: int
    files: int
    missing_files: int


def exports_dir() -> Path:
    """Carpeta de las exportaciones listas para bajar (dentro de la carpeta temporal del sistema)."""
    path = Path(tempfile.gettempdir()) / "lumen-exportaciones"
    path.mkdir(mode=0o700, exist_ok=True)
    path.chmod(0o700)  # solo el usuario del servicio puede leerla
    return path


def _purge_expired(base: Path) -> None:
    limit = time.time() - EXPIRES_SECONDS
    for folder in base.iterdir():
        try:
            if folder.stat().st_mtime < limit:
                shutil.rmtree(folder, ignore_errors=True)
        except FileNotFoundError:
            pass


def _same_name(a: str, b: str) -> bool:
    return " ".join(a.split()).casefold() == " ".join(b.split()).casefold()


@router.post("/clinics/{clinic_id}/export", response_model=ExportReadyOut)
def export_clinic(clinic_id: uuid.UUID, payload: ExportIn, request: Request,
                  owner: CurrentOwner = Depends(require_ready_owner), db: Session = Depends(get_db)):
    """Arma el .zip con todos los datos de la clínica (y nada de otras) y devuelve el enlace."""
    clinic = _get_clinic(db, clinic_id)
    if clinic.purged_at is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Los datos de esta clínica ya se borraron.")
    if not _same_name(payload.confirm_name, clinic.name):
        raise HTTPException(422, detail="Para confirmar, escribí el nombre de la clínica tal como aparece arriba.")
    base = exports_dir()
    _purge_expired(base)
    code = secrets.token_urlsafe(32)
    workdir = base / code
    workdir.mkdir(mode=0o700)
    try:
        result = build_clinic_export(db, clinic.id, workdir)
        (workdir / "dueno").write_text(str(owner.id), encoding="utf-8")
        # Se registra recién cuando el archivo está listo (así la auditoría dice lo que se entregó).
        audit.record(db, clinic_id=clinic.id, actor_id=None, action="system.clinic_export",
                     entity_type="clinic", entity_id=clinic.id, details={"count": result.patients},
                     request=request)
        record(db, owner_id=owner.id, action="owner.clinic_export", clinic_id=clinic.id,
               details={"reason": payload.reason, "patients": result.patients, "files": result.files},
               request=request)
        db.commit()
    except Exception:
        db.rollback()
        shutil.rmtree(workdir, ignore_errors=True)
        logger.exception("No se pudo generar la exportación de una clínica")  # sin datos de pacientes
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR,
                            detail="No se pudo generar la exportación. Revisá el registro del servidor.")
    return ExportReadyOut(download_url=f"/api/owner/exports/{code}", filename=result.filename,
                          size_bytes=result.size_bytes, patients=result.patients, files=result.files,
                          missing_files=result.missing_files)


@router.get("/exports/{code}")
def download_export(code: str, owner: CurrentOwner = Depends(require_ready_owner)):
    """Baja el .zip una sola vez: al terminar de enviarlo, se borra del servidor."""
    if not _CODE.fullmatch(code):
        raise _NOT_FOUND
    folder = exports_dir() / code
    try:
        if (folder / "dueno").read_text(encoding="utf-8") != str(owner.id):
            raise _NOT_FOUND
        if time.time() - folder.stat().st_mtime > EXPIRES_SECONDS:
            shutil.rmtree(folder, ignore_errors=True)
            raise _NOT_FOUND
        archive = next(folder.glob("*.zip"))
        # Se aparta antes de enviarlo: así un segundo pedido con el mismo enlace ya no lo encuentra.
        sending = folder / "enviando"
        sending.mkdir()
        target = sending / archive.name
        archive.rename(target)
    except (FileNotFoundError, StopIteration, FileExistsError):
        raise _NOT_FOUND
    return FileResponse(
        target, media_type="application/zip", filename=archive.name,
        headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "no-store"},
        background=BackgroundTask(shutil.rmtree, folder, ignore_errors=True),
    )
