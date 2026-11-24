"""Formulario de AYEX del BPS completado con los datos del paciente (todo ficticio)."""

import io
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from pypdf import PdfReader
from sqlalchemy import select

from app.models import Appointment, AuditEvent

MVD = ZoneInfo("America/Montevideo")


def _ayex_patient(client, world):
    r = client.post("/api/patients", json={
        "first_name": "Dánte", "last_name": "Fictício", "affiliation": "ayex",
        "ayex_expires_on": "2027-03-31", "document_number": "1.234.567-2", "phone": "099 123 456",
        "responsible_professional_id": str(world.lucia.id),
        "address_department": "Canelones", "address_locality": "Pando", "address_street": "Calle Falsa",
        "address_number": "123", "address_apartment": "2", "address_solar": "", "address_block": "",
    })
    assert r.status_code == 201, r.text
    return r.json()


def _next_weekday(weekday: int) -> date:
    d = date.today() + timedelta(days=1)
    while d.weekday() != weekday:
        d += timedelta(days=1)
    return d


def _fields(response) -> dict:
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "application/pdf"
    assert "solicitud-ayex-ficticio-dante.pdf" in response.headers["content-disposition"]
    fields = PdfReader(io.BytesIO(response.content)).get_fields()
    return {k: v.get("/V") for k, v in fields.items()}


def test_form_is_filled_with_patient_data(world, login, db):
    rec = login(world.reception_a)
    admin = login(world.admin_a)
    patient = _ayex_patient(rec, world)
    # Domicilio guardado en la ficha.
    detail = rec.get(f"/api/patients/{patient['id']}").json()
    assert detail["address_locality"] == "Pando" and detail["address_solar"] is None
    # Datos de la clínica como proveedor del BPS (solo administración).
    r = admin.patch("/api/clinic", json={"bps_provider_number": "99999", "bps_company_number": "1234",
                                         "phone": "2222 0000", "email": "aurora@ejemplo.test",
                                         "address_street": "Av. Ficticia", "address_locality": "Montevideo",
                                         "transport_included": False, "monthly_budget": "5000"})
    assert r.status_code == 200, r.text
    assert admin.get("/api/clinic").json()["bps_provider_number"] == "99999"
    assert rec.patch("/api/clinic", json={"phone": "1"}).status_code == 403
    # Responsable legal (contacto principal).
    r = rec.post(f"/api/patients/{patient['id']}/guardians", json={
        "first_name": "Laura", "last_name": "Ficticia", "second_last_name": "Gómez",
        "document_number": "2.345.678-3", "relationship": "Madre", "is_primary": True})
    assert r.status_code == 201 and r.json()["full_name"] == "Laura Ficticia Gómez"
    # Un turno el próximo lunes 10:00 y una sesión realizada este año.
    monday = _next_weekday(0).isoformat()
    r = rec.post("/api/appointments", json={
        "patient_id": patient["id"], "professional_id": str(world.lucia.id),
        "starts_at": f"{monday}T10:00:00-03:00", "ends_at": f"{monday}T10:50:00-03:00"})
    assert r.status_code == 201, r.text
    first = datetime(datetime.now(MVD).year, 1, 2, 9, 0, tzinfo=MVD)
    db.add(Appointment(clinic_id=world.clinic_a.id, patient_id=patient["id"], professional_id=world.lucia.id,
                       branch_id=world.branch_a.id, starts_at=first, ends_at=first + timedelta(minutes=50),
                       status="completed", created_by=world.reception_a.id))
    db.commit()

    f = _fields(rec.get(f"/api/patients/{patient['id']}/ayex-form"))
    today = datetime.now(MVD)
    assert (f["Día"], f["Mes"], f["Año"]) == (f"{today.day:02d}", f"{today.month:02d}", str(today.year))
    assert f["Cedula1"] == "12345672"
    assert (f["PRIMER NOMBRE"], f["PRIMER APELLIDO"]) == ("DÁNTE", "FICTÍCIO")
    assert (f["DEPARTAMENTO"], f["LOCALIDAD"], f["CALLE"], f["NUMERO"], f["APTO"]) == (
        "Canelones", "Pando", "Calle Falsa", "123", "2")
    assert f["TELEFONO"] == "099 123 456"
    assert f["N DE PROVEEDOR"] == "99999" and f["EMAIL PROVEEDOR"] == "aurora@ejemplo.test"
    assert f["NOMBRE RAZON SOCIAL"] == world.clinic_a.name.upper()
    assert f["ACTIVIDADRow1"] == "Psicología"
    assert f["NOMBRE Y APELLIDO TECNICORow1"] == world.lucia.full_name
    assert (f["TÉCNICO Lunes desde 1"], f["TÉCNICO Lunes hasta 1"]) == ("10:00", "10:50")
    assert f["FECHA INICIO AÑO ACTUALRow1"] == first.strftime("%d/%m/%Y")
    assert f["fill_85"] == "5000"
    assert (f["Cedula2"], f["PRIMER NOMBRERow1_2"], f["PRIMER APELLIDORow1_2"]) == (
        "23456783", "LAURA", "FICTICIA")
    assert f["Group14"] is not None and "2" in str(f["Group14"])  # transporte: NO
    # Lo que Nordeste no sabe queda vacío y editable.
    assert f.get("SOLAR") in (None, "") and f.get("N PROVEEDORRow1") in (None, "")
    # Queda en la auditoría (sin datos del paciente en los detalles).
    events = db.scalars(select(AuditEvent).where(AuditEvent.action == "patient.ayex_form")).all()
    assert len(events) == 1 and "Dánte" not in str(events[0].details)


