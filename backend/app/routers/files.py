"""Archivos adjuntos de pacientes (PDF e imágenes).

Los ven, suben y descargan los profesionales con acceso activo al paciente y, desde el
24/11/2026, también Administración y Recepción (de los pacientes que pueden ver: Recepción,
los de su sucursal y los privados). Retira un archivo quien lo subió o el profesional
responsable. Los archivos de una institución educativa (pestaña Instituciones) los suben
solo los profesionales. Cada operación queda en la auditoría, sin copiar el nombre del
archivo (podría contener datos personales).

Seguridad:
* El tipo se comprueba por el contenido real (firma del archivo), no por la extensión.
* Se guarda con un nombre aleatorio en una carpeta fuera de la parte pública.
* La descarga siempre es "adjunto" con el tipo verificado y `nosniff`, para que el
  navegador no lo ejecute como página.
"""

import hashlib
import os
import re
import secrets
import unicodedata
import uuid
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session, aliased
from starlette.concurrency import run_in_threadpool

from app import audit
from app.config import get_settings
from app.db import get_db
from app.deps import CurrentUser, get_current_user, utcnow
from app.features import require_feature
from app.models import AccessLevel, Patient, PatientFile, PatientInstitution, User
from app.permissions import CLINICAL_FORBIDDEN, get_clinical_patient, get_visible_patient
from app.schemas import FileOut, FileWithdrawIn

router = APIRouter(prefix="/api", tags=["archivos"],
                   dependencies=[Depends(require_feature("archivos"))])

_FILE_NOT_FOUND = HTTPException(status.HTTP_404_NOT_FOUND, detail="Archivo no encontrado.")

# Firma (primeros bytes) -> tipo de contenido permitido.
_SIGNATURES = (
    (b"%PDF-", "application/pdf"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
)
_EXTENSIONS = {"application/pdf": ".pdf", "image/png": ".png", "image/jpeg": ".jpg"}


def _detect_type(data: bytes) -> str | None:
    for signature, content_type in _SIGNATURES:
        if data.startswith(signature):
            return content_type
    return None


def _clean_filename(name: str, content_type: str) -> str:
    """Nombre seguro para mostrar y descargar (nunca se usa para guardar en disco)."""
    name = unicodedata.normalize("NFC", os.path.basename(name or "")).strip()
    name = re.sub(r"[\x00-\x1f\x7f/\\\"<>:|?*]+", "_", name)[:150] or "archivo"
    stem = name.rsplit(".", 1)[0] if "." in name else name
    return f"{stem}{_EXTENSIONS[content_type]}"


def _storage_dir() -> Path:
    path = Path(get_settings().files_dir)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _is_staff(user: CurrentUser) -> bool:
    return user.is_admin or user.is_reception


def _files_patient(db: Session, user: CurrentUser, patient_id: uuid.UUID) -> tuple[Patient, str | None]:
    """Paciente cuyos archivos el usuario puede ver y subir, con su nivel de acceso clínico
    (``None`` para Administración y Recepción), o 404/403."""
    if user.is_professional:
        patient, access = get_clinical_patient(db, user, patient_id)
        return patient, access.level
    if _is_staff(user):
        return get_visible_patient(db, user, patient_id), None
    raise CLINICAL_FORBIDDEN


def _files_query(user: CurrentUser):
    uploader = aliased(User)
    withdrawer = aliased(User)
    return (
        select(PatientFile, uploader.full_name, withdrawer.full_name, PatientInstitution.name)
        .join(uploader, uploader.id == PatientFile.uploaded_by)
        .outerjoin(withdrawer, withdrawer.id == PatientFile.withdrawn_by)
        .outerjoin(PatientInstitution, (PatientInstitution.id == PatientFile.institution_id)
                   & (PatientInstitution.clinic_id == PatientFile.clinic_id))
        .where(PatientFile.clinic_id == user.clinic_id)
    )


def _out(row, user: CurrentUser, access_level: str | None) -> FileOut:
    f, uploader_name, withdrawer_name, institution_name = row
    can_withdraw = f.withdrawn_at is None and (
        f.uploaded_by == user.id or access_level == AccessLevel.responsible.value
    )
    return FileOut(
        id=f.id, original_name=f.original_name, content_type=f.content_type,
        size_bytes=f.size_bytes, description=f.description, uploaded_by_name=uploader_name,
        created_at=f.created_at, withdrawn_at=f.withdrawn_at, withdrawn_by_name=withdrawer_name,
        withdraw_reason=f.withdraw_reason, can_withdraw=can_withdraw,
        institution_id=f.institution_id, institution_name=institution_name,
    )


def _get_file(db: Session, user: CurrentUser, file_id: uuid.UUID):
    """Archivo de un paciente cuyos archivos el usuario puede ver, con su nivel de acceso
    (``None`` para Administración y Recepción), o 404."""
    if not (user.is_professional or _is_staff(user)):
        raise CLINICAL_FORBIDDEN
    row = db.execute(_files_query(user).where(PatientFile.id == file_id)).first()
    if row is None:
        raise _FILE_NOT_FOUND
    try:
        _, level = _files_patient(db, user, row[0].patient_id)
    except HTTPException:
        raise _FILE_NOT_FOUND from None
    return row, level


@router.get("/patients/{patient_id}/files", response_model=list[FileOut])
def list_files(
    patient_id: uuid.UUID,
    request: Request,
    include_withdrawn: bool = False,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    patient, level = _files_patient(db, user, patient_id)
    query = _files_query(user).where(PatientFile.patient_id == patient.id)
    if not include_withdrawn:
        query = query.where(PatientFile.withdrawn_at.is_(None))
    rows = db.execute(query.order_by(PatientFile.created_at.desc())).all()
    audit.record(db, clinic_id=user.clinic_id, actor_id=user.id, action="file.list",
                 entity_type="patient", entity_id=patient.id, patient_id=patient.id,
                 details={"count": len(rows)}, request=request)
    db.commit()
    return [_out(r, user, level) for r in rows]


def _save_upload(db: Session, user: CurrentUser, patient_id: uuid.UUID, data: bytes,
                 filename: str, description: str | None, request: Request,
                 institution_id: uuid.UUID | None = None) -> FileOut:
    patient, level = _files_patient(db, user, patient_id)
    if institution_id is not None and not user.is_professional:
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            detail="Los archivos de una institución los suben los profesionales.")
    if institution_id is not None:  # archivo de una institución de ESTE paciente
        from app.routers.institutions import get_institution  # evita una importación circular
        get_institution(db, user.clinic_id, patient.id, institution_id)
    if not data:
        raise HTTPException(422, detail="El archivo está vacío.")
    content_type = _detect_type(data)
    if content_type is None:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                            detail="Solo se aceptan archivos PDF, PNG o JPG.")
    storage_key = secrets.token_hex(32)
    target = _storage_dir() / storage_key
    target.write_bytes(data)
    try:
        f = PatientFile(
            clinic_id=user.clinic_id, patient_id=patient.id, uploaded_by=user.id,
            original_name=_clean_filename(filename, content_type), content_type=content_type,
            size_bytes=len(data), sha256=hashlib.sha256(data).hexdigest(),
            storage_key=storage_key, description=(description or "").strip()[:300] or None,
            institution_id=institution_id,
        )
        db.add(f)
        db.flush()
        audit.record(db, clinic_id=user.clinic_id, actor_id=user.id, action="file.upload",
                     entity_type="file", entity_id=f.id, patient_id=patient.id,
                     details={"count": len(data)}, request=request)
        db.commit()
    except Exception:
        target.unlink(missing_ok=True)  # no dejar archivos huérfanos si falla la base
        raise
    row = db.execute(_files_query(user).where(PatientFile.id == f.id)).first()
    return _out(row, user, level)


