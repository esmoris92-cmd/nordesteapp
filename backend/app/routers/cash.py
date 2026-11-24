"""Caja diaria de cada sucursal.

* Hay UNA caja por sucursal y por día (hora de la clínica). La abre Recepción o
  Administración con el efectivo que hay al empezar el día.
* Mientras está abierta se cargan entradas y salidas de efectivo, con un concepto. Un
  movimiento equivocado no se borra: se anula (con el motivo) y deja de contar.
* Al cerrar se ingresa el efectivo contado. Lumen calcula lo esperado
  (inicial + entradas - salidas) y guarda la diferencia (sobrante o faltante). Si hay
  diferencia, hay que explicar el motivo.
* No se puede abrir la caja de hoy si quedó abierta la de un día anterior: primero se cierra.
* Una caja cerrada no se modifica. Solo Administración puede reabrirla (queda en la auditoría).
* Recepción trabaja solo con la caja de su sucursal activa. Administración, con la de
  cualquier sucursal, y en el balance puede ver todas juntas.
* Balance semanal (lunes a domingo), mensual o anual: entradas, salidas, neto y diferencias
  de cierre.
"""

import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, StringConstraints, field_validator
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import audit
from app.branch_scope import report_scope
from app.clinic_time import clinic_today
from app.db import get_db
from app.deps import CurrentUser, require_roles, utcnow
from app.features import require_feature
from app.models import Branch, CashMovement, CashMovementKind, CashRegister, Role, User

router = APIRouter(prefix="/api/cash", tags=["caja"],
                   dependencies=[Depends(require_feature("caja"))])
staff_only = require_roles(Role.admin, Role.reception)
admin_only = require_roles(Role.admin)

MAX_AMOUNT = Decimal("99999999.99")
ZERO = Decimal("0.00")
NOT_FOUND = HTTPException(status.HTTP_404_NOT_FOUND, detail="La caja no existe o no es de tu sucursal.")

Concept = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Reason = Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=200)]
Note = Annotated[str, StringConstraints(strip_whitespace=True, max_length=300)]


def _parse_amount(value: object, *, allow_zero: bool) -> Decimal:
    """Monto en pesos: acepta 1500, 1500.5 o "1500,50"; hasta 2 decimales."""
    if isinstance(value, bool) or value is None or value == "":
        raise ValueError("Ingresá un monto.")
    text = str(value).strip().replace(" ", "")
    if "," in text:  # coma decimal (1500,50); el punto de miles no se usa
        text = text.replace(".", "").replace(",", ".")
    try:
        amount = Decimal(text)
    except InvalidOperation:
        raise ValueError("El monto debe ser un número (por ejemplo 1500 o 1500,50).") from None
    if not amount.is_finite():
        raise ValueError("El monto debe ser un número (por ejemplo 1500 o 1500,50).")
    if amount < 0 or (amount == 0 and not allow_zero):
        raise ValueError("El monto debe ser mayor que cero." if not allow_zero
                         else "El monto no puede ser negativo.")
    if amount != amount.quantize(Decimal("0.01")):
        raise ValueError("El monto puede tener como máximo 2 decimales.")
    if amount > MAX_AMOUNT:
        raise ValueError("El monto es demasiado alto.")
    return amount.quantize(Decimal("0.01"))


class OpenIn(BaseModel):
    opening_amount: Decimal
    branch_id: uuid.UUID | None = None  # Administración elige la sucursal; Recepción, la suya

    @field_validator("opening_amount", mode="before")
    @classmethod
    def _amount(cls, v):
        return _parse_amount(v, allow_zero=True)


class MovementIn(BaseModel):
    kind: CashMovementKind
    amount: Decimal
    concept: Concept

    @field_validator("amount", mode="before")
    @classmethod
    def _amount(cls, v):
        return _parse_amount(v, allow_zero=False)


class VoidIn(BaseModel):
    reason: Reason


class CloseIn(BaseModel):
    counted_amount: Decimal
    note: Note | None = None

    @field_validator("counted_amount", mode="before")
    @classmethod
    def _amount(cls, v):
        return _parse_amount(v, allow_zero=True)


class MovementOut(BaseModel):
    id: uuid.UUID
    kind: CashMovementKind
    amount: float
    concept: str
    created_by_name: str
    created_at: datetime
    voided_at: datetime | None
    voided_by_name: str | None
    void_reason: str | None


