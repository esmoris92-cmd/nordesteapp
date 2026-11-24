"""Agenda: disponibilidad, superposición, cancelación y reprogramación."""

import uuid
from datetime import date, timedelta
from tests.conftest import workday

# Fechas futuras fijas en hora de Montevideo (UTC-3). La disponibilidad de prueba es 08-20 h.
DAY = workday().isoformat()


def _slot(hour: int, minutes: int = 50):
    end_h, end_m = divmod(hour * 60 + minutes, 60)
    return {"starts_at": f"{DAY}T{hour:02d}:00:00-03:00",
            "ends_at": f"{DAY}T{end_h:02d}:{end_m:02d}:00-03:00"}


def _book(client, world, hour, professional=None, patient=None):
    return client.post("/api/appointments", json={
        "patient_id": str((patient or world.patient_a).id),
        "professional_id": str((professional or world.lucia).id), **_slot(hour)})


def _move_to_past(db, appointment_id):
    """Corre el turno a ayer (directo en la base) para poder marcar su resultado."""
    from app.models import Appointment
    appt = db.get(Appointment, uuid.UUID(appointment_id))
    appt.starts_at -= timedelta(days=8)
    appt.ends_at -= timedelta(days=8)
    db.commit()


def _same_instant(a: str, b: str) -> bool:
    """Misma fecha y hora aunque una venga en UTC ("Z") y la otra en hora de Montevideo."""
    from datetime import datetime
    return datetime.fromisoformat(a) == datetime.fromisoformat(b)


def _range():
    return {"from": f"{DAY}T00:00:00-03:00", "to": f"{DAY}T23:59:00-03:00"}


def test_book_cancel_and_reschedule(world, login, db):
    rec = login(world.reception_a)
    r = _book(rec, world, 10)
    assert r.status_code == 201, r.text
    appt = r.json()
    assert appt["patient_name"] == "Ana Prueba" and appt["status"] == "scheduled"

    assert _book(rec, world, 10).status_code == 409  # superposición

    # Reprogramar exige el motivo.
    r = rec.post(f"/api/appointments/{appt['id']}/reschedule", json=_slot(12))
    assert r.status_code == 422
    r = rec.post(f"/api/appointments/{appt['id']}/reschedule", json={**_slot(12), "reason": "  "})
    assert r.status_code == 422
    r = rec.post(f"/api/appointments/{appt['id']}/reschedule",
                 json={**_slot(12), "reason": "La paciente pidió cambiar el horario"})
    assert r.status_code == 201, r.text
    new = r.json()
    listed = {a["id"]: a for a in rec.get("/api/appointments", params=_range()).json()}
    assert listed[appt["id"]]["status"] == "rescheduled"
    assert listed[appt["id"]]["rescheduled_to_id"] == new["id"]
    assert listed[appt["id"]]["reschedule_reason"] == "La paciente pidió cambiar el horario"
    assert _same_instant(listed[appt["id"]]["rescheduled_to_starts_at"], new["starts_at"])

    r = rec.post(f"/api/appointments/{new['id']}/cancel", json={"reason": "Pedido del paciente"})
    assert r.status_code == 200 and r.json()["status"] == "cancelled"
    # Una vez cancelado, el horario vuelve a estar libre.
    assert _book(rec, world, 12).status_code == 201


def test_outside_availability_is_rejected(world, login):
    r = _book(login(world.reception_a), world, 21)
    assert r.status_code == 409
    assert "disponibilidad" in r.json()["detail"]


def test_professional_needs_patient_assignment(world, login):
    r = _book(login(world.reception_a), world, 10, professional=world.mateo)
    assert r.status_code == 409


def test_professional_only_sees_own_agenda(world, login):
    rec = login(world.reception_a)
    _book(rec, world, 10)
    mateo = login(world.mateo)
    assert mateo.get("/api/appointments", params=_range()).json() == []
    r = mateo.get("/api/appointments", params={**_range(), "professional_id": str(world.lucia.id)})
    assert r.status_code == 403
    lucia = login(world.lucia)
    assert len(lucia.get("/api/appointments", params=_range()).json()) == 1


