"""Vencimiento del AYEX: obligatorio al ingresar o pasar a AYEX, y el Inicio avisa los que
vencen en los próximos 3 meses (amarillo; rojo a 2 meses o menos), los ya vencidos y los AYEX
que todavía no tienen fecha."""

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from app.ayex_alert import add_months, ayex_alert_before, ayex_level
from app.models import Patient


def _today() -> date:
    return datetime.now(ZoneInfo("America/Montevideo")).date()


def _new(client, first, **extra):
    return client.post("/api/patients", json={"first_name": first, "last_name": "Ficticio",
                                               "affiliation": "ayex", **extra})


def test_date_required_for_ayex(world, login):
    rec = login(world.reception_a)
    r = _new(rec, "Dante")
    assert r.status_code == 422 and r.json()["detail"] == "Indicá la fecha de vencimiento del AYEX."
    assert _new(rec, "Dante", ayex_expires_on="1999-01-01").status_code == 422  # fecha absurda
    r = _new(rec, "Dante", ayex_expires_on="2030-06-15")
    assert r.status_code == 201 and r.json()["ayex_expires_on"] == "2030-06-15"
    pid = r.json()["id"]
    # No se puede borrar la fecha mientras siga siendo AYEX…
    assert rec.patch(f"/api/patients/{pid}", json={"ayex_expires_on": None}).status_code == 422
    assert rec.get(f"/api/patients/{pid}").json()["ayex_expires_on"] == "2030-06-15"
    # …pero se puede cambiar, y si deja de ser AYEX se borra sola.
    assert rec.patch(f"/api/patients/{pid}", json={"ayex_expires_on": "2031-01-31"}).status_code == 200
    r = rec.patch(f"/api/patients/{pid}", json={"affiliation": "private"})
    assert r.status_code == 200 and r.json()["ayex_expires_on"] is None
    # Un privado no guarda fecha de AYEX aunque se mande.
    r = rec.post("/api/patients", json={"first_name": "Priv", "last_name": "Ficticio",
                                        "affiliation": "private", "ayex_expires_on": "2030-01-01"})
    assert r.status_code == 201 and r.json()["ayex_expires_on"] is None


def test_old_ayex_without_date_can_still_be_edited(world, login, db):
    """Los AYEX cargados antes (sin fecha) se pueden editar en otros datos."""
    beto = db.query(Patient).filter_by(first_name="Beto").one()
    r = login(world.admin_b).patch(f"/api/patients/{beto.id}", json={"phone": "099 000 000"})
    assert r.status_code == 200 and r.json()["ayex_expires_on"] is None


def test_add_months_and_levels():
    assert add_months(date(2026, 1, 31), 1) == date(2026, 2, 28)  # febrero no tiene 31
    assert add_months(date(2026, 11, 15), 3) == date(2027, 2, 15)  # cambia de año
    today = date(2026, 3, 15)
    assert ayex_alert_before(today) == date(2026, 6, 16)  # el 15/06 todavía tiene aviso
    assert ayex_level(date(2026, 3, 1), today) == "red"  # vencido
    assert ayex_level(date(2026, 5, 15), today) == "red"  # justo 2 meses
    assert ayex_level(date(2026, 5, 16), today) == "yellow"
    assert ayex_level(date(2026, 6, 15), today) == "yellow"  # justo 3 meses


