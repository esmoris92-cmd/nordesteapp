"""Caja diaria por sucursal: apertura, movimientos, cierre, reapertura y balances (todo ficticio)."""

from datetime import timedelta
from decimal import Decimal

from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from app.clinic_time import clinic_today
from app.models import AuditEvent, Branch, CashMovement, CashRegister, UserBranch


def _pando(db, world):
    pando = Branch(clinic_id=world.clinic_a.id, name="Pando")
    db.add(pando)
    db.commit()
    return pando


def _admin(login, world):
    """Administración con más de una sucursal tiene que elegir una al entrar (Central)."""
    admin = login(world.admin_a)
    admin.post("/api/auth/branch", json={"branch_id": str(world.branch_a.id)})
    return admin


def _old_register(db, world, branch, days_ago, opening="1000", closed=False, counted="1000"):
    """Caja de un día anterior cargada directamente en la base."""
    day = clinic_today(db, world.clinic_a.id) - timedelta(days=days_ago)
    reg = CashRegister(clinic_id=world.clinic_a.id, branch_id=branch.id, business_date=day,
                       opening_amount=Decimal(opening), opened_by=world.reception_a.id)
    if closed:
        reg.counted_amount = Decimal(counted)
        reg.expected_amount = Decimal(opening)
        reg.closed_by = world.reception_a.id
        from app.deps import utcnow
        reg.closed_at = utcnow()
    db.add(reg)
    db.commit()
    return reg


def test_full_day(world, login, db):
    rec = login(world.reception_a)
    t = rec.get("/api/cash/today").json()
    assert t["current"] is None and t["pending"] == [] and t["branch_name"] == "Central"
    assert t["suggested_opening"] is None

    r = rec.post("/api/cash/registers", json={"opening_amount": "2000"})
    assert r.status_code == 201, r.text
    reg = r.json()
    assert reg["status"] == "open" and reg["opening_amount"] == 2000 and reg["movements"] == []
    # No se abre dos veces el mismo día.
    assert rec.post("/api/cash/registers", json={"opening_amount": 0}).status_code == 409

    url = f"/api/cash/registers/{reg['id']}"
    r = rec.post(f"{url}/movements", json={"kind": "income", "amount": "1500,50", "concept": " Sesión particular "})
    assert r.status_code == 201, r.text
    assert r.json()["movements"][0]["concept"] == "Sesión particular"
    rec.post(f"{url}/movements", json={"kind": "income", "amount": 800, "concept": "Sesión particular"})
    r = rec.post(f"{url}/movements", json={"kind": "expense", "amount": 300.25, "concept": "Artículos de limpieza"})
    reg = r.json()
    assert (reg["income"], reg["expense"], reg["expected_amount"]) == (2300.5, 300.25, 4000.25)

    # Anular un movimiento equivocado: deja de contar, pero queda a la vista.
    wrong = reg["movements"][1]["id"]
    assert rec.post(f"{url}/movements/{wrong}/void", json={"reason": ""}).status_code == 422
    r = rec.post(f"{url}/movements/{wrong}/void", json={"reason": "Cargado dos veces"})
    assert r.status_code == 200, r.text
    reg = r.json()
    assert reg["income"] == 1500.5 and reg["expected_amount"] == 3200.25
    assert reg["movements"][1]["voided_at"] and reg["movements"][1]["void_reason"] == "Cargado dos veces"
    assert rec.post(f"{url}/movements/{wrong}/void", json={"reason": "otra vez"}).status_code == 409

    # Cierre con diferencia: hay que explicar el motivo.
    r = rec.post(f"{url}/close", json={"counted_amount": "3200"})
    assert r.status_code == 422 and "motivo" in r.json()["detail"]
    r = rec.post(f"{url}/close", json={"counted_amount": "3200", "note": "Faltan 25 centésimos de vuelto"})
    assert r.status_code == 200, r.text
    reg = r.json()
    assert reg["status"] == "closed" and reg["counted_amount"] == 3200 and reg["difference"] == -0.25
    assert reg["closed_by_name"] == world.reception_a.full_name

    # Cerrada: no se cargan ni anulan movimientos, ni se vuelve a cerrar.
    assert rec.post(f"{url}/movements", json={"kind": "income", "amount": 1, "concept": "x"}).status_code == 409
    assert rec.post(f"{url}/close", json={"counted_amount": 0}).status_code == 409
    assert rec.post("/api/cash/registers", json={"opening_amount": 0}).status_code == 409

    actions = [a for a in db.scalars(select(AuditEvent.action).where(AuditEvent.entity_type == "cash_register")
                                     .order_by(AuditEvent.id))]
    assert actions == ["cash.open", "cash.movement", "cash.movement", "cash.movement", "cash.void", "cash.close"]


