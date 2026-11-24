"""Control de los pagos AYEX del BPS.

Administración sube el PDF "Detalle de Item Facturable" que manda el BPS cada mes y Lumen
devuelve solo lo que hay que revisar:

* **Pago menor / pago mayor:** el importe no es el arancel AYEX de la clínica
  (multiplicado por la cantidad de la fila).
* **No figura en el PDF:** paciente AYEX activo de la clínica que el BPS no incluyó.
* **No es paciente / no es AYEX activo:** documento del PDF que no está en Lumen, o que
  está pero no como AYEX activo.
* **Repetido:** el mismo documento dos veces en el mismo mes.

Además compara la suma de las filas con el importe de la factura (encabezado del PDF),
para detectar si falta una página o una fila.

Privacidad: el PDF no se guarda (se lee en memoria). La auditoría registra solo la cantidad
de observaciones, sin documentos ni nombres.
"""

import re
from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app import audit
from app.branches import AFFILIATION_LABELS, branch_names
from app.bps_payments import BpsPdfError, BpsStatement, read_statement
from app.db import get_db
from app.deps import CurrentUser, require_staff_or_titular
from app.features import require_feature
from app.models import AffiliationType, Clinic, Patient, PatientStatus
from app.xlsx import build_xlsx

router = APIRouter(prefix="/api/bps-payments", tags=["pagos del BPS"],
                   dependencies=[Depends(require_feature("bps"))])
# Administración y Recepción (todas las sucursales), o el titular de un espacio independiente.
# El arancel AYEX lo sigue cambiando solo Administración (PATCH /api/clinic).
staff_only = require_staff_or_titular

MAX_BYTES = 5 * 1024 * 1024
NO_FEE = ("Primero cargá el arancel AYEX de la clínica en Usuarios → Clínica "
          "(el importe que paga el BPS por paciente).")

IssueKind = Literal["underpaid", "overpaid", "not_in_bps", "not_patient", "not_ayex", "duplicate"]

KIND_LABELS: dict[str, str] = {
    "underpaid": "Pago menor",
    "overpaid": "Pago mayor",
    "not_in_bps": "No figura en el PDF",
    "not_patient": "No es paciente de la clínica",
    "not_ayex": "No es AYEX activo en Lumen",
    "duplicate": "Repetido en el PDF",
}
_STATUS_LABELS = {"active": "Activo", "paused": "En pausa", "discharged": "Alta", "inactive": "Inactivo"}


class IssueOut(BaseModel):
    kind: IssueKind
    document: str | None
    name: str
    patient_id: str | None = None
    branch_name: str | None = None
    month: str | None = None
    amount: float | None = None
    expected: float | None = None
    difference: float | None = None
    note: str | None = None


class CheckOut(BaseModel):
    fee: float
    months: list[str]
    row_count: int
    ok_count: int
    rows_total: float
    invoice_total: float | None
    totals_match: bool | None
    missing_amount: float   # lo que falta por pagos menores
    issues: list[IssueOut]


def _doc_key(document: str | None) -> str:
    """Documento sin puntos, guiones ni espacios: "1.234.567-8" y "12345678" son el mismo."""
    return re.sub(r"[^0-9A-Z]", "", (document or "").upper())


def _full_name(p: Patient) -> str:
    return " ".join(x for x in (p.first_name, p.middle_name, p.last_name, p.second_last_name) if x)


def _month_start(month: str) -> date | None:
    try:
        return datetime.strptime(month, "%m/%Y").date()
    except ValueError:
        return None