@router.post("/patients/{patient_id}/files", response_model=FileOut,
             status_code=status.HTTP_201_CREATED)
async def upload_file(
    patient_id: uuid.UUID,
    request: Request,
    filename: str = Query(..., min_length=1, max_length=255),
    description: str | None = Query(default=None, max_length=300),
    institution_id: uuid.UUID | None = None,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Sube un archivo. El cuerpo de la petición es el contenido del archivo tal cual."""
    if not (user.is_professional or _is_staff(user)):
        raise CLINICAL_FORBIDDEN
    limit = get_settings().max_upload_mb * 1024 * 1024
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > limit:
        raise HTTPException(413,
                            detail=f"El archivo supera el máximo de {get_settings().max_upload_mb} MB.")
    chunks, size = [], 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > limit:
            raise HTTPException(413,
                                detail=f"El archivo supera el máximo de {get_settings().max_upload_mb} MB.")
        chunks.append(chunk)
    return await run_in_threadpool(
        _save_upload, db, user, patient_id, b"".join(chunks), filename, description, request,
        institution_id,
    )


@router.get("/files/{file_id}/download")
def download_file(
    file_id: uuid.UUID,
    request: Request,
    view: bool = False,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Descarga el archivo. Con ``view=true`` es para verlo dentro de Lumen (visor de PDF o
    imagen): el contenido es el mismo y la auditoría lo registra como "file.view"."""
    (f, *_), _ = _get_file(db, user, file_id)
    if f.withdrawn_at is not None:
        raise _FILE_NOT_FOUND
    path = _storage_dir() / f.storage_key
    if not path.is_file():
        raise HTTPException(status.HTTP_410_GONE, detail="El contenido del archivo no está disponible.")
    data = path.read_bytes()
    audit.record(db, clinic_id=user.clinic_id, actor_id=user.id,
                 action="file.view" if view else "file.download",
                 entity_type="file", entity_id=f.id, patient_id=f.patient_id, request=request)
    db.commit()
    ascii_name = f.original_name.encode("ascii", "ignore").decode() or "archivo"
    disposition = "inline" if view else "attachment"  # "inline": se muestra, no se descarga
    return Response(
        content=data,
        media_type=f.content_type,
        headers={
            "Content-Disposition": f"{disposition}; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(f.original_name)}",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.post("/files/{file_id}/withdraw", response_model=FileOut)
def withdraw_file(
    file_id: uuid.UUID,
    payload: FileWithdrawIn,
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Retira un archivo: deja de mostrarse y descargarse, pero se conserva con el motivo."""
    (f, *_), level = _get_file(db, user, file_id)
    if f.withdrawn_at is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="El archivo ya estaba retirado.")
    if f.uploaded_by != user.id and level != AccessLevel.responsible.value:
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            detail="Solo quien subió el archivo o el profesional responsable pueden retirarlo.")
    f.withdrawn_at = utcnow()
    f.withdrawn_by = user.id
    f.withdraw_reason = payload.reason
    audit.record(db, clinic_id=user.clinic_id, actor_id=user.id, action="file.withdraw",
                 entity_type="file", entity_id=f.id, patient_id=f.patient_id, request=request)
    db.commit()
    row = db.execute(_files_query(user).where(PatientFile.id == f.id)).first()
    return _out(row, user, level)