def test_amount_validation(world, login):
    rec = login(world.reception_a)
    for bad in (-1, "abc", "", "10.555", "1e3x", None):
        assert rec.post("/api/cash/registers", json={"opening_amount": bad}).status_code == 422, bad
    reg = rec.post("/api/cash/registers", json={"opening_amount": 0}).json()
    url = f"/api/cash/registers/{reg['id']}/movements"
    assert rec.post(url, json={"kind": "income", "amount": 0, "concept": "x"}).status_code == 422
    assert rec.post(url, json={"kind": "income", "amount": 10, "concept": "   "}).status_code == 422
    assert rec.post(url, json={"kind": "otra", "amount": 10, "concept": "x"}).status_code == 422
    assert rec.post(url, json={"kind": "income", "amount": "100000000", "concept": "x"}).status_code == 422


def test_close_without_difference_needs_no_note(world, login):
    rec = login(world.reception_a)
    reg = rec.post("/api/cash/registers", json={"opening_amount": "500"}).json()
    r = rec.post(f"/api/cash/registers/{reg['id']}/close", json={"counted_amount": "500.00"})
    assert r.status_code == 200 and r.json()["difference"] == 0 and r.json()["closing_note"] is None


def test_previous_day_must_be_closed_first(world, login, db):
    old = _old_register(db, world, world.branch_a, 1)
    rec = login(world.reception_a)
    t = rec.get("/api/cash/today").json()
    assert [p["id"] for p in t["pending"]] == [str(old.id)]
    r = rec.post("/api/cash/registers", json={"opening_amount": 0})
    assert r.status_code == 409 and "Primero cerrá la caja" in r.json()["detail"]
    # La de ayer todavía admite movimientos y se cierra; después se abre la de hoy, y se sugiere
    # como monto inicial lo contado en ese cierre.
    url = f"/api/cash/registers/{old.id}"
    assert rec.post(f"{url}/movements", json={"kind": "expense", "amount": 100, "concept": "Taxi"}).status_code == 201
    assert rec.post(f"{url}/close", json={"counted_amount": 900}).status_code == 200
    t = rec.get("/api/cash/today").json()
    assert t["pending"] == [] and t["suggested_opening"] == 900
    assert rec.post("/api/cash/registers", json={"opening_amount": 900}).status_code == 201


def test_reception_only_sees_own_branch(world, login, db):
    pando = _pando(db, world)
    other = _old_register(db, world, pando, 2, closed=True)
    rec = login(world.reception_a)
    assert rec.get(f"/api/cash/registers/{other.id}").status_code == 404
    assert rec.post(f"/api/cash/registers/{other.id}/movements",
                    json={"kind": "income", "amount": 1, "concept": "x"}).status_code == 404
    assert rec.get(f"/api/cash/today?branch={pando.id}").status_code == 403
    assert rec.get("/api/cash/balance?branch=all").status_code == 403
    assert rec.get(f"/api/cash/balance?branch={pando.id}").status_code == 403
    assert rec.post("/api/cash/registers", json={"opening_amount": 0, "branch_id": str(pando.id)}).status_code == 403
    # Si le asignan Pando y entra a esa sucursal, ve la caja de Pando (y no la de Central).
    db.add(UserBranch(user_id=world.reception_a.id, branch_id=pando.id, clinic_id=world.clinic_a.id))
    db.commit()
    rec.post("/api/auth/branch", json={"branch_id": str(pando.id)})
    assert rec.get(f"/api/cash/registers/{other.id}").status_code == 200
    assert rec.get("/api/cash/today").json()["branch_name"] == "Pando"


def test_professionals_and_other_clinics_have_no_access(world, login, db):
    reg = _old_register(db, world, world.branch_a, 0)
    lucia = login(world.lucia)
    assert lucia.get("/api/cash/today").status_code == 403
    assert lucia.get("/api/cash/balance").status_code == 403
    admin_b = login(world.admin_b)
    assert admin_b.get(f"/api/cash/registers/{reg.id}").status_code == 404
    assert admin_b.get(f"/api/cash/today?branch={world.branch_a.id}").status_code == 404