def _compare(db: Session, clinic_id, fee: Decimal, statement: BpsStatement) -> CheckOut:
    patients = db.scalars(select(Patient).where(Patient.clinic_id == clinic_id)).all()
    by_doc = {_doc_key(p.document_number): p for p in patients if _doc_key(p.document_number)}
    branches = branch_names(db, clinic_id)

    def is_active_ayex(p: Patient) -> bool:
        return p.affiliation == AffiliationType.ayex.value and p.status == PatientStatus.active.value

    issues: list[IssueOut] = []
    ok_count = 0
    missing = Decimal("0")
    seen: dict[tuple[str, str], int] = {}
    for row in statement.rows:
        key = _doc_key(row.document)
        patient = by_doc.get(key)
        base = dict(
            document=row.document, month=row.month, amount=float(row.amount),
            name=_full_name(patient) if patient else row.name,
            patient_id=str(patient.id) if patient else None,
            branch_name=branches.get(patient.branch_id) if patient else None,
        )
        problem = False
        seen[(key, row.month)] = seen.get((key, row.month), 0) + 1
        if seen[(key, row.month)] > 1:
            problem = True
            if seen[(key, row.month)] == 2:
                issues.append(IssueOut(kind="duplicate", note=f"El BPS lo incluye más de una vez en {row.month}.",
                                       **base))

        expected = fee * row.quantity
        if row.amount != expected:
            problem = True
            kind = "underpaid" if row.amount < expected else "overpaid"
            if kind == "underpaid":
                missing += expected - row.amount
            note = None
            if row.quantity != 1:
                note = f"Cantidad {row.quantity.normalize()} en la fila del BPS."
            issues.append(IssueOut(kind=kind, expected=float(expected),
                                   difference=float(row.amount - expected), note=note, **base))
        if patient is None:
            problem = True
            issues.append(IssueOut(kind="not_patient", note="No hay ningún paciente con ese documento en Lumen.",
                                   **base))
        elif not is_active_ayex(patient):
            problem = True
            issues.append(IssueOut(kind="not_ayex", note=(
                f"En Lumen figura como {AFFILIATION_LABELS.get(patient.affiliation, patient.affiliation)}, "
                f"{_STATUS_LABELS.get(patient.status, patient.status).lower()}."), **base))
        if not problem:
            ok_count += 1

    months = sorted({r.month for r in statement.rows}, key=lambda m: (m[3:], m[:2]))
    first_month = _month_start(months[0]) if months else None
    in_pdf = {_doc_key(r.document) for r in statement.rows}
    for p in sorted(patients, key=lambda p: (p.last_name.lower(), p.first_name.lower())):
        if not is_active_ayex(p):
            continue
        key = _doc_key(p.document_number)
        if key and key in in_pdf:
            continue
        note = None
        if not key:
            note = "No tiene documento cargado en Lumen: no se puede buscar en el PDF."
        elif p.ayex_expires_on and first_month and p.ayex_expires_on < first_month:
            note = f"Su AYEX venció el {p.ayex_expires_on:%d/%m/%Y}."
        issues.append(IssueOut(kind="not_in_bps", document=p.document_number, name=_full_name(p),
                               patient_id=str(p.id), branch_name=branches.get(p.branch_id),
                               expected=float(fee), note=note))

    # Primero lo más importante para reclamar (el mismo orden que la pantalla y el Excel).
    order = ["underpaid", "not_in_bps", "duplicate", "overpaid", "not_patient", "not_ayex"]
    issues.sort(key=lambda i: order.index(i.kind))
    rows_total = sum((r.amount for r in statement.rows), Decimal("0"))
    invoice = statement.invoice_total
    return CheckOut(
        fee=float(fee), months=months, row_count=len(statement.rows), ok_count=ok_count,
        rows_total=float(rows_total), invoice_total=float(invoice) if invoice is not None else None,
        totals_match=None if invoice is None else rows_total == invoice,
        missing_amount=float(missing), issues=issues,
    )


async def _read_body(request: Request) -> bytes:
    chunks, size = [], 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > MAX_BYTES:
            raise HTTPException(413, detail="El archivo supera el máximo de 5 MB.")
        chunks.append(chunk)
    data = b"".join(chunks)
    if not data.strip():
        raise HTTPException(422, detail="El archivo está vacío.")
    return data


def _check(db: Session, user: CurrentUser, data: bytes) -> CheckOut:
    clinic = db.get(Clinic, user.clinic_id)
    if not clinic.ayex_fee:
        raise HTTPException(409, detail=NO_FEE)
    try:
        statement = read_statement(data)
    except BpsPdfError as exc:
        raise HTTPException(422, detail=str(exc)) from exc
    return _compare(db, user.clinic_id, Decimal(clinic.ayex_fee), statement)


@router.post("/check", response_model=CheckOut)
async def check_payments(request: Request, user: CurrentUser = Depends(staff_only),
                         db: Session = Depends(get_db)):
    """Revisa el PDF del BPS (el cuerpo de la petición es el archivo tal cual). No guarda nada."""
    data = await _read_body(request)
    result = await run_in_threadpool(_check, db, user, data)
    audit.record(db, clinic_id=user.clinic_id, actor_id=user.id, action="bps_payments.check",
                 details={"count": len(result.issues)}, request=request)
    db.commit()
    return result


HEADERS = ["Situación", "Documento", "Nombre", "Sucursal", "Mes cargo", "Importe pagado",
           "Importe esperado", "Diferencia", "Observación"]
WIDTHS = [26, 14, 34, 14, 11, 15, 16, 12, 50]


@router.post("/check/xlsx")
async def check_payments_xlsx(request: Request, user: CurrentUser = Depends(staff_only),
                              db: Session = Depends(get_db)):
    """Lo mismo que /check, pero devuelve un Excel con las observaciones para reclamar."""
    data = await _read_body(request)
    result = await run_in_threadpool(_check, db, user, data)
    rows = [[KIND_LABELS[i.kind], i.document, i.name, i.branch_name, i.month, i.amount, i.expected,
             i.difference, i.note] for i in result.issues]
    content = build_xlsx("Control pagos BPS", HEADERS, rows, WIDTHS)
    audit.record(db, clinic_id=user.clinic_id, actor_id=user.id, action="bps_payments.export",
                 details={"count": len(result.issues)}, request=request)
    db.commit()
    tz = ZoneInfo("America/Montevideo")
    month = result.months[-1].replace("/", "-") if result.months else f"{datetime.now(tz):%m-%Y}"
    filename = f"lumen-control-pagos-bps-{month}.xlsx"
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"',
                 "X-Content-Type-Options": "nosniff", "Cache-Control": "no-store"},
    )
