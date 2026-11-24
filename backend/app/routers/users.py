"""Administración de la clínica: datos, especialidades, usuarios y profesionales."""

import uuid

from fastapi import APIRouter, Body, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel
from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from app import audit
from app.bps import activity_by_name
from app.db import get_db
from app.deps import CurrentUser, get_current_user, require_admin_or_titular, require_roles, utcnow
from app.models import (
    Appointment, AppointmentStatus, AuthSession, Availability, Branch, Clinic, Patient, Role, Specialty,
    User, UserBranch,
)
from app.presenters import professionals_out, user_out, users_out
from app.schemas import (
    AccountUpdateIn,
    ClinicDetailOut,
    ClinicUpdateIn,
    AppointmentOut,
    BranchIn,
    BranchOut,
    BranchUpdateIn,
    ProfessionalOut,
    ResponsiblePatientOut,
    SpecialtyIn,
    SpecialtyOut,
    SpecialtyUpdateIn,
    UserArchiveIn,
    UserCreateIn,
    UserOut,
    UserUpdateIn,
)
from app import appointment_moves
from app.branches import user_branch_ids
from app.permissions import get_clinic_professional
from app.responsibility import assign_responsible, responsible_accesses_of
from app.routers.agenda import _appointment_rows
from app.security import hash_password, temporary_password

router = APIRouter(prefix="/api", tags=["clínica y usuarios"])
admin_only = require_roles(Role.admin)

_SPECIALTY_NOT_FOUND = HTTPException(status.HTTP_404_NOT_FOUND, detail="Especialidad no encontrada.")


# ---------- Clínica ----------