def test_admin_any_branch_and_reopen(world, login, db):
    pando = _pando(db, world)
    admin = _admin(login, world)
    rec = login(world.reception_a)
    r = admin.post("/api/cash/registers", json={"opening_amount": 300, "branch_id": str(pando.id)})
    assert r.status_code == 201 and r.json()["branch_name"] == "Pando"
    assert admin.get(f"/api/cash/today?branch={pando.id}").json()["current"]["id"] == r.json()["id"]
    reg = rec.post("/api/cash/registers", json={"opening_amount": 100}).json()
    url = f"/api/cash/registers/{reg['id']}"
    rec.post(f"{url}/close", json={"counted_amount": 100})
    # Recepción no puede reabrir; Administración sí, y queda en la auditoría.
    assert rec.post(f"{url}/reopen").status_code == 403
    r = admin.post(f"{url}/reopen")
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "open" and r.json()["reopen_count"] == 1 and r.json()["counted_amount"] is None
    assert admin.post(f"{url}/reopen").status_code == 409
    assert rec.post(f"{url}/movements", json={"kind": "income", "amount": 50, "concept": "Corrección"}).status_code == 201
    assert rec.post(f"{url}/close", json={"counted_amount": 150}).json()["difference"] == 0
    assert db.scalar(select(AuditEvent.details).where(AuditEvent.action == "cash.reopen")) == {"count": 1}


def test_balance(world, login, db):
    pando = _pando(db, world)
    rec = login(world.reception_a)
    admin = _admin(login, world)
    today = clinic_today(db, world.clinic_a.id)
    reg = rec.post("/api/cash/registers", json={"opening_amount": 1000}).json()
    url = f"/api/cash/registers/{reg['id']}"
    rec.post(f"{url}/movements", json={"kind": "income", "amount": 700, "concept": "Sesión"})
    rec.post(f"{url}/movements", json={"kind": "expense", "amount": 200, "concept": "Agua"})
    rec.post(f"{url}/close", json={"counted_amount": 1450, "note": "Faltante"})
    pr = admin.post("/api/cash/registers", json={"opening_amount": 0, "branch_id": str(pando.id)}).json()
    admin.post(f"/api/cash/registers/{pr['id']}/movements", json={"kind": "income", "amount": 400, "concept": "Sesión"})

    # Recepción: su sucursal, semana de lunes a domingo, una fila por día.
    b = rec.get("/api/cash/balance", params={"period": "week"}).json()
    assert b["scope"] == "branch" and b["branch_name"] == "Central"
    assert b["start"] == (today - timedelta(days=today.weekday())).isoformat() and len(b["rows"]) == 7
    assert b["totals"] == {"income": 700, "expense": 200, "net": 500, "difference": -50,
                           "registers": 1, "open_registers": 0}
    row = next(x for x in b["rows"] if x["key"] == today.isoformat())
    assert row["register_id"] == reg["id"] and row["net"] == 500

    # Mes y año.
    m = rec.get("/api/cash/balance", params={"period": "month", "date": today.isoformat()}).json()
    assert m["start"] == today.replace(day=1).isoformat() and m["totals"]["net"] == 500
    y = rec.get("/api/cash/balance", params={"period": "year"}).json()
    assert len(y["rows"]) == 12 and y["rows"][today.month - 1]["income"] == 700
    assert y["rows"][today.month - 1]["register_id"] is None

    # Administración: todas las sucursales juntas, con el detalle por sucursal.
    a = admin.get("/api/cash/balance", params={"period": "month", "branch": "all"}).json()
    assert a["scope"] == "clinic" and a["totals"]["income"] == 1100 and a["totals"]["open_registers"] == 1
    assert [(x["branch_name"], x["income"]) for x in a["by_branch"]] == [("Central", 700), ("Pando", 400)]
    p = admin.get("/api/cash/balance", params={"period": "month", "branch": str(pando.id)}).json()
    assert p["totals"]["income"] == 400 and p["by_branch"] == []
    assert rec.get("/api/cash/balance", params={"period": "decada"}).status_code == 422


def test_cash_rows_cannot_be_deleted(world, db):
    reg = _old_register(db, world, world.branch_a, 0)
    db.add(CashMovement(clinic_id=world.clinic_a.id, register_id=reg.id, kind="income", amount=Decimal("5"),
                        concept="x", created_by=world.reception_a.id))
    db.commit()
    for table in ("cash_movements", "cash_registers"):
        try:
            db.execute(text(f"DELETE FROM {table}"))
            raise AssertionError(f"Se pudo borrar de {table}")
        except DBAPIError:
            db.rollback()