class RegisterOut(BaseModel):
    id: uuid.UUID
    branch_id: uuid.UUID
    branch_name: str
    business_date: date
    status: Literal["open", "closed"]
    opening_amount: float
    income: float  # suma de entradas (sin las anuladas)
    expense: float  # suma de salidas (sin las anuladas)
    expected_amount: float  # inicial + entradas - salidas (al cerrar, lo calculado en ese momento)
    counted_amount: float | None
    difference: float | None  # contado - esperado: positivo = sobrante, negativo = faltante
    closing_note: str | None
    opened_by_name: str
    opened_at: datetime
    closed_by_name: str | None
    closed_at: datetime | None
    reopen_count: int
    movements: list[MovementOut] | None = None  # solo en el detalle


class TodayOut(BaseModel):
    today: date
    branch_id: uuid.UUID
    branch_name: str
    current: RegisterOut | None  # la caja de hoy (con sus movimientos), si ya se abrió
    pending: list[RegisterOut]  # cajas de días anteriores que quedaron abiertas
    suggested_opening: float | None  # lo contado en el último cierre de esta sucursal


class Totals(BaseModel):
    income: float = 0
    expense: float = 0
    net: float = 0  # entradas - salidas
    difference: float = 0  # suma de sobrantes y faltantes de los cierres
    registers: int = 0  # cajas abiertas en el período
    open_registers: int = 0  # de ellas, las que todavía no se cerraron


class BalanceRow(Totals):
    key: str  # "2026-10-30" (semana y mes) o "2026-10" (año)
    register_id: uuid.UUID | None = None  # con una sola sucursal y por día: la caja de ese día


class BranchTotals(Totals):
    branch_id: uuid.UUID
    branch_name: str


class BalanceOut(BaseModel):
    period: Literal["week", "month", "year"]
    start: date
    end: date
    scope: Literal["branch", "clinic"]
    branch_name: str | None
    totals: Totals
    rows: list[BalanceRow]
    by_branch: list[BranchTotals]  # solo con "todas las sucursales"


# ---------- Ayudas ----------


def _branch(db: Session, user: CurrentUser, branch: str | None) -> Branch:
    """Sucursal con la que se trabaja: Recepción, la suya; Administración, la que elija."""
    if branch == "all":
        raise HTTPException(422, detail="Elegí una sucursal.")
    scope = report_scope(db, user, branch)
    return db.get(Branch, scope.branch_id)


def _get_register(db: Session, user: CurrentUser, register_id: uuid.UUID, *, lock: bool = False) -> CashRegister:
    query = select(CashRegister).where(CashRegister.clinic_id == user.clinic_id, CashRegister.id == register_id)
    if not user.is_admin:
        query = query.where(CashRegister.branch_id == user.branch_id)
    if lock:
        query = query.with_for_update()
    register = db.scalar(query)
    if register is None:
        raise NOT_FOUND
    return register


def _sums(db: Session, clinic_id: uuid.UUID, register_ids: list[uuid.UUID]) -> dict[uuid.UUID, tuple[Decimal, Decimal]]:
    """Entradas y salidas (sin anuladas) de cada caja."""
    result = {rid: (ZERO, ZERO) for rid in register_ids}
    if not register_ids:
        return result
    rows = db.execute(
        select(CashMovement.register_id, CashMovement.kind, func.sum(CashMovement.amount))
        .where(CashMovement.clinic_id == clinic_id, CashMovement.register_id.in_(register_ids),
               CashMovement.voided_at.is_(None))
        .group_by(CashMovement.register_id, CashMovement.kind)
    ).all()
    for rid, kind, total in rows:
        income, expense = result[rid]
        if kind == CashMovementKind.income.value:
            income = total
        else:
            expense = total
        result[rid] = (income, expense)
    return result


def _names(db: Session, clinic_id: uuid.UUID) -> dict[uuid.UUID, str]:
    return dict(db.execute(select(User.id, User.full_name).where(User.clinic_id == clinic_id)).all())


def _branch_names(db: Session, clinic_id: uuid.UUID) -> dict[uuid.UUID, str]:
    return dict(db.execute(select(Branch.id, Branch.name).where(Branch.clinic_id == clinic_id)).all())


