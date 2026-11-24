"""Dueño del sistema: resumen de cada clínica, espacio que ocupa y funciones que se pueden
habilitar o deshabilitar por clínica. Datos ficticios."""

from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select

from app.features import FEATURE_DISABLED, FEATURE_KEYS
from app.models import AuditEvent, Clinic, OwnerAuditEvent, PatientFile
from tests.test_dueno_sistema import _ready_owner

# Una ruta de cada función, para comprobar que se bloquea (GET, sin efectos).
FEATURE_URLS = {
    "caja": lambda w: "/api/cash/today",
    "bps": lambda w: "/api/bps-schedule",
    "avisos": lambda w: "/api/notices/mine",
    "informe_mensual": lambda w: "/api/monthly-summary",
    "objetivos": lambda w: f"/api/patients/{w.patient_a.id}/goals",
    "archivos": lambda w: f"/api/patients/{w.patient_a.id}/files",
}
# Quién de la clínica A puede usar cada una (para ver que antes funcionaba).
FEATURE_USER = {"caja": "admin_a", "bps": "admin_a", "avisos": "lucia", "informe_mensual": "admin_a",
                "objetivos": "lucia", "archivos": "lucia"}


def _set(owner, clinic_id, key, enabled):
    return owner.http.put(f"/api/owner/clinics/{clinic_id}/features/{key}", json={"enabled": enabled},
                          headers={"X-CSRF-Token": owner.csrf})


def test_everything_is_enabled_by_default(world, db, login):
    me = login(world.admin_a).get("/api/auth/me").json()
    assert me["clinic"]["features"] == list(FEATURE_KEYS)


def test_disabling_a_feature_blocks_it_only_for_that_clinic_and_keeps_the_data(world, db, capsys, login):
    owner, _ = _ready_owner(db, capsys)
    assert set(FEATURE_URLS) == set(FEATURE_KEYS)
    for key in FEATURE_KEYS:
        user = login(getattr(world, FEATURE_USER[key]))
        url = FEATURE_URLS[key](world)
        assert user.get(url).status_code == 200, (key, user.get(url).text)

        r = _set(owner, world.clinic_a.id, key, False)
        assert r.status_code == 200, r.text
        assert {f["key"]: f["enabled"] for f in r.json()}[key] is False
        blocked = user.get(url)
        assert blocked.status_code == 403 and blocked.json()["detail"] == FEATURE_DISABLED, key
        assert key not in user.get("/api/auth/me").json()["clinic"]["features"]
        # La otra clínica sigue con todo.
        assert key in login(world.admin_b).get("/api/auth/me").json()["clinic"]["features"]

        assert _set(owner, world.clinic_a.id, key, True).status_code == 200
        assert user.get(url).status_code == 200, key

    # Lo que la clínica sí necesita siempre sigue andando, y las listas del BPS (para los datos de
    # las cuentas) también, aunque BPS esté apagado.
    _set(owner, world.clinic_a.id, "bps", False)
    admin = login(world.admin_a)
    assert admin.get("/api/bps-schedule/lists").status_code == 200
    assert admin.get("/api/patients").status_code == 200

    # Queda en la auditoría del dueño y en la de la clínica.
    owner_actions = db.scalars(select(OwnerAuditEvent.action).where(
        OwnerAuditEvent.clinic_id == world.clinic_a.id)).all()
    assert owner_actions.count("owner.feature_disable") == len(FEATURE_KEYS) + 1
    assert owner_actions.count("owner.feature_enable") == len(FEATURE_KEYS)
    events = db.scalars(select(AuditEvent).where(AuditEvent.clinic_id == world.clinic_a.id,
                                                 AuditEvent.action == "system.feature_disabled")).all()
    assert {e.details["feature"] for e in events} == set(FEATURE_KEYS)
    db.expire_all()
    assert db.get(Clinic, world.clinic_a.id).disabled_features == ["bps"]