@router.get("/clinic", response_model=ClinicDetailOut)
def get_clinic(user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    return db.get(Clinic, user.clinic_id)


@router.patch("/clinic", response_model=ClinicDetailOut)
def update_clinic(
    payload: ClinicUpdateIn,
    request: Request,
    user: CurrentUser = Depends(require_admin_or_titular),
    db: Session = Depends(get_db),
):
    """Nombre de la clínica y sus datos como proveedor del BPS (solo los campos enviados)."""
    clinic = db.get(Clinic, user.clinic_id)
    changes = payload.model_dump(exclude_unset=True)
    if "name" in changes and changes["name"] is None:
        del changes["name"]  # el nombre no puede quedar vacío
    for field, value in changes.items():
        setattr(clinic, field, value)
    audit.record(db, clinic_id=user.clinic_id, actor_id=user.id, action="clinic.update",
                 entity_type="clinic", entity_id=clinic.id, details={"fields": sorted(changes)},
                 request=request)
    db.commit()
    return clinic


# ---------- Logo de la clínica ----------

LOGO_MAX_BYTES = 1024 * 1024  # 1 MB: alcanza de sobra para un logo nítido
_LOGO_TYPES = ((b"\x89PNG\r\n\x1a\n", "image/png"), (b"\xff\xd8\xff", "image/jpeg"))
_NO_LOGO = HTTPException(status.HTTP_404_NOT_FOUND, detail="La clínica no tiene logo.")


@router.get("/clinic/logo")
def get_clinic_logo(user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    """El logo de la clínica (para el encabezado de lo que se imprime). Lo ve cualquier usuario
    de la clínica. La dirección lleva ?v=<fecha de subida>, así que se puede guardar en caché."""
    row = db.execute(select(Clinic.logo, Clinic.logo_content_type)
                     .where(Clinic.id == user.clinic_id)).first()
    if row is None or row[0] is None:
        raise _NO_LOGO
    return Response(content=row[0], media_type=row[1] or "application/octet-stream",
                    headers={"Cache-Control": "private, max-age=86400",
                             "X-Content-Type-Options": "nosniff"})


@router.post("/clinic/logo", response_model=ClinicDetailOut)
async def upload_clinic_logo(
    request: Request,
    user: CurrentUser = Depends(require_admin_or_titular),
    db: Session = Depends(get_db),
):
    """Sube (o reemplaza) el logo. El cuerpo es la imagen tal cual: PNG o JPG de hasta 1 MB."""
    too_big = HTTPException(413, detail="El logo supera el máximo de 1 MB. Probá con una imagen más chica.")
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > LOGO_MAX_BYTES:
        raise too_big
    chunks, size = [], 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > LOGO_MAX_BYTES:
            raise too_big
        chunks.append(chunk)
    data = b"".join(chunks)
    if not data:
        raise HTTPException(422, detail="El archivo está vacío.")
    content_type = next((t for sig, t in _LOGO_TYPES if data.startswith(sig)), None)
    if content_type is None:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                            detail="El logo tiene que ser una imagen PNG o JPG.")
    clinic = db.get(Clinic, user.clinic_id)
    clinic.logo, clinic.logo_content_type, clinic.logo_updated_at = data, content_type, utcnow()
    audit.record(db, clinic_id=user.clinic_id, actor_id=user.id, action="clinic.logo_update",
                 entity_type="clinic", entity_id=clinic.id, details={"count": len(data)}, request=request)
    db.commit()
    return clinic


@router.delete("/clinic/logo", response_model=ClinicDetailOut)
def delete_clinic_logo(
    request: Request,
    user: CurrentUser = Depends(require_admin_or_titular),
    db: Session = Depends(get_db),
):
    """Quita el logo: lo impreso vuelve a llevar solo el nombre de la clínica."""
    clinic = db.get(Clinic, user.clinic_id)
    if clinic.logo_updated_at is None:
        raise _NO_LOGO
    clinic.logo, clinic.logo_content_type, clinic.logo_updated_at = None, None, None
    audit.record(db, clinic_id=user.clinic_id, actor_id=user.id, action="clinic.logo_remove",
                 entity_type="clinic", entity_id=clinic.id, request=request)
    db.commit()
    return clinic


# ---------- Datos personales (C.I. y teléfono) y "Mi cuenta" ----------


def _check_document_free(db: Session, clinic_id: uuid.UUID, document: str | None,
                         exclude_id: uuid.UUID | None = None) -> None:
    if not document:
        return
    query = select(User.id).where(User.clinic_id == clinic_id, User.document_number == document)
    if exclude_id is not None:
        query = query.where(User.id != exclude_id)
    if db.scalar(query.limit(1)):
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Ya hay otra cuenta con esa C.I. en la clínica.")


def _apply_personal(db: Session, target: User, changes: dict) -> set[str]:
    """C.I. y teléfono (los usan la edición de Administración y "Mi cuenta")."""
    changed: set[str] = set()
    if "document_number" in changes and changes["document_number"] != target.document_number:
        _check_document_free(db, target.clinic_id, changes["document_number"], exclude_id=target.id)
        target.document_number = changes["document_number"]
        changed.add("document_number")
    if "phone" in changes and changes["phone"] != target.phone:
        target.phone = changes["phone"]
        changed.add("phone")
    for field in ("first_name", "middle_name", "last_name", "second_last_name", "bps_training", "degree_issuer"):
        if field in changes and changes[field] != getattr(target, field):
            setattr(target, field, changes[field])
            changed.add(field)
    return changed


@router.patch("/account", response_model=UserOut)
def update_my_account(
    payload: AccountUpdateIn,
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Cada persona cambia sus datos personales: nombre, C.I. y teléfono. El correo, el rol, la
    especialidad y las sucursales los cambia Administración."""
    target = db.get(User, user.id)
    if "document_number" in payload.model_fields_set and payload.document_number is None:
        raise HTTPException(422, detail="Indicá la C.I.")
    changes = payload.model_dump(exclude_unset=True)
    changed: set[str] = set()
    if changes.get("full_name") and changes["full_name"] != target.full_name:
        target.full_name = changes["full_name"]
        changed.add("full_name")
    changed |= _apply_personal(db, target, changes)
    if changed:
        audit.record(db, clinic_id=user.clinic_id, actor_id=user.id, action="account.update",
                     entity_type="user", entity_id=target.id, details={"fields": sorted(changed)},
                     request=request)
    db.commit()
    return user_out(db, target)


# ---------- Especialidades ----------


def _get_specialty(db: Session, user: CurrentUser, specialty_id: uuid.UUID) -> Specialty:
    sp = db.scalar(
        select(Specialty).where(Specialty.id == specialty_id, Specialty.clinic_id == user.clinic_id)
    )
    if sp is None:
        raise _SPECIALTY_NOT_FOUND
    return sp


def _check_name_free(db: Session, user: CurrentUser, name: str, exclude_id: uuid.UUID | None = None):
    query = select(Specialty.id).where(
        Specialty.clinic_id == user.clinic_id, func.lower(Specialty.name) == name.lower()
    )
    if exclude_id:
        query = query.where(Specialty.id != exclude_id)
    if db.scalar(query):
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Ya existe una especialidad con ese nombre.")


def _specialties_out(db: Session, user: CurrentUser, specialties) -> list[SpecialtyOut]:
    counts = dict(db.execute(
        select(User.specialty_id, func.count())
        .where(User.clinic_id == user.clinic_id, User.role == Role.professional.value,
               User.is_active.is_(True), User.specialty_id.is_not(None))
        .group_by(User.specialty_id)
    ).all())
    return [
        SpecialtyOut(id=s.id, name=s.name, is_active=s.is_active,
                     professional_count=counts.get(s.id, 0), bps_activity=s.bps_activity,
                     bps_activity_auto=activity_by_name(s.name))
        for s in specialties
    ]


@router.get("/specialties", response_model=list[SpecialtyOut])
def list_specialties(
    include_inactive: bool = False,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = select(Specialty).where(Specialty.clinic_id == user.clinic_id)
    if not (include_inactive and user.is_admin):
        query = query.where(Specialty.is_active.is_(True))
    return _specialties_out(db, user, db.scalars(query.order_by(Specialty.name)).all())


@router.post("/specialties", response_model=SpecialtyOut, status_code=status.HTTP_201_CREATED)
def create_specialty(
    payload: SpecialtyIn,
    request: Request,
    user: CurrentUser = Depends(admin_only),
    db: Session = Depends(get_db),
):
    _check_name_free(db, user, payload.name)
    sp = Specialty(clinic_id=user.clinic_id, name=payload.name, is_active=True)
    db.add(sp)
    db.flush()
    audit.record(db, clinic_id=user.clinic_id, actor_id=user.id, action="specialty.create",
                 entity_type="specialty", entity_id=sp.id, request=request)
    db.commit()
    return _specialties_out(db, user, [sp])[0]


@router.patch("/specialties/{specialty_id}", response_model=SpecialtyOut)
def update_specialty(
    specialty_id: uuid.UUID,
    payload: SpecialtyUpdateIn,
    request: Request,
    user: CurrentUser = Depends(admin_only),
    db: Session = Depends(get_db),
):
    """Renombra o activa/desactiva. Desactivar no quita la especialidad a quienes ya la
    tienen; solo impide asignarla a nuevas cuentas."""
    sp = _get_specialty(db, user, specialty_id)
    changed = []
    if payload.name is not None and payload.name != sp.name:
        _check_name_free(db, user, payload.name, exclude_id=sp.id)
        sp.name = payload.name
        changed.append("name")
    if payload.is_active is not None and payload.is_active != sp.is_active:
        sp.is_active = payload.is_active
        changed.append("is_active")
    if "bps_activity" in payload.model_fields_set and payload.bps_activity != sp.bps_activity:
        sp.bps_activity = payload.bps_activity
        changed.append("bps_activity")
    if changed:
        audit.record(db, clinic_id=user.clinic_id, actor_id=user.id, action="specialty.update",
                     entity_type="specialty", entity_id=sp.id,
                     details={"fields": changed, "is_active": sp.is_active}, request=request)
    db.commit()
    return _specialties_out(db, user, [sp])[0]


def _resolve_specialty_for_assignment(
    db: Session, user: CurrentUser, specialty_id: uuid.UUID, current_id: uuid.UUID | None = None
) -> uuid.UUID:
    """La especialidad debe ser de la misma clínica y estar activa (salvo que ya la tuviera)."""
    sp = db.scalar(
        select(Specialty).where(Specialty.id == specialty_id, Specialty.clinic_id == user.clinic_id)
    )
    if sp is None:
        raise HTTPException(422, detail="La especialidad elegida no existe en esta clínica.")
    if not sp.is_active and sp.id != current_id:
        raise HTTPException(422, detail="La especialidad elegida está desactivada.")
    return sp.id


# ---------- Sucursales ----------


def _get_branch(db: Session, user: CurrentUser, branch_id: uuid.UUID) -> Branch:
    branch = db.scalar(select(Branch).where(Branch.id == branch_id, Branch.clinic_id == user.clinic_id))
    if branch is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Sucursal no encontrada.")
    return branch


def _check_branch_name_free(db: Session, user: CurrentUser, name: str,
                            exclude_id: uuid.UUID | None = None) -> None:
    query = select(Branch.id).where(Branch.clinic_id == user.clinic_id,
                                    func.lower(Branch.name) == name.lower())
    if exclude_id:
        query = query.where(Branch.id != exclude_id)
    if db.scalar(query):
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Ya existe una sucursal con ese nombre.")


@router.get("/branches", response_model=list[BranchOut])
def list_branches(user: CurrentUser = Depends(admin_only), db: Session = Depends(get_db)):
    """Todas las sucursales de la clínica, también las desactivadas (para administrarlas)."""
    return db.scalars(select(Branch).where(Branch.clinic_id == user.clinic_id)
                      .order_by(Branch.created_at, Branch.name)).all()


@router.post("/branches", response_model=BranchOut, status_code=status.HTTP_201_CREATED)
def create_branch(payload: BranchIn, request: Request, user: CurrentUser = Depends(admin_only),
                  db: Session = Depends(get_db)):
    _check_branch_name_free(db, user, payload.name)
    branch = Branch(clinic_id=user.clinic_id, name=payload.name, is_active=True)
    db.add(branch)
    db.flush()
    audit.record(db, clinic_id=user.clinic_id, actor_id=user.id, action="branch.create",
                 entity_type="branch", entity_id=branch.id, request=request)
    db.commit()
    return branch


@router.patch("/branches/{branch_id}", response_model=BranchOut)
def update_branch(branch_id: uuid.UUID, payload: BranchUpdateIn, request: Request,
                  user: CurrentUser = Depends(admin_only), db: Session = Depends(get_db)):
    """Renombra o activa/desactiva una sucursal (no se borran: guardan su historial)."""
    branch = _get_branch(db, user, branch_id)
    changed = []
    if payload.name is not None and payload.name != branch.name:
        _check_branch_name_free(db, user, payload.name, exclude_id=branch.id)
        branch.name = payload.name
        changed.append("name")
    if payload.is_active is not None and payload.is_active != branch.is_active:
        if not payload.is_active:
            others = db.scalar(select(func.count()).select_from(Branch).where(
                Branch.clinic_id == user.clinic_id, Branch.is_active.is_(True), Branch.id != branch.id))
            if not others:
                raise HTTPException(status.HTTP_409_CONFLICT,
                                    detail="Debe quedar al menos una sucursal activa.")
            upcoming = _future_in_branches(db, user.clinic_id, {branch.id})
            if upcoming:
                raise HTTPException(
                    status.HTTP_409_CONFLICT,
                    detail=f"La sucursal tiene {upcoming} turno(s) programado(s) a futuro. "
                           "Cancelalos o reprogramalos antes de desactivarla.",
                )
        branch.is_active = payload.is_active
        changed.append("is_active")
    if changed:
        audit.record(db, clinic_id=user.clinic_id, actor_id=user.id, action="branch.update",
                     entity_type="branch", entity_id=branch.id,
                     details={"fields": changed, "is_active": branch.is_active}, request=request)
        db.commit()
    return branch


def _set_user_branches(db: Session, user: CurrentUser, target: User, branch_ids: list[uuid.UUID]) -> None:
    """Asigna las sucursales de una cuenta (Administración no necesita: entra a todas)."""
    if target.role == Role.admin.value:
        db.execute(delete(UserBranch).where(UserBranch.user_id == target.id,
                                            UserBranch.clinic_id == user.clinic_id))
        return
    wanted = set(branch_ids)
    if not wanted:
        raise HTTPException(422, detail="Elegí al menos una sucursal para esta cuenta.")
    found = set(db.scalars(select(Branch.id).where(
        Branch.clinic_id == user.clinic_id, Branch.id.in_(wanted), Branch.is_active.is_(True))).all())
    if found != wanted:
        raise HTTPException(422, detail="Alguna sucursal elegida no existe o está desactivada.")
    removed = set(user_branch_ids(db, user.clinic_id, [target.id])[target.id]) - wanted
    if removed and target.role == Role.professional.value:
        # Quien deja de trabajar en una sucursal no puede dejar turnos allí; sus horarios
        # de esa sucursal se quitan.
        upcoming = _future_in_branches(db, user.clinic_id, removed, professional_id=target.id)
        if upcoming:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail=f"{target.full_name} tiene {upcoming} turno(s) a futuro en la sucursal que "
                       "querés quitarle. Cancelalos o pasalos a otro profesional antes.",
            )
        db.execute(delete(Availability).where(Availability.clinic_id == user.clinic_id,
                                              Availability.professional_id == target.id,
                                              Availability.branch_id.in_(removed)))
    db.execute(delete(UserBranch).where(UserBranch.user_id == target.id,
                                        UserBranch.clinic_id == user.clinic_id))
    for bid in sorted(wanted):
        db.add(UserBranch(user_id=target.id, branch_id=bid, clinic_id=user.clinic_id))


def _future_in_branches(db: Session, clinic_id: uuid.UUID, branch_ids: set[uuid.UUID],
                        professional_id: uuid.UUID | None = None) -> int:
    """Turnos programados a futuro en esas sucursales (de un profesional, si se indica)."""
    query = select(func.count()).select_from(Appointment).where(
        Appointment.clinic_id == clinic_id, Appointment.branch_id.in_(branch_ids),
        Appointment.status == AppointmentStatus.scheduled.value, Appointment.starts_at > utcnow())
    if professional_id is not None:
        query = query.where(Appointment.professional_id == professional_id)
    return db.scalar(query) or 0


# ---------- Profesionales y usuarios ----------


@router.get("/professionals", response_model=list[ProfessionalOut])
def list_professionals(user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    """Lista mínima (nombre y especialidad) para elegir profesional en agenda y accesos."""
    profs = db.scalars(
        select(User)
        .where(User.clinic_id == user.clinic_id, User.role == Role.professional.value,
               User.is_active.is_(True))
        .order_by(User.full_name)
    ).all()
    return professionals_out(db, user.clinic_id, profs)


@router.get("/users", response_model=list[UserOut])
def list_users(
    include_archived: bool = False,
    user: CurrentUser = Depends(admin_only),
    db: Session = Depends(get_db),
):
    query = select(User).where(User.clinic_id == user.clinic_id)
    if not include_archived:
        query = query.where(User.archived_at.is_(None))
    users = db.scalars(query.order_by(User.archived_at.is_not(None), User.full_name)).all()
    return users_out(db, user.clinic_id, users)


def _get_clinic_user(db: Session, user: CurrentUser, user_id: uuid.UUID) -> User:
    target = db.scalar(select(User).where(User.id == user_id, User.clinic_id == user.clinic_id))
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Usuario no encontrado.")
    return target


def _revoke_sessions(db: Session, user_id: uuid.UUID, keep_session_id: uuid.UUID | None = None):
    sessions = update(AuthSession).where(
        AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None)
    )
    if keep_session_id:
        sessions = sessions.where(AuthSession.id != keep_session_id)
    db.execute(sessions.values(revoked_at=utcnow()))


ARCHIVE_REASSIGN_REASON = "Reasignado al eliminar la cuenta del responsable anterior"


ARCHIVE_CANCEL_REASON = "Cuenta del profesional eliminada"


def _patients_word(n: int) -> str:
    return "1 paciente" if n == 1 else f"{n} pacientes"


def _appointments_word(n: int) -> str:
    return "1 turno" if n == 1 else f"{n} turnos"


@router.get("/users/{user_id}/responsible-patients", response_model=list[ResponsiblePatientOut])
def list_responsible_patients(
    user_id: uuid.UUID,
    user: CurrentUser = Depends(admin_only),
    db: Session = Depends(get_db),
):
    """Pacientes de los que esta cuenta es responsable (para reasignarlos al eliminarla)."""
    target = _get_clinic_user(db, user, user_id)
    patient_ids = [a.patient_id for a in responsible_accesses_of(db, user.clinic_id, target.id)]
    if not patient_ids:
        return []
    patients = db.scalars(
        select(Patient).where(Patient.clinic_id == user.clinic_id, Patient.id.in_(patient_ids))
        .order_by(Patient.last_name, Patient.first_name)
    ).all()
    return [
        ResponsiblePatientOut(
            id=p.id,
            full_name=" ".join(x for x in (p.first_name, p.middle_name, p.last_name, p.second_last_name) if x),
            document_number=p.document_number, status=p.status,
        )
        for p in patients
    ]


@router.get("/users/{user_id}/future-appointments", response_model=list[AppointmentOut])
def list_future_appointments(
    user_id: uuid.UUID,
    user: CurrentUser = Depends(admin_only),
    db: Session = Depends(get_db),
):
    """Turnos programados a futuro de esta cuenta (para decidir qué hacer al eliminarla)."""
    target = _get_clinic_user(db, user, user_id)
    ids = [a.id for a in appointment_moves.future_appointments(db, user.clinic_id, target.id)]
    if not ids:
        return []
    return _appointment_rows(db, user, select(Appointment).where(Appointment.id.in_(ids))
                             .order_by(Appointment.starts_at))


@router.post("/users/{user_id}/archive", response_model=UserOut)
def archive_user(
    user_id: uuid.UUID,
    request: Request,
    payload: UserArchiveIn | None = Body(default=None),
    user: CurrentUser = Depends(admin_only),
    db: Session = Depends(get_db),
):
    """"Eliminar" una cuenta: la desactiva y la oculta de la lista, sin borrar nada.

    No se borra porque notas, informes, turnos, accesos y auditoría guardan quién hizo
    cada cosa. Se puede restaurar.

    Si la cuenta es responsable de pacientes, hay que indicar el nuevo responsable de
    cada uno (``reassignments``); todo se hace en una sola operación.
    """
    target = _get_clinic_user(db, user, user_id)
    if target.id == user.id:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="No podés eliminar tu propia cuenta.")
    if target.archived_at is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="La cuenta ya estaba eliminada.")

    reassignments = payload.reassignments if payload else []
    plan = {r.patient_id: r.professional_id for r in reassignments}
    if len(plan) != len(reassignments):
        raise HTTPException(422, detail="Hay pacientes repetidos en la reasignación.")
    held = responsible_accesses_of(db, user.clinic_id, target.id)
    if set(plan) != {a.patient_id for a in held}:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail=f"Esta cuenta es responsable de {_patients_word(len(held))}. "
                   "Elegí un nuevo responsable para cada uno antes de eliminarla.",
        )
    new_profs: dict[uuid.UUID, User] = {}
    for professional_id in set(plan.values()):
        if professional_id == target.id:
            raise HTTPException(status.HTTP_409_CONFLICT,
                                detail="El nuevo responsable no puede ser la cuenta que se elimina.")
        new_profs[professional_id] = get_clinic_professional(db, user, professional_id)
    for access in held:
        assign_responsible(db, user, access.patient_id, new_profs[plan[access.patient_id]],
                           ARCHIVE_REASSIGN_REASON, request)

    # Turnos futuros: cada uno se cancela o pasa a otro profesional (después de reasignar
    # los pacientes, para que el nuevo responsable ya tenga acceso).
    decisions = {d.appointment_id: d for d in (payload.appointments if payload else [])}
    upcoming = appointment_moves.future_appointments(db, user.clinic_id, target.id)
    if len(decisions) != len(payload.appointments if payload else []) or \
            set(decisions) != {a.id for a in upcoming}:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail=f"Esta cuenta tiene {_appointments_word(len(upcoming))} a futuro. "
                   "Indicá si cada uno se cancela o pasa a otro profesional.",
        )
    cancel_reason = (payload.cancel_reason if payload else None) or ARCHIVE_CANCEL_REASON
    for appt in upcoming:
        decision = decisions[appt.id]
        if decision.action == "cancel":
            appointment_moves.cancel(db, user, appt, cancel_reason, request)
        else:
            if decision.professional_id == target.id:
                raise HTTPException(status.HTTP_409_CONFLICT,
                                    detail="No podés pasar turnos a la cuenta que se elimina.")
            get_clinic_professional(db, user, decision.professional_id)
            appointment_moves.move(db, user, appt, decision.professional_id, request,
                                   reason="Se eliminó la cuenta del profesional: pasó a otro profesional.")

    target.is_active = False
    target.archived_at = utcnow()
    _revoke_sessions(db, target.id)
    audit.record(db, clinic_id=user.clinic_id, actor_id=user.id, action="user.archive",
                 entity_type="user", entity_id=target.id,
                 details={"role": target.role, "count": len(held)},
                 request=request)
    db.commit()
    return user_out(db, target)


class PasswordResetOut(BaseModel):
    temporary_password: str


_temporary_password = temporary_password


@router.post("/users/{user_id}/reset-password", response_model=PasswordResetOut)
def reset_password(
    user_id: uuid.UUID,
    request: Request,
    user: CurrentUser = Depends(admin_only),
    db: Session = Depends(get_db),
):
    """Da una contraseña temporal a una cuenta que olvidó la suya.

    La contraseña se muestra UNA sola vez a administración (no se guarda en claro). La
    persona deberá cambiarla al entrar; hasta entonces no puede usar el resto de Nordeste.
    Se cierran sus sesiones abiertas y se quita el bloqueo por intentos fallidos.
    """
    target = _get_clinic_user(db, user, user_id)
    if target.id == user.id:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            detail="Para cambiar tu propia contraseña usá \"Mi cuenta\".")
    if target.archived_at is not None:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            detail="La cuenta está eliminada. Restaurala primero.")
    temporary = _temporary_password()
    target.password_hash = hash_password(temporary)
    target.must_change_password = True
    target.failed_login_count = 0
    target.locked_until = None
    _revoke_sessions(db, target.id)
    audit.record(db, clinic_id=user.clinic_id, actor_id=user.id, action="user.password_reset",
                 entity_type="user", entity_id=target.id, details={"role": target.role},
                 request=request)
    db.commit()
    return PasswordResetOut(temporary_password=temporary)


@router.post("/users/{user_id}/restore", response_model=UserOut)
def restore_user(
    user_id: uuid.UUID,
    request: Request,
    user: CurrentUser = Depends(admin_only),
    db: Session = Depends(get_db),
):
    """Devuelve una cuenta eliminada a la lista. Vuelve DESACTIVADA: hay que reactivarla."""
    target = _get_clinic_user(db, user, user_id)
    if target.archived_at is None:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="La cuenta no estaba eliminada.")
    target.archived_at = None
    audit.record(db, clinic_id=user.clinic_id, actor_id=user.id, action="user.restore",
                 entity_type="user", entity_id=target.id, details={"role": target.role},
                 request=request)
    db.commit()
    return user_out(db, target)


class UserCreatedOut(UserOut):
    """La cuenta nueva y su contraseña temporal (se muestra UNA sola vez a administración)."""
    temporary_password: str


@router.post("/users", response_model=UserCreatedOut, status_code=status.HTTP_201_CREATED)
def create_user(
    payload: UserCreateIn,
    request: Request,
    user: CurrentUser = Depends(admin_only),
    db: Session = Depends(get_db),
):
    """Crea una cuenta con una contraseña temporal: la persona debe cambiarla al entrar por
    primera vez, así administración nunca conoce su contraseña definitiva."""
    if db.scalar(select(User.id).where(User.email == payload.email)):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail="Ya existe una cuenta con ese correo (puede estar entre las eliminadas).",
        )
    specialty_id = (
        _resolve_specialty_for_assignment(db, user, payload.specialty_id)
        if payload.specialty_id else None
    )
    _check_document_free(db, user.clinic_id, payload.document_number)
    temporary = _temporary_password()
    new_user = User(
        clinic_id=user.clinic_id,
        email=payload.email,
        full_name=payload.full_name,
        document_number=payload.document_number,
        phone=payload.phone,
        role=payload.role.value,
        specialty_id=specialty_id,
        max_concurrent_patients=payload.max_concurrent_patients,
        password_hash=hash_password(temporary),
        must_change_password=True,  # administración no debe conocer la contraseña definitiva
    )
    db.add(new_user)
    db.flush()
    _set_user_branches(db, user, new_user, payload.branch_ids)
    audit.record(db, clinic_id=user.clinic_id, actor_id=user.id, action="user.create",
                 entity_type="user", entity_id=new_user.id, details={"role": payload.role.value},
                 request=request)
    db.commit()
    return UserCreatedOut(**user_out(db, new_user).model_dump(), temporary_password=temporary)


@router.patch("/users/{user_id}", response_model=UserOut)
def update_user(
    user_id: uuid.UUID,
    payload: UserUpdateIn,
    request: Request,
    user: CurrentUser = Depends(admin_only),
    db: Session = Depends(get_db),
):
    """Edita nombre, correo, rol, especialidad o estado de una cuenta de la clínica.

    Si cambia el correo o el rol, o se desactiva la cuenta, se cierran sus sesiones
    abiertas (para que vuelva a entrar con los datos y permisos nuevos). Si la persona
    se edita a sí misma, se conserva la sesión actual.
    """
    target = _get_clinic_user(db, user, user_id)
    if target.archived_at is not None:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            detail="La cuenta está eliminada. Restaurala para poder editarla.")
    changes = {k: v for k, v in payload.model_dump(exclude_unset=True).items()
               if v is not None or k in ("specialty_id", "phone", "middle_name", "second_last_name",
                                         "first_name", "last_name", "bps_training", "degree_issuer")}
    if "document_number" in payload.model_fields_set and payload.document_number is None:
        raise HTTPException(422, detail="Indicá la C.I.")
    if target.id == user.id and (
        changes.get("is_active") is False
        or ("role" in changes and changes["role"] != Role.admin)
    ):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail="No podés desactivar tu propia cuenta ni quitarte el rol de administración.",
        )

    changed: set[str] = set()
    if "full_name" in changes and changes["full_name"] != target.full_name:
        target.full_name = changes["full_name"]
        changed.add("full_name")
    changed |= _apply_personal(db, target, changes)
    if "email" in changes and changes["email"] != target.email:
        taken = db.scalar(select(User.id).where(User.email == changes["email"], User.id != target.id))
        if taken:
            raise HTTPException(status.HTTP_409_CONFLICT, detail="Ya existe una cuenta con ese correo.")
        target.email = changes["email"]
        changed.add("email")
    if "role" in changes and changes["role"].value != target.role:
        if target.role == Role.professional.value:
            held = responsible_accesses_of(db, user.clinic_id, target.id)
            if held:
                raise HTTPException(
                    status.HTTP_409_CONFLICT,
                    detail=f"Es responsable de {_patients_word(len(held))}. Cambiale el responsable "
                           "a esos pacientes antes de cambiar su rol.",
                )
            upcoming = appointment_moves.future_appointments(db, user.clinic_id, target.id)
            if upcoming:
                raise HTTPException(
                    status.HTTP_409_CONFLICT,
                    detail=f"Tiene {_appointments_word(len(upcoming))} a futuro. Cancelalos o "
                           "reprogramalos en la Agenda antes de cambiar su rol.",
                )
        target.role = changes["role"].value
        changed.add("role")
    if "specialty_id" in changes:
        new_specialty = (
            _resolve_specialty_for_assignment(db, user, changes["specialty_id"], target.specialty_id)
            if changes["specialty_id"] else None
        )
        if new_specialty != target.specialty_id:
            target.specialty_id = new_specialty
            changed.add("specialty")
    if target.role == Role.professional.value and target.specialty_id is None:
        raise HTTPException(422, detail="Indicá la especialidad del profesional.")
    if target.role != Role.professional.value and target.specialty_id is not None:
        target.specialty_id = None
        changed.add("specialty")
    if ("max_concurrent_patients" in changes
            and changes["max_concurrent_patients"] != target.max_concurrent_patients):
        target.max_concurrent_patients = changes["max_concurrent_patients"]
        changed.add("max_concurrent_patients")
    if "is_active" in changes and changes["is_active"] != target.is_active:
        target.is_active = changes["is_active"]
        changed.add("is_active")
    if payload.branch_ids is not None or "role" in changed:
        current = set(user_branch_ids(db, user.clinic_id, [target.id])[target.id])
        wanted = set(payload.branch_ids) if payload.branch_ids is not None else current
        if target.role == Role.admin.value:
            if current:
                _set_user_branches(db, user, target, [])
                changed.add("branches")
        elif wanted != current or not current:
            _set_user_branches(db, user, target, list(wanted))
            changed.add("branches")

    if changed & {"email", "role"} or ("is_active" in changed and not target.is_active):
        _revoke_sessions(db, target.id, keep_session_id=user.session_id if target.id == user.id else None)

    if changed:
        # Solo los NOMBRES de los campos cambiados, nunca los valores (p. ej. el correo).
        audit.record(db, clinic_id=user.clinic_id, actor_id=user.id, action="user.update",
                     entity_type="user", entity_id=target.id,
                     details={"fields": sorted(changed), "role": target.role,
                              "is_active": target.is_active},
                     request=request)
    db.commit()
    return user_out(db, target)