def test_professional_sees_everyones_day_but_only_manages_own(world, login):
    """«Día (todos)» y «Horas libres»: con all_professionals, el profesional ve los turnos de todos
    en su sucursal activa (con el nombre del paciente), pero no puede modificar los ajenos."""
    rec = login(world.reception_a)
    appt = _book(rec, world, 10).json()  # turno de Lucía
    mateo = login(world.mateo)
    assert mateo.get("/api/appointments", params=_range()).json() == []  # sin la opción: solo lo suyo
    seen = mateo.get("/api/appointments", params={**_range(), "all_professionals": "true"}).json()
    assert [(a["id"], a["patient_name"]) for a in seen] == [(appt["id"], "Ana Prueba")]
    # Pedir la agenda de otro profesional en particular sigue sin estar permitido.
    r = mateo.get("/api/appointments", params={**_range(), "professional_id": str(world.lucia.id),
                                               "all_professionals": "true"})
    assert r.status_code == 403
    # Ver no es modificar: no puede cancelar, reprogramar ni dar turnos (desde el 24/11/2026 los
    # turnos los dan solo Recepción y Administración).
    assert mateo.post(f"/api/appointments/{appt['id']}/cancel",
                      json={"reason": "Pedido del paciente"}).status_code == 403
    assert _book(mateo, world, 12).status_code == 403


def test_only_staff_schedules(world, login):
    """Dar, reprogramar y cancelar turnos: solo Recepción y Administración. El profesional del
    turno no puede, pero sí marcarlo como realizado o ausente."""
    lucia = login(world.lucia)
    r = _book(lucia, world, 10)
    assert r.status_code == 403 and "Recepción y Administración" in r.json()["detail"]
    appt = _book(login(world.admin_a), world, 10)
    assert appt.status_code == 201, appt.text
    appt = appt.json()
    move = {**_slot(12), "reason": "Pedido de la familia"}
    assert lucia.post(f"/api/appointments/{appt['id']}/reschedule", json=move).status_code == 403
    assert lucia.post(f"/api/appointments/{appt['id']}/cancel", json={"reason": "Pedido"}).status_code == 403
    rec = login(world.reception_a)
    assert rec.post(f"/api/appointments/{appt['id']}/reschedule", json=move).status_code == 201


def test_professional_marks_outcome(world, login, db):
    rec = login(world.reception_a)
    appt = _book(rec, world, 9).json()
    lucia = login(world.lucia)
    # Un turno futuro todavía no se puede marcar como realizado ni ausente.
    r = lucia.post(f"/api/appointments/{appt['id']}/status", json={"status": "completed"})
    assert r.status_code == 409 and "todavía no empezó" in r.json()["detail"]
    _move_to_past(db, appt["id"])
    r = lucia.post(f"/api/appointments/{appt['id']}/status", json={"status": "completed"})
    assert r.status_code == 200 and r.json()["status"] == "completed"
    r = login(world.mateo).post(f"/api/appointments/{appt['id']}/status", json={"status": "no_show"})
    assert r.status_code == 404


def test_availability_management(world, login):
    # Desde el 24/11/2026 el profesional ve sus horarios pero no los cambia (ni los suyos).
    lucia = login(world.lucia)
    assert len(lucia.get("/api/availability", params={"professional_id": str(world.lucia.id)}).json()) > 0
    r = lucia.post("/api/availability", json={"professional_id": str(world.lucia.id),
                                              "weekday": 0, "start_time": "06:00",
                                              "end_time": "07:00"})
    assert r.status_code == 403
    own = lucia.get("/api/availability", params={"professional_id": str(world.lucia.id)}).json()[0]
    assert lucia.delete(f"/api/availability/{own['id']}").status_code == 403
    r = login(world.admin_a).post("/api/availability", json={"professional_id": str(world.lucia.id),
                                                             "weekday": 0, "start_time": "07:00",
                                                             "end_time": "09:00"})
    assert r.status_code == 409  # se superpone con 08-20
    r = login(world.reception_a).post("/api/availability", json={
        "professional_id": str(world.mateo.id), "weekday": 0, "start_time": "06:00",
        "end_time": "07:00"})
    assert r.status_code == 201
    assert login(world.reception_a).delete(f"/api/availability/{r.json()['id']}").status_code == 204