def test_feature_changes_are_validated_and_idempotent(world, db, capsys, login):
    owner, _ = _ready_owner(db, capsys)
    assert _set(owner, world.clinic_a.id, "no-existe", False).status_code == 404
    assert _set(owner, world.clinic_a.id, "caja", True).status_code == 200  # ya estaba activa
    assert db.scalar(select(OwnerAuditEvent.id).where(OwnerAuditEvent.action.like("owner.feature%"))) is None
    # Sin CSRF no se cambia nada, y una cuenta de clínica no puede.
    assert owner.http.put(f"/api/owner/clinics/{world.clinic_a.id}/features/caja",
                          json={"enabled": False}).status_code == 403
    admin = login(world.admin_a)
    assert admin._write("PUT", f"/api/owner/clinics/{world.clinic_a.id}/features/caja",
                        json={"enabled": False}).status_code == 401


def test_dashboard_has_counts_and_accounts_but_never_patients(world, db, capsys, login):
    owner, _ = _ready_owner(db, capsys)
    login(world.admin_a)  # un ingreso de hoy
    r = owner.get(f"/api/owner/clinics/{world.clinic_a.id}/dashboard")
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["clinic"]["name"] == "Clínica A (prueba)"
    assert d["patients_total"] == 1
    assert {x["key"]: x["count"] for x in d["patients_by_status"]}["active"] == 1
    assert d["patients_by_affiliation"] == [{"key": "private", "count": 1}]
    assert d["patients_by_branch"] == [{"name": "Central", "is_active": True, "active": 1, "total": 1}]
    month = datetime.now(ZoneInfo("America/Montevideo")).strftime("%Y-%m")
    assert len(d["new_patients_by_month"]) == 12 and d["new_patients_by_month"][-1] == {"period": month, "count": 1}
    assert {x["key"]: x["count"] for x in d["accounts_by_role"]} == {"admin": 1, "reception": 1, "professional": 2}
    assert len(d["accounts"]) == 4 and d["accounts"][0]["full_name"] == "Admin"  # el que entró, primero
    assert d["accounts"][0]["last_seen_at"] is not None and d["accounts"][1]["last_seen_at"] is None
    assert len(d["logins_by_day"]) == 30 and d["logins_by_day"][-1]["count"] == 1
    assert d["active_accounts_7d"] == 1 and d["active_accounts_30d"] == 1
    assert d["storage"]["database_bytes"] > 0
    assert {t["table"]: t["rows"] for t in d["storage"]["tables"]}["patients"] == 1
    assert all(f["enabled"] for f in d["features"]) and len(d["features"]) == len(FEATURE_KEYS)
    # Nada de los pacientes: ni nombres ni apellidos.
    assert "Ana" not in r.text and "Beto" not in r.text and "\"Prueba\"" not in r.text
    assert owner.get("/api/owner/clinics/00000000-0000-0000-0000-000000000000/dashboard").status_code == 404
    # Una cuenta de clínica no puede verlo.
    assert login(world.admin_a).get(f"/api/owner/clinics/{world.clinic_a.id}/dashboard").status_code == 401


def test_storage_overview_splits_the_database_between_clinics(world, db, capsys):
    owner, _ = _ready_owner(db, capsys)
    db.add(PatientFile(clinic_id=world.clinic_a.id, patient_id=world.patient_a.id,
                       uploaded_by=world.lucia.id, original_name="informe-ficticio.pdf",
                       content_type="application/pdf", size_bytes=12345, sha256="0" * 64,
                       storage_key="clave-ficticia-de-prueba"))
    db.commit()
    r = owner.get("/api/owner/storage")
    assert r.status_code == 200, r.text
    s = r.json()
    by_name = {c["name"]: c for c in s["clinics"]}
    a, b = by_name["Clínica A (prueba)"], by_name["Clínica B (prueba)"]
    assert a["database_bytes"] > 0 and b["database_bytes"] > 0
    assert a["files_count"] == 1 and a["files_bytes"] == 12345 and b["files_bytes"] == 0
    assert s["files_bytes"] == 12345
    assert s["clinics_bytes"] == a["database_bytes"] + b["database_bytes"]
    assert s["database_bytes"] >= s["clinics_bytes"]
    assert s["shared_bytes"] == s["database_bytes"] - s["clinics_bytes"]
    assert a["tables"] == []  # el detalle por tabla está en el resumen de cada clínica
    d = owner.get(f"/api/owner/clinics/{world.clinic_a.id}/dashboard").json()
    assert d["files"] == {"patient_files": 1, "patient_files_withdrawn": 0, "patient_files_bytes": 12345,
                          "degrees": 0, "degrees_bytes": 0}