def _out(db: Session, registers: list[CashRegister], *, with_movements: bool = False) -> list[RegisterOut]:
    if not registers:
        return []
    clinic_id = registers[0].clinic_id
    names = _names(db, clinic_id)
    branches = _branch_names(db, clinic_id)
    sums = _sums(db, clinic_id, [r.id for r in registers])
    movements: dict[uuid.UUID, list[MovementOut]] = {r.id: [] for r in registers}
    if with_movements:
        for m in db.scalars(select(CashMovement).where(
                CashMovement.clinic_id == clinic_id, CashMovement.register_id.in_(list(movements)))
                .order_by(CashMovement.created_at)):
            movements[m.register_id].append(MovementOut(
                id=m.id, kind=m.kind, amount=float(m.amount), concept=m.concept,
                created_by_name=names.get(m.created_by, "—"), created_at=m.created_at,
                voided_at=m.voided_at, voided_by_name=names.get(m.voided_by) if m.voided_by else None,
                void_reason=m.void_reason))
    result = []
    for r in registers:
        income, expense = sums[r.id]
        closed = r.closed_at is not None
        expected = r.expected_amount if closed else r.opening_amount + income - expense
        result.append(RegisterOut(
            id=r.id, branch_id=r.branch_id, branch_name=branches.get(r.branch_id, "—"),
            business_date=r.business_date, status="closed" if closed else "open",
            opening_amount=float(r.opening_amount), income=float(income), expense=float(expense),
            expected_amount=float(expected),
            counted_amount=float(r.counted_amount) if closed else None,
            difference=float(r.counted_amount - r.expected_amount) if closed else None,
            closing_note=r.closing_note, opened_by_name=names.get(r.opened_by, "—"), opened_at=r.opened_at,
            closed_by_name=names.get(r.closed_by) if r.closed_by else None, closed_at=r.closed_at,
            reopen_count=r.reopen_count,
            movements=movements[r.id] if with_movements else None,
        ))
    return result


def _require_open(register: CashRegister) -> None:
    if register.closed_at is not None:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            detail="Esta caja ya está cerrada. Solo Administración puede reabrirla.")


def _fmt(d: date) -> str:
    return d.strftime("%d/%m/%Y")


# ---------- Rutas ----------


@router.get("/today", response_model=TodayOut)
def today(branch: str | None = None, user: CurrentUser = Depends(staff_only), db: Session = Depends(get_db)):
    """Estado de la caja de hoy en la sucursal (y cajas de días anteriores sin cerrar)."""
    br = _branch(db, user, branch)
    day = clinic_today(db, user.clinic_id)
    current = db.scalar(select(CashRegister).where(
        CashRegister.clinic_id == user.clinic_id, CashRegister.branch_id == br.id,
        CashRegister.business_date == day))
    pending = db.scalars(select(CashRegister).where(
        CashRegister.clinic_id == user.clinic_id, CashRegister.branch_id == br.id,
        CashRegister.business_date < day, CashRegister.closed_at.is_(None))
        .order_by(CashRegister.business_date)).all()
    last_closed = db.scalar(select(CashRegister.counted_amount).where(
        CashRegister.clinic_id == user.clinic_id, CashRegister.branch_id == br.id,
        CashRegister.business_date < day, CashRegister.closed_at.is_not(None))
        .order_by(CashRegister.business_date.desc()).limit(1))
    return TodayOut(
        today=day, branch_id=br.id, branch_name=br.name,
        current=_out(db, [current], with_movements=True)[0] if current else None,
        pending=_out(db, list(pending)),
        suggested_opening=float(last_closed) if last_closed is not None else None,
    )


@router.post("/registers", response_model=RegisterOut, status_code=status.HTTP_201_CREATED)
def open_register(payload: OpenIn, request: Request, user: CurrentUser = Depends(staff_only),
                  db: Session = Depends(get_db)):
    """Abrir la caja de HOY con el efectivo contado al empezar."""
    br = _branch(db, user, str(payload.branch_id) if payload.branch_id else None)
    if not br.is_active:
        raise HTTPException(409, detail="Esa sucursal está desactivada.")
    day = clinic_today(db, user.clinic_id)
    existing = db.scalar(select(CashRegister).where(
        CashRegister.clinic_id == user.clinic_id, CashRegister.branch_id == br.id,
        CashRegister.business_date == day))
    if existing is not None:
        raise HTTPException(409, detail="La caja de hoy ya está abierta." if existing.closed_at is None else
                            "La caja de hoy ya se cerró. Si hay que corregirla, Administración puede reabrirla.")
    pending = db.scalar(select(CashRegister.business_date).where(
        CashRegister.clinic_id == user.clinic_id, CashRegister.branch_id == br.id,
        CashRegister.business_date < day, CashRegister.closed_at.is_(None))
        .order_by(CashRegister.business_date).limit(1))
    if pending is not None:
        raise HTTPException(409, detail=f"Primero cerrá la caja del {_fmt(pending)}, que quedó abierta.")
    register = CashRegister(clinic_id=user.clinic_id, branch_id=br.id, business_date=day,
                            opening_amount=payload.opening_amount, opened_by=user.id)
    db.add(register)
    try:
        db.flush()
    except IntegrityError:  # dos personas abrieron a la vez
        db.rollback()
        raise HTTPException(409, detail="La caja de hoy ya está abierta.") from None
    audit.record(db, clinic_id=user.clinic_id, actor_id=user.id, action="cash.open",
                 entity_type="cash_register", entity_id=register.id, request=request)
    db.commit()
    return _out(db, [register], with_movements=True)[0]