def test_inactive_patient_cannot_be_booked(world, login):
    rec = login(world.reception_a)
    rec.patch(f"/api/patients/{world.patient_a.id}", json={"status": "discharged"})
    assert _book(rec, world, 10).status_code == 409


def test_naive_datetimes_rejected(world, login):
    r = login(world.reception_a).post("/api/appointments", json={
        "patient_id": str(world.patient_a.id), "professional_id": str(world.lucia.id),
        "starts_at": f"{DAY}T10:00:00", "ends_at": f"{DAY}T10:50:00"})
    assert r.status_code == 422


def test_patient_reschedule_history_with_reason_author_and_date(world, login, db):
    """La pestaña Turnos del paciente muestra cada reprogramación: de cuándo a cuándo, el
    motivo, quién la hizo y cuándo."""
    rec = login(world.reception_a)
    first = _book(rec, world, 9).json()
    second = rec.post(f"/api/appointments/{first['id']}/reschedule",
                      json={**_slot(11), "reason": "Feriado en la escuela"}).json()
    rec.post(f"/api/appointments/{second['id']}/reschedule",
             json={**_slot(15), "reason": "Coincide con otra terapia"})

    url = f"/api/patients/{world.patient_a.id}/reschedules"
    history = rec.get(url).json()
    assert [h["reason"] for h in history] == ["Coincide con otra terapia", "Feriado en la escuela"]
    last = history[0]
    assert _same_instant(last["from_starts_at"], second["starts_at"]) and last["to_status"] == "scheduled"
    assert last["rescheduled_by"] == "Recepcion" and last["rescheduled_at"] is not None
    assert last["professional_name"] == "Lucia" and last["to_professional_name"] is None

    # La profesional del paciente lo ve; otra profesional sin acceso, no; otra clínica, tampoco.
    assert len(login(world.lucia).get(url).json()) == 2
    assert login(world.mateo).get(url).status_code == 404
    assert login(world.admin_b).get(url).status_code == 404
    other = login(world.reception_a).get(f"/api/patients/{world.patient_b.id}/reschedules")
    assert other.status_code == 404


def test_no_show_reason_is_optional_and_shown_in_patient_history(world, login, db):
    """Al marcar ausente se puede escribir por qué no vino; queda en el turno y en el
    historial de ausencias del paciente, con quién lo marcó y cuándo."""
    rec = login(world.reception_a)
    lucia = login(world.lucia)
    with_reason = _book(rec, world, 9).json()
    without = _book(rec, world, 11).json()
    done = _book(rec, world, 14).json()
    for a in (with_reason, without, done):
        _move_to_past(db, a["id"])

    # El motivo es solo para ausencias.
    r = lucia.post(f"/api/appointments/{done['id']}/status", json={"status": "completed", "reason": "Vino"})
    assert r.status_code == 422
    r = lucia.post(f"/api/appointments/{with_reason['id']}/status",
                   json={"status": "no_show", "reason": "  Estaba enfermo, avisó la madre  "})
    assert r.status_code == 200, r.text
    assert r.json()["no_show_reason"] == "Estaba enfermo, avisó la madre"
    r = rec.post(f"/api/appointments/{without['id']}/status", json={"status": "no_show", "reason": ""})
    assert r.status_code == 200 and r.json()["no_show_reason"] is None

    url = f"/api/patients/{world.patient_a.id}/absences"
    history = rec.get(url).json()
    assert [h["reason"] for h in history] == [None, "Estaba enfermo, avisó la madre"]  # más reciente primero
    assert history[1]["marked_by"] == "Lucia" and history[1]["marked_at"] is not None
    assert history[0]["marked_by"] == "Recepcion" and history[1]["professional_name"] == "Lucia"
    assert history[0]["branch_name"] == "Central"

    # La profesional del paciente lo ve; otra sin acceso, no; otra clínica, tampoco.
    assert len(lucia.get(url).json()) == 2
    assert login(world.mateo).get(url).status_code == 404
    assert login(world.admin_b).get(url).status_code == 404
