"""Reglas de acceso a pacientes e información clínica.

Todas las consultas filtran por ``clinic_id`` del usuario que inició sesión;
el identificador del paciente nunca alcanza por sí solo para ver datos.

* admin y recepción: ven los datos administrativos (contacto, estado) de los
  pacientes de su clínica, pero NO la historia clínica. De los informes, solo
  pueden LEER (e imprimir) los finalizados; nunca los borradores.
* profesional: ve solo los pacientes sobre los que tiene un acceso activo
  (responsable o colaborador) y, de ellos, la historia clínica y los informes.
* Para quien no tiene permiso, un paciente de otra clínica o sin acceso
  responde "no encontrado" (404) y no revela si existe.
"""

import uuid

from fastapi import HTTPException, status
from sqlalchemy import Select, exists, false, or_, select
from sqlalchemy.orm import Session

from app.deps import CurrentUser
from app.models import AffiliationType, PatientAccess, Patient, Role, User

PATIENT_NOT_FOUND = HTTPException(status.HTTP_404_NOT_FOUND, detail="Paciente no encontrado.")
CLINICAL_FORBIDDEN = HTTPException(
    status.HTTP_403_FORBIDDEN,
    detail="Tu rol no tiene acceso a la historia clínica ni puede crear o modificar informes.",
)


def active_access(
    db: Session, clinic_id: uuid.UUID, user_id: uuid.UUID, patient_id: uuid.UUID
) -> PatientAccess | None:
    return db.scalar(
        select(PatientAccess).where(
            PatientAccess.clinic_id == clinic_id,
            PatientAccess.user_id == user_id,
            PatientAccess.patient_id == patient_id,
            PatientAccess.revoked_at.is_(None),
        )
    )


def visible_patients(user: CurrentUser) -> Select[tuple[Patient]]:
    """Consulta base de pacientes que el usuario puede ver."""
    query = select(Patient).where(Patient.clinic_id == user.clinic_id)
    if user.is_professional:
        query = query.where(
            exists().where(
                PatientAccess.patient_id == Patient.id,
                PatientAccess.clinic_id == user.clinic_id,
                PatientAccess.user_id == user.id,
                PatientAccess.revoked_at.is_(None),
            )
        )
    elif user.is_reception:
        # Recepción: los pacientes de su sucursal activa, más los privados de cualquier
        # sucursal (los privados pueden atenderse en todas; AYEX, Tutela Militar y Tutela Policial, solo en la suya).
        query = query.where(or_(Patient.branch_id == user.branch_id,
                                Patient.affiliation == AffiliationType.private.value))
    elif not user.is_admin:
        query = query.where(false())
    return query


def get_visible_patient(db: Session, user: CurrentUser, patient_id: uuid.UUID) -> Patient:
    patient = db.scalar(visible_patients(user).where(Patient.id == patient_id))
    if patient is None:
        raise PATIENT_NOT_FOUND
    return patient


def get_clinical_patient(
    db: Session, user: CurrentUser, patient_id: uuid.UUID
) -> tuple[Patient, PatientAccess]:
    """Paciente cuya historia clínica el usuario puede leer y escribir."""
    if not user.is_professional:
        raise CLINICAL_FORBIDDEN
    patient = db.scalar(
        select(Patient).where(Patient.id == patient_id, Patient.clinic_id == user.clinic_id)
    )
    access = active_access(db, user.clinic_id, user.id, patient_id) if patient else None
    if patient is None or access is None:
        raise PATIENT_NOT_FOUND
    return patient, access


def get_clinic_professional(db: Session, user: CurrentUser, professional_id: uuid.UUID) -> User:
    """Profesional activo de la misma clínica, o 404."""
    prof = db.scalar(
        select(User).where(
            User.id == professional_id,
            User.clinic_id == user.clinic_id,
            User.role == Role.professional.value,
            User.is_active.is_(True),
        )
    )
    if prof is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Profesional no encontrado.")
    return prof