@router.get("/registers/{register_id}", response_model=RegisterOut)
def get_register(register_id: uuid.UUID, user: CurrentUser = Depends(staff_only), db: Session = Depends(get_db)):
    return _out(db, [_get_register(db, user, register_id)], with_movements=True)[0]


@router.post("/registers/{register_id}/movements", response_model=RegisterOut, status_code=status.HTTP_201_CREATED)
def add_movement(register_id: uuid.UUID, payload: MovementIn, request: Request,
                 user: CurrentUser = Depends(staff_only), db: Session = Depends(get_db)):
    register = _get_register(db, user, register_id, lock=True)
    _require_open(register)
    movement = CashMovement(clinic_id=user.clinic_id, register_id=register.id, kind=payload.kind.value,
                            amount=payload.amount, concept=payload.concept, created_by=user.id)
    db.add(movement)
    db.flush()
    audit.record(db, clinic_id=user.clinic_id, actor_id=user.id, action="cash.movement",
                 entity_type="cash_register", entity_id=register.id, details={"kind": payload.kind.value},
                 request=request)
    db.commit()
    return _out(db, [register], with_movements=True)[0]


@router.post("/registers/{register_id}/movements/{movement_id}/void", response_model=RegisterOut)
def void_movement(register_id: uuid.UUID, movement_id: uuid.UUID, payload: VoidIn, request: Request,
                  user: CurrentUser = Depends(staff_only), db: Session = Depends(get_db)):
    """Anular un movimiento equivocado (no se borra; deja de contar)."""
    register = _get_register(db, user, register_id, lock=True)
    _require_open(register)
    movement = db.scalar(select(CashMovement).where(
        CashMovement.clinic_id == user.clinic_id, CashMovement.register_id == register.id,
        CashMovement.id == movement_id))
    if movement is None:
        raise HTTPException(404, detail="El movimiento no existe.")
    if movement.voided_at is not None:
        raise HTTPException(409, detail="Ese movimiento ya estaba anulado.")
    movement.voided_at = utcnow()
    movement.voided_by = user.id
    movement.void_reason = payload.reason
    audit.record(db, clinic_id=user.clinic_id, actor_id=user.id, action="cash.void",
                 entity_type="cash_register", entity_id=register.id, details={"kind": movement.kind},
                 request=request)
    db.commit()
    return _out(db, [register], with_movements=True)[0]


@router.post("/registers/{register_id}/close", response_model=RegisterOut)
def close_register(register_id: uuid.UUID, payload: CloseIn, request: Request,
                   user: CurrentUser = Depends(staff_only), db: Session = Depends(get_db)):
    """Cierre de caja: se ingresa lo contado y se guarda la diferencia con lo esperado."""
    register = _get_register(db, user, register_id, lock=True)
    _require_open(register)
    income, expense = _sums(db, user.clinic_id, [register.id])[register.id]
    expected = register.opening_amount + income - expense
    note = (payload.note or "").strip() or None
    if payload.counted_amount != expected and not note:
        raise HTTPException(422, detail="Lo contado no coincide con lo esperado: escribí el motivo de la "
                                        "diferencia.")
    register.counted_amount = payload.counted_amount
    register.expected_amount = expected
    register.closing_note = note
    register.closed_by = user.id
    register.closed_at = utcnow()
    audit.record(db, clinic_id=user.clinic_id, actor_id=user.id, action="cash.close",
                 entity_type="cash_register", entity_id=register.id, request=request)
    db.commit()
    return _out(db, [register], with_movements=True)[0]


