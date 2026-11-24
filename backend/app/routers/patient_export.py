"""Exportar el listado de pacientes a Excel (.xlsx).

* Solo Administración y Recepción (los mismos roles que importan).
* Respeta los filtros del listado (búsqueda, estado y tipo de afiliación).
* Solo datos administrativos: nunca historia clínica, informes ni archivos.
* Cada exportación queda en la auditoría (cantidad de pacientes, sin copiar datos).

Las columnas usan los mismos nombres que la importación: si el archivo se guarda como CSV
desde Excel, se puede volver a importar (las columnas extra se ignoran).
"""

from datetime import date
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy.orm import Session

from app import audit
from app.db import get_db
from app.deps import CurrentUser, require_staff_or_titular
from app.models import AffiliationType, Clinic, PatientStatus
from app.branches import AFFILIATION_LABELS, branch_names
from app.routers.patients import (
    AyexFilter, _responsibles, ayex_due_before, branch_filter_id, filtered_patients,
)
from app.xlsx import build_xlsx

router = APIRouter(prefix="/api/patient-export", tags=["exportación de pacientes"])
staff_only = require_staff_or_titular  # también el titular de un espacio independiente

MAX_ROWS = 20000

_SEX = {"male": "M", "female": "F", "unspecified": "X"}
_AFFILIATION = AFFILIATION_LABELS
_STATUS = {"active": "Activo", "paused": "En pausa", "discharged": "Alta", "inactive": "Inactivo"}

HEADERS = [
    "documento", "primer_nombre", "segundo_nombre", "primer_apellido", "segundo_apellido",
    "sexo", "tipo_afiliacion", "vencimiento_ayex", "fecha_nacimiento", "telefono", "correo",
    "profesional_responsable", "sucursal", "estado", "fecha_registro",
]
WIDTHS = [14, 16, 16, 16, 16, 7, 18, 16, 16, 16, 28, 28, 14, 11, 18]


@router.get("")
def export_patients(
    request: Request,
    q: str | None = Query(default=None, max_length=100),
    status_filter: PatientStatus | None = Query(default=None, alias="status"),
    affiliation: AffiliationType | None = None,
    branch: str | None = Query(default=None, max_length=40),
    ayex: AyexFilter | None = None,
    user: CurrentUser = Depends(staff_only),
    db: Session = Depends(get_db),
):
    query = filtered_patients(user, q, status_filter, affiliation, branch_filter_id(user, branch),
                              ayex=ayex, ayex_before=ayex_due_before(db, user.clinic_id) if ayex else None)
    patients = db.scalars(query.limit(MAX_ROWS)).all()
    names = branch_names(db, user.clinic_id)
    responsibles = _responsibles(db, user.clinic_id, [p.id for p in patients])
    tz = ZoneInfo(db.get(Clinic, user.clinic_id).timezone)
    rows = [
        [
            p.document_number, p.first_name, p.middle_name, p.last_name, p.second_last_name,
            _SEX.get(p.sex or ""), _AFFILIATION.get(p.affiliation), p.ayex_expires_on, p.birth_date, p.phone, p.email,
            responsibles.get(p.id, (None, None))[1], names.get(p.branch_id), _STATUS.get(p.status, p.status),
            p.created_at.astimezone(tz).replace(tzinfo=None),
        ]
        for p in patients
    ]
    content = build_xlsx("Pacientes", HEADERS, rows, WIDTHS)
    audit.record(db, clinic_id=user.clinic_id, actor_id=user.id, action="patient.export",
                 entity_type="patient", details={"count": len(patients)}, request=request)
    db.commit()
    filename = f"lumen-pacientes-{date.today():%Y-%m-%d}.xlsx"
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"',
                 "X-Content-Type-Options": "nosniff"},
    )
