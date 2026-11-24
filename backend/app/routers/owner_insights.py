"""Pantalla del dueño del sistema: resumen de cada clínica, espacio que ocupa y sus funciones.

Privacidad (igual que en ``owner_clinics``): NUNCA se ven pacientes, turnos, notas ni archivos.
De los pacientes solo hay cantidades (por estado, sucursal, afiliación y mes de alta). De las
cuentas de la clínica, el nombre, el rol y cuándo entraron por última vez (para dar soporte y
saber si la usan).
"""

import uuid
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import audit
from app.db import get_db
from app.deps import utcnow
from app.features import FEATURE_KEYS, FEATURES, enabled_features
from app.models import AuthSession, Branch, Clinic, Patient, PatientFile, PatientStatus, User
from app.owner_deps import CurrentOwner, record, require_ready_owner
from app.routers.owner_clinics import ClinicSummaryOut, _get_clinic, _summaries
from app.storage_usage import ClinicUsage, measure

router = APIRouter(prefix="/api/owner", tags=["dueño del sistema"])

MONTHS_BACK = 12  # altas de pacientes de los últimos 12 meses
DAYS_BACK = 30    # ingresos de los últimos 30 días


class KeyCount(BaseModel):
    key: str
    count: int


class PeriodCount(BaseModel):
    period: str  # "2026-10" (mes) o "2026-10-31" (día)
    count: int


class BranchPatientsOut(BaseModel):
    name: str
    is_active: bool
    active: int
    total: int


class AccountOut(BaseModel):
    id: uuid.UUID
    full_name: str
    role: str
    is_active: bool
    created_at: datetime
    last_seen_at: datetime | None


class FilesOut(BaseModel):
    patient_files: int
    patient_files_withdrawn: int
    patient_files_bytes: int
    degrees: int
    degrees_bytes: int


class TableUsageOut(BaseModel):
    table: str
    label: str
    rows: int
    bytes: int


class ClinicStorageOut(BaseModel):
    clinic_id: uuid.UUID
    name: str
    suspended: bool
    database_bytes: int
    rows: int
    files_count: int
    files_bytes: int
    tables: list[TableUsageOut] = []


class StorageOverviewOut(BaseModel):
    database_bytes: int
    clinics_bytes: int
    shared_bytes: int
    files_bytes: int
    clinics: list[ClinicStorageOut]


class FeatureStateOut(BaseModel):
    key: str
    label: str
    description: str
    enabled: bool


class FeatureIn(BaseModel):
    enabled: bool


class ClinicDashboardOut(BaseModel):
    clinic: ClinicSummaryOut
    patients_total: int
    patients_by_status: list[KeyCount]
    patients_by_affiliation: list[KeyCount]  # solo pacientes activos
    patients_by_branch: list[BranchPatientsOut]
    new_patients_by_month: list[PeriodCount]
    accounts_by_role: list[KeyCount]  # cuentas activas
    accounts: list[AccountOut]
    logins_by_day: list[PeriodCount]
    active_accounts_7d: int
    active_accounts_30d: int
    files: FilesOut
    storage: ClinicStorageOut
    features: list[FeatureStateOut]


def _feature_states(clinic: Clinic) -> list[FeatureStateOut]:
    on = set(enabled_features(clinic.disabled_features))
    return [FeatureStateOut(key=f.key, label=f.label, description=f.description, enabled=f.key in on)
            for f in FEATURES]


def _storage_out(clinic: Clinic, usage: ClinicUsage | None, with_tables: bool) -> ClinicStorageOut:
    usage = usage or ClinicUsage()
    return ClinicStorageOut(
        clinic_id=clinic.id, name=clinic.name, suspended=clinic.suspended_at is not None,
        database_bytes=usage.database_bytes, rows=usage.rows, files_count=usage.files_count,
        files_bytes=usage.files_bytes,
        tables=[TableUsageOut(table=t.table, label=t.label, rows=t.rows, bytes=t.bytes)
                for t in usage.tables] if with_tables else [],
    )


