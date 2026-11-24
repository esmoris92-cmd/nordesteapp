"""/sistema muestra, de cada clínica, los pacientes en pausa y cuántos de ellos tuvieron algún turno
realizado en el mes corriente (el contrato cobra por pacientes activos). Datos ficticios."""

from datetime import datetime, timedelta, timezone

from app.models import Appointment, Patient
from tests.test_dueno_sistema import _ready_owner


def _appointment(db, w, patient, professional, branch, starts_at, status="completed"):
    db.add(Appointment(clinic_id=patient.clinic_id, patient_id=patient.id, professional_id=professional.id,
                       branch_id=branch.id, starts_at=starts_at, ends_at=starts_at + timedelta(minutes=45),
                       status=status, created_by=professional.id))


def test_paused_patients_and_those_seen_this_month(world, db, capsys):
    w = world
    now = datetime.now(timezone.utc)
    last_month = now.replace(day=1) - timedelta(days=3)
    w.patient_a.status = "paused"  # en pausa, pero con un turno realizado este mes (dos veces)
    quiet = Patient(clinic_id=w.clinic_a.id, first_name="Sin", last_name="Turnos", affiliation="private",
                    status="paused", created_by=w.reception_a.id, branch_id=w.branch_a.id)
    old = Patient(clinic_id=w.clinic_a.id, first_name="Mes", last_name="Pasado", affiliation="private",
                  status="paused", created_by=w.reception_a.id, branch_id=w.branch_a.id)
    planned = Patient(clinic_id=w.clinic_a.id, first_name="Solo", last_name="Programado", affiliation="private",
                      status="paused", created_by=w.reception_a.id, branch_id=w.branch_a.id)
    active = Patient(clinic_id=w.clinic_a.id, first_name="Activo", last_name="Prueba", affiliation="private",
                     status="active", created_by=w.reception_a.id, branch_id=w.branch_a.id)
    db.add_all([quiet, old, planned, active])
    db.flush()
    _appointment(db, w, w.patient_a, w.lucia, w.branch_a, now - timedelta(minutes=1))
    _appointment(db, w, w.patient_a, w.lucia, w.branch_a, now - timedelta(minutes=50))
    _appointment(db, w, old, w.lucia, w.branch_a, last_month)  # realizado, pero el mes pasado
    _appointment(db, w, planned, w.lucia, w.branch_a, now, status="scheduled")  # todavía no realizado
    _appointment(db, w, active, w.lucia, w.branch_a, now)  # activo: no cuenta como "en pausa"
    w.patient_b.status = "paused"  # la clínica B tiene lo suyo, aparte
    _appointment(db, w, w.patient_b, w.bruno, w.branch_b, now)
    db.commit()

    owner, _ = _ready_owner(db, capsys)
    clinics = {c["name"]: c for c in owner.get("/api/owner/clinics").json()}
    a, b = clinics[w.clinic_a.name], clinics[w.clinic_b.name]
    assert (a["active_patients"], a["paused_patients"], a["paused_with_sessions"]) == (1, 4, 1)
    assert (b["active_patients"], b["paused_patients"], b["paused_with_sessions"]) == (0, 1, 1)
    summary = owner.get(f"/api/owner/clinics/{w.clinic_a.id}/dashboard").json()["clinic"]
    assert summary["paused_patients"] == 4 and summary["paused_with_sessions"] == 1