def test_dashboard_lists_due_and_expired(world, login, db):
    today = _today()
    admin = login(world.admin_a)
    # Se cargan desordenados: el Inicio los devuelve del más cercano al más lejano.
    _new(admin, "Borde", ayex_expires_on=add_months(today, 3).isoformat())
    _new(admin, "Lejos", ayex_expires_on=(add_months(today, 3) + timedelta(days=1)).isoformat())
    _new(admin, "Amarillo", ayex_expires_on=(add_months(today, 2) + timedelta(days=1)).isoformat())
    _new(admin, "Rojo", ayex_expires_on=add_months(today, 1).isoformat())
    _new(admin, "Viejo", ayex_expires_on=(today - timedelta(days=40)).isoformat())
    pausa = _new(admin, "Pausa", ayex_expires_on=today.isoformat()).json()["id"]
    admin.patch(f"/api/patients/{pausa}", json={"status": "paused"})  # solo pacientes activos
    db.add(Patient(clinic_id=world.clinic_a.id, branch_id=world.branch_a.id, first_name="Sinfecha",
                   last_name="Ficticio", affiliation="ayex", created_by=world.admin_a.id))
    db.commit()
    d = admin.get("/api/dashboard").json()
    assert [(a["name"], a["expired"], a["level"]) for a in d["ayex_due"]] == [
        ("Viejo Ficticio", True, "red"),
        ("Rojo Ficticio", False, "red"),
        ("Amarillo Ficticio", False, "yellow"),
        ("Borde Ficticio", False, "yellow"),
    ]
    assert d["ayex_due_total"] == 4 and d["ayex_missing"] == 1
    # Un profesional sin acceso a esos pacientes no los ve.
    m = login(world.mateo).get("/api/dashboard").json()
    assert m["ayex_due"] == [] and m["ayex_missing"] == 0


def test_import_reads_optional_expiry(world, login, db):
    body = ("primer_nombre;primer_apellido;tipo_afiliacion;vencimiento_ayex\n"
            "Con;Fecha;AYEX;15/06/2030\n"
            "Sin;Fecha;AYEX;\n"
            "Mala;Fecha;AYEX;31/02/2030\n"
            "Priv;Ada;Privado;15/06/2030\n")
    admin = login(world.admin_a)
    r = admin.post("/api/patient-import?dry_run=false", content=body.encode(),
                   headers={"Content-Type": "application/octet-stream"})
    rows = r.json()["rows"]
    assert [(x["status"], x["ayex_expires_on"]) for x in rows] == [
        ("created", "2030-06-15"), ("created", None), ("error", None), ("created", None)]
    assert "Fecha de vencimiento del AYEX no válida" in rows[2]["errors"][0]
    db.expire_all()
    assert db.query(Patient).filter_by(first_name="Con").one().ayex_expires_on == date(2030, 6, 15)
    assert db.query(Patient).filter_by(first_name="Priv").one().ayex_expires_on is None


def test_patient_list_filters_like_dashboard(world, login, db):
    """El enlace del Inicio abre el listado con los mismos pacientes que cuenta el aviso."""
    today = _today()
    admin = login(world.admin_a)
    _new(admin, "Dante", ayex_expires_on=add_months(today, 3).isoformat())
    _new(admin, "Viejo", ayex_expires_on=(today - timedelta(days=40)).isoformat())
    _new(admin, "Lejos", ayex_expires_on=(add_months(today, 3) + timedelta(days=1)).isoformat())
    db.add(Patient(clinic_id=world.clinic_a.id, branch_id=world.branch_a.id, first_name="Sinfecha",
                   last_name="Ficticio", affiliation="ayex", created_by=world.admin_a.id))
    db.commit()

    def names(**params):
        r = admin.get("/api/patients", params={"status": "active", **params})
        assert r.status_code == 200, r.text
        return sorted(p["first_name"] for p in r.json())

    assert names(ayex="due") == ["Dante", "Viejo"]
    assert names(ayex="missing") == ["Sinfecha"]
    assert admin.get("/api/patients", params={"ayex": "otra"}).status_code == 422
    d = admin.get("/api/dashboard").json()
    assert d["ayex_due_total"] == 2 and d["ayex_missing"] == 1
    # La exportación a Excel respeta el mismo filtro.
    assert admin.get("/api/patient-export", params={"ayex": "missing"}).status_code == 200


def test_patient_detail_has_responsible_id(world, login):
    """La ficha trae el id del responsable (para proponerlo al dar un turno)."""
    r = login(world.reception_a).get(f"/api/patients/{world.patient_a.id}")
    assert r.status_code == 200 and r.json()["responsible_id"] == str(world.lucia.id)
