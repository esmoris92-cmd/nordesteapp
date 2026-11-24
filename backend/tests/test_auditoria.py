"""Pantalla de auditoría: filtros, "Cargar más", nombre del paciente y textos (todo ficticio)."""

import re
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from app.models import AuditEvent

MVD = ZoneInfo("America/Montevideo")
ROOT = Path(__file__).resolve().parents[2]


def _event(db, world, action, actor, patient=None, when=None, **kw):
    e = AuditEvent(clinic_id=world.clinic_a.id, actor_id=actor.id, action=action,
                   patient_id=patient.id if patient else None, details={}, **kw)
    if when:
        e.created_at = when
    db.add(e)
    db.flush()
    return e


def test_filters_patient_name_and_paging(world, login, db):
    admin = login(world.admin_a)
    now = datetime.now(MVD)
    old = now - timedelta(days=10)
    _event(db, world, "patient.view", world.lucia, world.patient_a, when=old)
    _event(db, world, "patient.view", world.reception_a, world.patient_a, when=now)
    _event(db, world, "note.create", world.lucia, world.patient_a, when=now)
    db.commit()
    rows = admin.get("/api/audit", params={"action": "patient.view"}).json()
    assert [r["actor_name"] for r in rows] == [world.reception_a.full_name, world.lucia.full_name]
    assert rows[0]["patient_name"] == "Prueba, Ana"
    # Por persona y acción.
    rows = admin.get("/api/audit", params={"actor_id": str(world.lucia.id), "action": "patient.view"}).json()
    assert len(rows) == 1
    # Por fechas (días de la clínica).
    today = now.date().isoformat()
    rows = admin.get("/api/audit", params={"action": "patient.view", "date_from": today, "date_to": today}).json()
    assert [r["actor_name"] for r in rows] == [world.reception_a.full_name]
    day = old.date().isoformat()
    rows = admin.get("/api/audit", params={"action": "patient.view", "date_to": day}).json()
    assert [r["actor_name"] for r in rows] == [world.lucia.full_name]
    assert admin.get("/api/audit", params={"date_from": today, "date_to": day}).status_code == 422
    # Por paciente.
    rows = admin.get("/api/audit", params={"patient_id": str(world.patient_a.id)}).json()
    assert len(rows) == 3
    # "Cargar más": de a uno, sin repetir.
    first = admin.get("/api/audit", params={"patient_id": str(world.patient_a.id), "limit": 2}).json()
    rest = admin.get("/api/audit", params={"patient_id": str(world.patient_a.id), "limit": 2,
                                           "before_id": first[-1]["id"]}).json()
    assert len(first) == 2 and len(rest) == 1 and rest[0]["id"] < first[-1]["id"]
    # Personas para el filtro: solo de la propia clínica; solo administración.
    people = {p["full_name"] for p in admin.get("/api/audit/people").json()}
    assert world.lucia.full_name in people and world.bruno.full_name not in people
    assert login(world.reception_a).get("/api/audit/people").status_code == 403


def test_every_audit_action_has_a_label():
    """Toda acción que se registra tiene su texto en la pantalla (labels.ts)."""
    actions = set()
    for path in (ROOT / "backend" / "app").rglob("*.py"):
        actions |= set(re.findall(r'action="([a-z_]+\.[a-z_]+)"', path.read_text(encoding="utf-8")))
    labels = (ROOT / "frontend" / "src" / "labels.ts").read_text(encoding="utf-8")
    missing = sorted(a for a in actions if f'"{a}":' not in labels)
    assert missing == []