@router.post("/registers/{register_id}/reopen", response_model=RegisterOut)
def reopen_register(register_id: uuid.UUID, request: Request, user: CurrentUser = Depends(admin_only),
                    db: Session = Depends(get_db)):
    """Solo Administración: reabrir una caja cerrada para corregirla."""
    register = _get_register(db, user, register_id, lock=True)
    if register.closed_at is None:
        raise HTTPException(409, detail="Esta caja ya está abierta.")
    register.counted_amount = None
    register.expected_amount = None
    register.closing_note = None
    register.closed_by = None
    register.closed_at = None
    register.reopen_count += 1
    audit.record(db, clinic_id=user.clinic_id, actor_id=user.id, action="cash.reopen",
                 entity_type="cash_register", entity_id=register.id, details={"count": register.reopen_count},
                 request=request)
    db.commit()
    return _out(db, [register], with_movements=True)[0]


def _period(period: str, ref: date) -> tuple[date, date]:
    if period == "week":
        start = ref - timedelta(days=ref.weekday())  # lunes
        return start, start + timedelta(days=6)
    if period == "month":
        start = ref.replace(day=1)
        nxt = (start + timedelta(days=32)).replace(day=1)
        return start, nxt - timedelta(days=1)
    return date(ref.year, 1, 1), date(ref.year, 12, 31)


class _Acc:
    """Suma en pesos exactos (Decimal); se convierte a número recién al responder."""

    def __init__(self) -> None:
        self.income = ZERO
        self.expense = ZERO
        self.difference = ZERO
        self.registers = 0
        self.open_registers = 0

    def add(self, income: Decimal, expense: Decimal, register: CashRegister) -> None:
        self.income += income
        self.expense += expense
        self.registers += 1
        if register.closed_at is None:
            self.open_registers += 1
        else:
            self.difference += register.counted_amount - register.expected_amount

    def values(self) -> dict:
        return {"income": float(self.income), "expense": float(self.expense),
                "net": float(self.income - self.expense), "difference": float(self.difference),
                "registers": self.registers, "open_registers": self.open_registers}


@router.get("/balance", response_model=BalanceOut)
def balance(period: Literal["week", "month", "year"] = "month",
            ref: date | None = Query(None, alias="date"),
            branch: str | None = None,
            user: CurrentUser = Depends(staff_only), db: Session = Depends(get_db)):
    """Balance de la semana (lunes a domingo), el mes o el año que contiene la fecha indicada."""
    scope = report_scope(db, user, branch)
    start, end = _period(period, ref or clinic_today(db, user.clinic_id))
    query = select(CashRegister).where(CashRegister.clinic_id == user.clinic_id,
                                       CashRegister.business_date.between(start, end))
    if scope.branch_id is not None:
        query = query.where(CashRegister.branch_id == scope.branch_id)
    registers = list(db.scalars(query.order_by(CashRegister.business_date)).all())
    sums = _sums(db, user.clinic_id, [r.id for r in registers])

    # Filas: un día (semana y mes) o un mes (año), todas aunque no haya caja.
    if period == "year":
        keys = [f"{start.year}-{m:02d}" for m in range(1, 13)]
    else:
        keys = [(start + timedelta(days=i)).isoformat() for i in range((end - start).days + 1)]
    rows = {k: _Acc() for k in keys}
    row_register: dict[str, uuid.UUID] = {}
    total = _Acc()
    branches: dict[uuid.UUID, _Acc] = {}
    names = _branch_names(db, user.clinic_id)
    for r in registers:
        income, expense = sums[r.id]
        key = r.business_date.isoformat()[:7] if period == "year" else r.business_date.isoformat()
        rows[key].add(income, expense, r)
        total.add(income, expense, r)
        if scope.branch_id is not None and period != "year":
            row_register[key] = r.id
        if scope.branch_id is None:
            branches.setdefault(r.branch_id, _Acc()).add(income, expense, r)
    by_branch = [BranchTotals(branch_id=bid, branch_name=names.get(bid, "—"), **acc.values())
                 for bid, acc in branches.items()]
    return BalanceOut(
        period=period, start=start, end=end, scope="branch" if scope.branch_id else "clinic",
        branch_name=scope.branch_name, totals=Totals(**total.values()),
        rows=[BalanceRow(key=k, register_id=row_register.get(k), **acc.values()) for k, acc in rows.items()],
        by_branch=sorted(by_branch, key=lambda b: b.branch_name.lower()),
    )
