"""Cronograma BPS: la planilla oficial completada con los AYEX activos (todo ficticio)."""

import io
import re
import zipfile
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select

from app.models import AuditEvent, Branch, Patient
from app.bps import activity_for
from app.models import Specialty

MVD = ZoneInfo("America/Montevideo")


def _cells(content: bytes) -> dict[str, dict[str, object]]:
    """{hoja: {celda: valor}} leyendo el XML (sin dependencias extra)."""
    z = zipfile.ZipFile(io.BytesIO(content))
    shared = []
    if "xl/sharedStrings.xml" in z.namelist():
        sst = z.read("xl/sharedStrings.xml").decode()
        for si in re.findall(r"<si>(.*?)</si>", sst, re.S):
            shared.append("".join(re.findall(r"<t[^>]*>(.*?)</t>", si, re.S)))
    wb = z.read("xl/workbook.xml").decode()
    rels = dict(re.findall(r'Id="(rId\d+)"[^>]*Target="([^"]+)"', z.read("xl/_rels/workbook.xml.rels").decode()))
    out = {}
    for name, rid in re.findall(r'<sheet name="([^"]+)"[^>]*r:id="([^"]+)"', wb):
        xml = z.read(f"xl/{rels[rid]}").decode()
        cells = {}
        for ref, attrs, body in re.findall(r'<c r="([A-Z]+\d+)"([^>]*?)(?:/>|>(.*?)</c>)', xml, re.S):
            if 't="inlineStr"' in attrs:
                cells[ref] = re.search(r"<t[^>]*>(.*?)</t>", body, re.S).group(1)
            elif 't="s"' in attrs:
                cells[ref] = shared[int(re.search(r"<v>(\d+)</v>", body).group(1))]
            elif body and "<f" not in body and "<v>" in body:
                v = re.search(r"<v>(.*?)</v>", body).group(1)
                cells[ref] = int(v) if v.isdigit() else v
        out[name] = cells
    return out


def _next_weekday(weekday: int) -> date:
    d = date.today() + timedelta(days=1)
    while d.weekday() != weekday:
        d += timedelta(days=1)
    return d


def _setup(world, login):
    admin = login(world.admin_a)
    rec = login(world.reception_a)
    r = admin.patch("/api/clinic", json={"bps_provider_number": "99999", "phone": "2222 0000",
                                         "email": "aurora@ejemplo.test", "address_street": "Av. Ficticia",
                                         "address_number": "100", "address_locality": "Montevideo",
                                         "address_department": "Montevideo"})
    assert r.status_code == 200, r.text
    r = rec.post("/api/patients", json={
        "first_name": "Dánte", "middle_name": "Ito", "last_name": "Fictício", "second_last_name": "Pérez",
        "affiliation": "ayex", "ayex_expires_on": "2030-03-31", "document_number": "1.234.567-2",
        "phone": "099 123 456", "responsible_professional_id": str(world.lucia.id),
        "address_department": "Canelones", "address_locality": "Pando", "address_street": "Calle Falsa",
        "address_number": "123", "address_apartment": "2"})
    assert r.status_code == 201, r.text
    patient = r.json()
    # Datos BPS de la profesional (en "Mi cuenta").
    lucia = login(world.lucia)
    r = lucia.patch("/api/account", json={
        "first_name": "Lucía", "last_name": "Ficticia", "second_last_name": "Sosa",
        "bps_training": "PSICOLOGIA", "degree_issuer": "UDELAR", "document_number": "3.456.789-1"})
    assert r.status_code == 200, r.text
    assert r.json()["bps_training"] == "PSICOLOGIA"
    monday = _next_weekday(0).isoformat()
    r = rec.post("/api/appointments", json={
        "patient_id": patient["id"], "professional_id": str(world.lucia.id),
        "starts_at": f"{monday}T10:00:00-03:00", "ends_at": f"{monday}T10:50:00-03:00"})
    assert r.status_code == 201, r.text
    return admin, rec, patient


def test_schedule_is_filled(world, login, db):
    admin, rec, patient = _setup(world, login)
    r = admin.get("/api/bps-schedule")
    assert r.status_code == 200, r.text
    assert "cronograma-bps-" in r.headers["content-disposition"]
    c = _cells(r.content)
    prov = c["PROV"]
    assert prov["C2"] == 99999 and prov["E2"] == world.clinic_a.name.upper()
    assert (prov["C3"], prov["E3"], prov["G3"], prov["E4"], prov["G4"]) == (
        "2222 0000", "Av. Ficticia 100", "Montevideo", "aurora@ejemplo.test", "Montevideo")
    assert prov["G8"] == datetime.now(MVD).year
    u = c["USUARIOS"]
    assert [u[f"{col}2"] for col in "ABCDEFG"] == [
        12345672, "Fictício", "Pérez", "Dánte", "Ito", "099 123 456", "Calle Falsa 123 apto 2, Pando, Canelones"]
    assert "A3" not in u  # Ana es privada: no va
    t = c["TÉCNICOS"]
    assert [t.get(f"{col}2") for col in "ABCDEFG"] == [
        34567891, "Ficticia", "Sosa", "Lucía", None, "PSICOLOGIA", "UDELAR"]
    lun = c["LUN"]
    assert [lun[f"{col}5"] for col in "ABCDE"] == [
        1, "Fictício Dánte - 12345672", "10:00 a 10:50", " PSICOLOGÍA", "Lucía Ficticia - PSICOLOGIA"]
    assert "B5" not in c["MAR"]
    event = db.scalar(select(AuditEvent).where(AuditEvent.action == "patient.bps_schedule"))
    assert event.details == {"count": 1}