def _month_keys(today: date, count: int) -> list[str]:
    year, month = today.year, today.month
    keys = []
    for _ in range(count):
        keys.append(f"{year:04d}-{month:02d}")
        month -= 1
        if month == 0:
            year, month = year - 1, 12
    return list(reversed(keys))


@router.get("/clinics/{clinic_id}/dashboard", response_model=ClinicDashboardOut)
def clinic_dashboard(clinic_id: uuid.UUID, _: CurrentOwner = Depends(require_ready_owner),
                     db: Session = Depends(get_db)):
    clinic = _get_clinic(db, clinic_id)
    tz = clinic.timezone or "America/Montevideo"
    now = utcnow()
    today = now.astimezone(ZoneInfo(tz)).date()
    in_clinic = Patient.clinic_id == clinic.id

    by_status = dict(db.execute(select(Patient.status, func.count()).where(in_clinic)
                                .group_by(Patient.status)).all())
    by_affiliation = dict(db.execute(
        select(Patient.affiliation, func.count())
        .where(in_clinic, Patient.status == PatientStatus.active.value)
        .group_by(Patient.affiliation)).all())

    branch_rows = db.execute(
        select(Branch.name, Branch.is_active, func.count(Patient.id),
               func.count(Patient.id).filter(Patient.status == PatientStatus.active.value))
        .outerjoin(Patient, (Patient.branch_id == Branch.id) & (Patient.clinic_id == Branch.clinic_id))
        .where(Branch.clinic_id == clinic.id)
        .group_by(Branch.id, Branch.name, Branch.is_active)
        .order_by(func.lower(Branch.name))).all()

    months = _month_keys(today, MONTHS_BACK)
    month_expr = func.to_char(func.timezone(tz, Patient.created_at), "YYYY-MM")
    new_by_month = dict(db.execute(
        select(month_expr, func.count()).where(in_clinic, month_expr >= months[0])
        .group_by(month_expr)).all())

    accounts = db.scalars(select(User).where(User.clinic_id == clinic.id, User.archived_at.is_(None))).all()
    last_seen = dict(db.execute(
        select(AuthSession.user_id, func.max(AuthSession.last_seen_at))
        .where(AuthSession.clinic_id == clinic.id).group_by(AuthSession.user_id)).all())
    roles: dict[str, int] = {}
    for u in accounts:
        if u.is_active:
            roles[u.role] = roles.get(u.role, 0) + 1
    account_rows = sorted(
        accounts, key=lambda u: (last_seen.get(u.id) is None, -(last_seen[u.id].timestamp() if u.id in last_seen else 0),
                                 u.full_name.lower()))

    first_day = today - timedelta(days=DAYS_BACK - 1)
    day_expr = func.to_char(func.timezone(tz, AuthSession.created_at), "YYYY-MM-DD")
    logins = dict(db.execute(
        select(day_expr, func.count()).where(AuthSession.clinic_id == clinic.id,
                                             day_expr >= first_day.isoformat())
        .group_by(day_expr)).all())

    def active_since(days: int) -> int:
        return db.scalar(select(func.count(func.distinct(AuthSession.user_id))).where(
            AuthSession.clinic_id == clinic.id, AuthSession.last_seen_at >= now - timedelta(days=days))) or 0

    files_row = db.execute(select(
        func.count(PatientFile.id).filter(PatientFile.withdrawn_at.is_(None)),
        func.count(PatientFile.id).filter(PatientFile.withdrawn_at.is_not(None)),
        func.coalesce(func.sum(PatientFile.size_bytes), 0),
    ).where(PatientFile.clinic_id == clinic.id)).one()
    usage = measure(db).clinics.get(clinic.id)
    degrees_count = degrees_bytes = 0
    if usage:
        degrees_count = usage.files_count - int(files_row[0]) - int(files_row[1])
        degrees_bytes = usage.files_bytes - int(files_row[2])

    return ClinicDashboardOut(
        clinic=_summaries(db, [clinic.id])[0],
        patients_total=sum(by_status.values()),
        patients_by_status=[KeyCount(key=s.value, count=by_status.get(s.value, 0)) for s in PatientStatus],
        patients_by_affiliation=[KeyCount(key=k, count=v) for k, v in
                                 sorted(by_affiliation.items(), key=lambda kv: -kv[1])],
        patients_by_branch=[BranchPatientsOut(name=n, is_active=a, total=t, active=act)
                            for n, a, t, act in branch_rows],
        new_patients_by_month=[PeriodCount(period=m, count=new_by_month.get(m, 0)) for m in months],
        accounts_by_role=[KeyCount(key=r, count=roles.get(r, 0)) for r in ("admin", "reception", "professional")],
        accounts=[AccountOut(id=u.id, full_name=u.full_name, role=u.role, is_active=u.is_active,
                             created_at=u.created_at, last_seen_at=last_seen.get(u.id))
                  for u in account_rows],
        logins_by_day=[PeriodCount(period=(first_day + timedelta(days=i)).isoformat(),
                                   count=logins.get((first_day + timedelta(days=i)).isoformat(), 0))
                       for i in range(DAYS_BACK)],
        active_accounts_7d=active_since(7),
        active_accounts_30d=active_since(30),
        files=FilesOut(patient_files=int(files_row[0]), patient_files_withdrawn=int(files_row[1]),
                       patient_files_bytes=int(files_row[2]), degrees=max(degrees_count, 0),
                       degrees_bytes=max(degrees_bytes, 0)),
        storage=_storage_out(clinic, usage, with_tables=True),
        features=_feature_states(clinic),
    )