def test_form_permissions(world, login):
    rec = login(world.reception_a)
    patient = _ayex_patient(rec, world)
    url = f"/api/patients/{patient['id']}/ayex-form"
    assert login(world.admin_a).get(url).status_code == 200
    assert login(world.lucia).get(url).status_code == 403  # profesionales: no
    assert login(world.admin_b).get(url).status_code == 404  # otra clínica
    # Solo para pacientes AYEX.
    r = rec.get(f"/api/patients/{world.patient_a.id}/ayex-form")
    assert r.status_code == 409 and "solo para pacientes" in r.json()["detail"]


def test_form_schedule_includes_past_agenda(world, login, db):
    """Los días y horarios salen de la Agenda también con turnos ya pasados (realizados), no
    con los cancelados; si cambió el horario, vale el de la fecha más reciente."""
    rec = login(world.reception_a)
    patient = _ayex_patient(rec, world)
    today = datetime.now(MVD).date()
    monday = today - timedelta(days=today.weekday())

    def add(day: date, hour: int, status: str):
        start = datetime.combine(day, datetime.min.time(), tzinfo=MVD).replace(hour=hour)
        db.add(Appointment(clinic_id=world.clinic_a.id, patient_id=patient["id"], professional_id=world.lucia.id,
                           branch_id=world.branch_a.id, starts_at=start, ends_at=start + timedelta(minutes=45),
                           status=status, created_by=world.reception_a.id))

    add(monday - timedelta(weeks=2) + timedelta(days=1), 9, "completed")   # martes viejo
    add(monday - timedelta(weeks=1) + timedelta(days=1), 14, "completed")  # martes nuevo
    add(monday - timedelta(weeks=1) + timedelta(days=4), 8, "cancelled")   # viernes cancelado
    db.commit()
    f = _fields(rec.get(f"/api/patients/{patient['id']}/ayex-form"))
    assert (f["TÉCNICO Martes desde 1"], f["TÉCNICO Martes hasta 1"]) == ("14:00", "14:45")
    assert "TÉCNICO Viernes desde 1" not in f or not f["TÉCNICO Viernes desde 1"]