def test_permissions_and_reception_scope(world, login, db):
    admin, rec, _ = _setup(world, login)
    assert login(world.lucia).get("/api/bps-schedule").status_code == 403
    # Un AYEX de otra sucursal: Administración lo exporta, Recepción (de Central) no lo ve.
    pando = Branch(clinic_id=world.clinic_a.id, name="Pando")
    db.add(pando)
    db.flush()
    db.add(Patient(clinic_id=world.clinic_a.id, first_name="Zoe", last_name="Zeta", affiliation="ayex",
                   created_by=world.admin_a.id, branch_id=pando.id))
    db.add(Patient(clinic_id=world.clinic_a.id, first_name="Alta", last_name="Aaa", affiliation="ayex",
                   status="discharged", created_by=world.admin_a.id, branch_id=world.branch_a.id))
    db.commit()
    names_admin = [v for k, v in _cells(admin.get("/api/bps-schedule").content)["USUARIOS"].items()
                   if k.startswith("D") and k != "D1"]
    names_rec = [v for k, v in _cells(rec.get("/api/bps-schedule").content)["USUARIOS"].items()
                 if k.startswith("D") and k != "D1"]
    assert names_admin == ["Dánte", "Zoe"]  # el de alta no va
    assert names_rec == ["Dánte"]
    # La otra clínica no ve nada de la clínica A.
    other = _cells(login(world.admin_b).get("/api/bps-schedule").content)["USUARIOS"]
    assert other.get("D2") == "Beto" and "D3" not in other


def test_bps_fields_are_validated_and_activity_mapped(world, login, db):
    lucia = login(world.lucia)
    assert lucia.patch("/api/account", json={"bps_training": "ASTROLOGIA"}).status_code == 422
    assert lucia.patch("/api/account", json={"degree_issuer": "Otra cosa"}).status_code == 422
    admin = login(world.admin_a)
    sp = db.scalar(select(Specialty).where(Specialty.clinic_id == world.clinic_a.id,
                                           Specialty.name == "Terapia ocupacional"))
    assert activity_for(sp) == "TERAPIA OCUPACIONAL"  # sin asociar: por el nombre
    r = admin.patch(f"/api/specialties/{sp.id}", json={"bps_activity": "HIDROTERAPIA"})
    assert r.status_code == 200, r.text
    assert any(s["bps_activity"] == "HIDROTERAPIA" for s in admin.get("/api/specialties").json())
    assert admin.patch(f"/api/specialties/{sp.id}", json={"bps_activity": "NADA"}).status_code == 422
    assert admin.patch(f"/api/specialties/{sp.id}", json={"bps_activity": ""}).status_code == 200
    db.refresh(sp)
    assert sp.bps_activity is None
    # Administración también puede corregir los datos BPS de un profesional.
    r = admin.patch(f"/api/users/{world.mateo.id}", json={"bps_training": "TERAPIA OCUPACIONAL",
                                                          "first_name": "Mateo"})
    assert r.status_code == 200 and r.json()["first_name"] == "Mateo", r.text
    assert login(world.reception_a).patch(f"/api/specialties/{sp.id}", json={"bps_activity": "HIDROTERAPIA"}).status_code == 403


def test_day_sheets_use_agenda_past_and_future(world, login, db):
    """Los días salen de la Agenda: también turnos ya pasados (realizados o con inasistencia),
    no los cancelados; si cambió el horario, vale el de la fecha más reciente o próxima."""
    from app.models import Appointment
    admin, rec, patient = _setup(world, login)  # deja un turno el próximo lunes 10:00
    today = datetime.now(MVD).date()
    monday = today - timedelta(days=today.weekday())

    def add(day: date, hour: int, status: str):
        start = datetime.combine(day, datetime.min.time(), tzinfo=MVD).replace(hour=hour)
        db.add(Appointment(clinic_id=world.clinic_a.id, patient_id=patient["id"], professional_id=world.lucia.id,
                           branch_id=world.branch_a.id, starts_at=start, ends_at=start + timedelta(minutes=45),
                           status=status, created_by=world.reception_a.id))

    add(monday - timedelta(weeks=2) + timedelta(days=1), 9, "completed")   # martes, horario viejo
    add(monday - timedelta(weeks=1) + timedelta(days=1), 14, "completed")  # martes, horario nuevo
    add(monday - timedelta(weeks=1) + timedelta(days=3), 8, "no_show")     # jueves: cuenta
    add(monday - timedelta(weeks=1) + timedelta(days=4), 8, "cancelled")   # viernes: no cuenta
    add(monday - timedelta(weeks=6) + timedelta(days=2), 8, "completed")   # miércoles muy viejo: no
    db.commit()
    c = _cells(admin.get("/api/bps-schedule").content)
    assert [c["MAR"].get(f"{col}5") for col in "BC"] == ["Fictício Dánte - 12345672", "14:00 a 14:45"]
    assert "B6" not in c["MAR"]
    assert c["JUE"]["C5"] == "08:00 a 08:45"
    assert "B5" not in c["VIE"] and "B5" not in c["MIE"]
    assert c["LUN"]["C5"] == "10:00 a 10:50"