@router.get("/storage", response_model=StorageOverviewOut)
def storage_overview(_: CurrentOwner = Depends(require_ready_owner), db: Session = Depends(get_db)):
    """Espacio de todas las clínicas, de mayor a menor."""
    usage = measure(db)
    clinics = db.scalars(select(Clinic)).all()
    rows = sorted((_storage_out(c, usage.clinics.get(c.id), with_tables=False) for c in clinics),
                  key=lambda r: (-r.database_bytes, r.name.lower()))
    return StorageOverviewOut(
        database_bytes=usage.database_bytes,
        clinics_bytes=sum(r.database_bytes for r in rows),
        shared_bytes=usage.shared_bytes,
        files_bytes=sum(r.files_bytes for r in rows),
        clinics=rows,
    )


@router.put("/clinics/{clinic_id}/features/{key}", response_model=list[FeatureStateOut])
def set_feature(clinic_id: uuid.UUID, key: str, payload: FeatureIn, request: Request,
                owner: CurrentOwner = Depends(require_ready_owner), db: Session = Depends(get_db)):
    """Habilita o deshabilita una función para la clínica. No borra ningún dato: al
    deshabilitarla desaparece del menú y la API la rechaza; al habilitarla vuelve como estaba."""
    if key not in FEATURE_KEYS:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="No existe esa función.")
    clinic = _get_clinic(db, clinic_id)
    if clinic.purged_at is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Los datos de esta clínica ya se borraron.")
    disabled = set(clinic.disabled_features or [])
    if payload.enabled == (key not in disabled):
        return _feature_states(clinic)  # ya estaba así: nada que registrar
    if payload.enabled:
        disabled.discard(key)
    else:
        disabled.add(key)
    clinic.disabled_features = sorted(disabled)
    word = "enabled" if payload.enabled else "disabled"
    audit.record(db, clinic_id=clinic.id, actor_id=None, action=f"system.feature_{word}",
                 entity_type="clinic", entity_id=clinic.id, details={"feature": key}, request=request)
    record(db, owner_id=owner.id, action=f"owner.feature_{'enable' if payload.enabled else 'disable'}",
           clinic_id=clinic.id, details={"feature": key}, request=request)
    db.commit()
    return _feature_states(clinic)
