"""Exportación completa de los datos de una clínica (pestaña Exportar de /sistema).

Comprueba que el .zip trae todo lo de ESA clínica y nada de otra, que no lleva contraseñas, que
queda en las dos auditorías, que solo lo genera el dueño (con confirmación), que funciona en un
espacio independiente, que los textos largos no rompen el Excel y que las preguntas de la
anamnesis del backend son las mismas que las de la interfaz. Datos ficticios."""

import csv
import hashlib
import io
import re
import zipfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.anamnesis_form import SECTIONS
from app.audit_labels import AUDIT_ACTION_LABELS
from app.config import BACKEND_DIR, get_settings
from app.main import app
from app.models import (
    AnamnesisVersion, Appointment, AuditEvent, CashMovement, CashRegister, ClinicalNote, GoalUpdate,
    Notice, NoticeRecipient, OwnerAuditEvent, PatientFile, PatientGuardian, PatientInstitution,
    ProfessionalDegree, Report, ReportSectionVersion, TreatmentGoal,
)
from tests.test_dueno_sistema import _ready_owner
from tests.test_espacio_independiente import _independent_space

PDF = b"%PDF-1.4 prueba ficticia\n"
SECRET_B = "SECRETO-DE-LA-CLINICA-B"


def _store(content: bytes, key: str) -> str:
    """Guarda un archivo en la carpeta de adjuntos (la de pruebas) y devuelve su huella."""
    folder = Path(get_settings().files_dir)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / key).write_bytes(content)
    return hashlib.sha256(content).hexdigest()


def _export(owner, clinic, reason="Fin del contrato (prueba)", name=None):
    """Los dos pasos: generar (devuelve el enlace) y bajar el .zip con ese enlace."""
    r = owner.post(f"/api/owner/clinics/{clinic.id}/export",
                   {"reason": reason, "confirm_name": clinic.name if name is None else name})
    if r.status_code != 200:
        return r
    return owner.get(r.json()["download_url"])


def _open(response) -> tuple[zipfile.ZipFile, str]:
    zf = zipfile.ZipFile(io.BytesIO(response.content))
    root = zf.namelist()[0].split("/")[0]
    assert all(n.startswith(root + "/") for n in zf.namelist())
    return zf, root


def _all_text(zf: zipfile.ZipFile) -> dict[str, str]:
    """El texto de cada entrada, sin la carpeta raíz (de las planillas, el de sus XML de adentro)."""
    out = {}
    for full in zf.namelist():
        data = zf.read(full)
        name = full.split("/", 1)[1]
        if name.endswith(".xlsx"):
            inner = zipfile.ZipFile(io.BytesIO(data))
            out[name] = "".join(inner.read(n).decode("utf-8") for n in inner.namelist())
        else:
            out[name] = data.decode("utf-8", errors="replace")
    return out


def _csv(zf, root, name) -> list[dict]:
    text = zf.read(f"{root}/datos-csv/{name}.csv").decode("utf-8-sig")
    return list(csv.DictReader(io.StringIO(text)))


def _fill_clinic_a(db, w):
    a, pa, lucia = w.clinic_a, w.patient_a, w.lucia
    now = datetime.now(timezone.utc)
    db.add(PatientGuardian(clinic_id=a.id, patient_id=pa.id, full_name="Marta Prueba", relationship="Madre",
                           document_number="1.111.111-1", created_by=w.reception_a.id, is_primary=True))
    school = PatientInstitution(clinic_id=a.id, patient_id=pa.id, name="Escuela N.º 1 (ficticia)",
                                level="primaria", created_by=w.reception_a.id)
    db.add(school)
    db.flush()
    original = ClinicalNote(clinic_id=a.id, patient_id=pa.id, author_id=lucia.id, kind="session",
                            session_date=date.today(), content="Nota original de la sesión.")
    db.add(original)
    db.flush()
    db.add(ClinicalNote(clinic_id=a.id, patient_id=pa.id, author_id=lucia.id, kind="session",
                        session_date=date.today(), content="Nota corregida de la sesión.",
                        supersedes_id=original.id, correction_reason="Error de tipeo"))
    db.add(ClinicalNote(clinic_id=a.id, patient_id=pa.id, author_id=lucia.id, kind="evaluation",
                        content="LARGA " + "x" * 40000))
    db.add(ClinicalNote(clinic_id=a.id, patient_id=pa.id, author_id=lucia.id, kind="institution",
                        institution_id=school.id, content="Reporte para la escuela."))
    db.add(AnamnesisVersion(clinic_id=a.id, patient_id=pa.id, author_id=lucia.id,
                            data={"motivo_dificultad": "Primera versión", "fecha_entrevista": "2026-10-01"},
                            created_at=now - timedelta(days=2)))
    db.add(AnamnesisVersion(clinic_id=a.id, patient_id=pa.id, author_id=lucia.id,
                            data={"motivo_dificultad": "Le cuesta leer", "fecha_entrevista": "2026-10-01",
                                  "hermano_1_nombre": "Leo", "hermano_1_edad": "4",
                                  "clave_vieja": "Dato de una pregunta que ya no existe",
                                  "entrevistado_nombre": "Marta Prueba"}))
    db.add(ReportSectionVersion(clinic_id=a.id, patient_id=pa.id, section="diagnostico", author_id=lucia.id,
                                data={"texto": "Diagnóstico viejo"}, created_at=now - timedelta(days=1)))
    db.add(ReportSectionVersion(clinic_id=a.id, patient_id=pa.id, section="diagnostico", author_id=lucia.id,
                                data={"texto": "Diagnóstico vigente"}))
    db.add(ReportSectionVersion(clinic_id=a.id, patient_id=pa.id, section="abordaje", owner_id=lucia.id,
                                author_id=lucia.id, data={"abordaje": "Trabajo semanal", "en_suma": "Avanza",
                                                          "sugerencias": "Seguir"}))
    db.add(Report(clinic_id=a.id, patient_id=pa.id, author_id=lucia.id, title="Informe de evolución",
                  content="DIAGNÓSTICO\nTexto del informe final.", status="final", finalized_at=now,
                  signers=[{"user_id": str(lucia.id), "name": "Lucia", "specialty": "Psicología"}]))
    db.add(Report(clinic_id=a.id, patient_id=pa.id, author_id=lucia.id, title="Informe sin terminar",
                  content="Borrador a medias.", status="draft"))
    goal = TreatmentGoal(clinic_id=a.id, patient_id=pa.id, created_by=lucia.id, area="Lectura",
                         description="Leer frases cortas")
    db.add(goal)
    db.flush()
    db.add(GoalUpdate(clinic_id=a.id, goal_id=goal.id, author_id=lucia.id, progress=30, note="Mejora"))
    db.add(Appointment(clinic_id=a.id, patient_id=pa.id, professional_id=lucia.id, branch_id=w.branch_a.id,
                       starts_at=now, ends_at=now + timedelta(minutes=45), status="completed",
                       created_by=w.reception_a.id))
    sha = _store(PDF, "a" * 32)
    db.add(PatientFile(clinic_id=a.id, patient_id=pa.id, uploaded_by=lucia.id, original_name="Estudio previo.pdf",
                       content_type="application/pdf", size_bytes=len(PDF), sha256=sha, storage_key="a" * 32))
    sha = _store(PDF + b"2", "b" * 32)
    db.add(PatientFile(clinic_id=a.id, patient_id=pa.id, uploaded_by=lucia.id, original_name="Retirado.pdf",
                       content_type="application/pdf", size_bytes=len(PDF) + 1, sha256=sha, storage_key="b" * 32,
                       withdrawn_at=now, withdrawn_by=lucia.id, withdraw_reason="Duplicado"))
    db.add(PatientFile(clinic_id=a.id, patient_id=pa.id, uploaded_by=lucia.id, original_name="Perdido.pdf",
                       content_type="application/pdf", size_bytes=10, sha256="0" * 64, storage_key="c" * 32))
    sha = _store(PDF + b"titulo", "d" * 32)
    db.add(ProfessionalDegree(clinic_id=a.id, user_id=lucia.id, original_name="Titulo.pdf",
                              content_type="application/pdf", size_bytes=len(PDF) + 6, sha256=sha,
                              storage_key="d" * 32))
    register = CashRegister(clinic_id=a.id, branch_id=w.branch_a.id, business_date=date.today(),
                            opening_amount=1000, opened_by=w.reception_a.id)
    db.add(register)
    db.flush()
    db.add(CashMovement(clinic_id=a.id, register_id=register.id, kind="income", amount=500,
                        concept="Sesión particular", created_by=w.reception_a.id))
    notice = Notice(clinic_id=a.id, author_id=w.reception_a.id, message="Reunión el viernes", to_all=True)
    db.add(notice)
    db.flush()
    db.add(NoticeRecipient(clinic_id=a.id, notice_id=notice.id, user_id=lucia.id))
    db.add(AuditEvent(clinic_id=a.id, actor_id=lucia.id, action="patient.view", entity_type="patient",
                      entity_id=str(pa.id), patient_id=pa.id))
    # Datos de la clínica B que NUNCA deben aparecer en la exportación de A.
    b, pb = w.clinic_b, w.patient_b
    db.add(ClinicalNote(clinic_id=b.id, patient_id=pb.id, author_id=w.bruno.id, kind="session",
                        content=SECRET_B))
    db.add(PatientGuardian(clinic_id=b.id, patient_id=pb.id, full_name=SECRET_B, relationship="Padre",
                           created_by=w.admin_b.id))
    db.add(AuditEvent(clinic_id=b.id, actor_id=w.admin_b.id, action=SECRET_B))
    db.commit()


def test_export_has_everything_of_the_clinic_and_nothing_of_others(world, db, capsys):
    _fill_clinic_a(db, world)
    owner, _ = _ready_owner(db, capsys)
    r = _export(owner, world.clinic_a)
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "application/zip"
    assert "attachment" in r.headers["content-disposition"]
    zf, root = _open(r)
    names = [n.split("/", 1)[1] for n in zf.namelist()]
    folder = next(n.split("/")[1] for n in names if n.startswith("pacientes/"))
    assert folder.startswith("Prueba, Ana (")
    for expected in ("LEEME.txt", "huellas-sha256.txt", "planillas/06-pacientes.xlsx",
                     "datos-csv/06-pacientes.csv", "planillas/22-auditoria.xlsx",
                     f"pacientes/{folder}/historia-clinica-completa.html", f"pacientes/{folder}/anamnesis.html"):
        assert expected in names, expected
    reports = [n for n in names if n.startswith(f"pacientes/{folder}/informes/")]
    assert len(reports) == 2 and any("(BORRADOR)" in n for n in reports)
    attached = [n for n in names if f"{folder}/archivos/" in n]
    assert any(n.endswith("Estudio previo.pdf") and "/retirados/" not in n for n in attached)
    assert any(n.endswith("Retirado.pdf") and "/retirados/" in n for n in attached)
    assert not any("Perdido" in n for n in attached)  # no estaba en el disco
    assert zf.read(f"{root}/{next(n for n in attached if n.endswith('Estudio previo.pdf'))}") == PDF
    assert any(n.startswith("clinica/titulos-profesionales/") for n in names)

    texts = _all_text(zf)
    everything = "\n".join(texts.values())
    # Nada de la clínica B ni contraseñas.
    assert SECRET_B not in everything
    assert str(world.patient_b.id) not in everything and "Beto" not in everything
    assert "admin@b.test" not in everything and "bruno@b.test" not in everything
    assert world.admin_a.password_hash not in everything and "argon2" not in everything

    # Planillas: notas con su corrección, textos largos completos en CSV y cortados en Excel.
    notes = _csv(zf, root, "11-notas-clinicas")
    fixed = next(n for n in notes if n["texto"] == "Nota corregida de la sesión.")
    assert fixed["motivo_de_la_correccion"] == "Error de tipeo" and fixed["corrige_a_la_nota"]
    long_note = next(n for n in notes if n["texto"].startswith("LARGA"))
    assert len(long_note["texto"]) == 40006
    assert "TEXTO CORTADO" in texts["planillas/11-notas-clinicas.xlsx"]
    assert any(n["institucion"] == "Escuela N.º 1 (ficticia)" for n in notes)
    answers = _csv(zf, root, "12-anamnesis")
    assert any(a["pregunta"].startswith("¿Cuál es la dificultad") and a["respuesta"] == "Le cuesta leer"
               and a["vigente"] == "Sí" for a in answers)
    assert any(a["respuesta"] == "Primera versión" and a["vigente"] == "No" for a in answers)
    files = {f["nombre_original"]: f for f in _csv(zf, root, "17-archivos")}
    assert files["Estudio previo.pdf"]["estado_de_la_copia"] == "Copiado"
    assert files["Perdido.pdf"]["estado_de_la_copia"] == "No estaba en el servidor"
    assert files["Retirado.pdf"]["motivo_del_retiro"] == "Duplicado"
    users = _csv(zf, root, "04-usuarios")
    assert {u["correo"] for u in users} == {"admin@a.test", "recepcion@a.test", "lucia@a.test", "mateo@a.test"}
    assert "password_hash" not in users[0]
    assert len(_csv(zf, root, "21-movimientos-de-caja")) == 1
    audit_rows = _csv(zf, root, "22-auditoria")
    assert [(e["accion"], e["descripcion"], e["paciente"]) for e in audit_rows] == [
        ("patient.view", "Consulta de ficha de paciente", "Ana Prueba")]

    # Documentos legibles.
    history = texts[f"pacientes/{folder}/historia-clinica-completa.html"]
    for piece in ("Nota original de la sesión.", "Nota corregida de la sesión.", "Error de tipeo",
                  "Diagnóstico vigente", "Diagnóstico viejo", "Trabajo semanal", "Leer frases cortas",
                  "Marta Prueba", "Escuela N.º 1 (ficticia)"):
        assert piece in history, piece
    anamnesis = texts[f"pacientes/{folder}/anamnesis.html"]
    assert "¿Cuál es la dificultad del niño/a? ¿Desde cuándo la notó?" in anamnesis
    assert "Le cuesta leer" in anamnesis and "Primera versión" in anamnesis
    assert "Leo · 4 años" in anamnesis and "01/10/2026" in anamnesis
    assert "Dato de una pregunta que ya no existe" in anamnesis  # nada se pierde
    final = texts[next(n for n in reports if "(Finalizado)" in n)]
    assert "<strong>DIAGNÓSTICO</strong>" in final and "Firma" in final
    assert "BORRADOR" in texts[next(n for n in reports if "(BORRADOR)" in n)]

    readme = texts["LEEME.txt"]
    assert world.clinic_a.name in readme and "Perdido.pdf" in readme

    # Huellas: cada archivo coincide con la suya.
    listed = dict(line.split("  ", 1)[::-1] for line in texts["huellas-sha256.txt"].splitlines())
    for name in names:
        if name != "huellas-sha256.txt":
            assert listed[name] == hashlib.sha256(zf.read(f"{root}/{name}")).hexdigest(), name

    # Auditoría del dueño y de la clínica.
    event = db.scalar(select(OwnerAuditEvent).where(OwnerAuditEvent.action == "owner.clinic_export"))
    assert event.clinic_id == world.clinic_a.id
    assert event.details == {"reason": "Fin del contrato (prueba)", "patients": 1, "files": 3}
    clinic_event = db.scalar(select(AuditEvent).where(AuditEvent.action == "system.clinic_export"))
    assert clinic_event.clinic_id == world.clinic_a.id and clinic_event.actor_id is None


def test_export_needs_the_owner_and_the_clinic_name(world, db, capsys, login):
    owner, _ = _ready_owner(db, capsys)
    assert _export(owner, world.clinic_a, name="Otra clínica").status_code == 422
    assert _export(owner, world.clinic_a, reason="").status_code == 422
    # Una sesión de la clínica no sirve para /api/owner (y sin sesión, tampoco).
    admin = login(world.admin_a)
    r = admin.post(f"/api/owner/clinics/{world.clinic_a.id}/export",
                   json={"reason": "Prueba", "confirm_name": world.clinic_a.name})
    assert r.status_code == 401
    assert TestClient(app).post(f"/api/owner/clinics/{world.clinic_a.id}/export",
                                json={"reason": "Prueba", "confirm_name": world.clinic_a.name}).status_code == 401
    assert db.scalar(select(OwnerAuditEvent).where(OwnerAuditEvent.action == "owner.clinic_export")) is None
    # Mayúsculas y espacios de más no importan.
    r = _export(owner, world.clinic_a, name="  " + world.clinic_a.name.upper() + " ")
    assert r.status_code == 200, r.text


def test_export_of_an_independent_space(world, db, capsys):
    clinic, _, _ = _independent_space(db)
    owner, _ = _ready_owner(db, capsys)
    r = _export(owner, clinic)
    assert r.status_code == 200, r.text
    zf, root = _open(r)
    readme = zf.read(f"{root}/LEEME.txt").decode("utf-8")
    assert "espacio de profesional independiente" in readme
    users = _csv(zf, root, "04-usuarios")
    assert [u["rol"] for u in users] == ["Profesional independiente (titular)"]
    assert _csv(zf, root, "06-pacientes") == []  # sin pacientes: la planilla queda solo con títulos
    everything = "\n".join(_all_text(zf).values())
    assert str(world.patient_a.id) not in everything and "lucia@a.test" not in everything  # nada de A


def _interface_questions() -> list[tuple]:
    """Lee las preguntas de frontend/src/pages/anamnesisForm.ts (sin ejecutar TypeScript)."""
    path = BACKEND_DIR.parent / "frontend" / "src" / "pages" / "anamnesisForm.ts"
    if not path.exists():
        pytest.skip("No está la carpeta frontend.")
    body = path.read_text(encoding="utf-8")
    body = body[body.index("export const ANAMNESIS_SECTIONS"):]
    body = body[:body.index("\n];")]
    token = re.compile(
        r'id:\s*"(?P<sid>[^"]+)",\s*title:\s*"(?P<stitle>[^"]+)"'
        r'|\{\s*title:\s*"(?P<gtitle>[^"]+)",\s*fields:'
        r'|\{\s*fields:'
        r'|(?P<sib>siblings:\s*true)'
        r'|\{\s*key:\s*"(?P<key>[^"]+)",\s*label:\s*"(?P<label>[^"]*)"'
        r'(?:,\s*type:\s*(?:"(?P<type>[a-z]+)"|(?P<opts>\{\s*options:)))?')
    out = []
    section = group = None
    for m in token.finditer(body):
        if m.group("sid"):
            section = (m.group("sid"), m.group("stitle"))
        elif m.group("key"):
            kind = m.group("type") or ("options" if m.group("opts") else "text")
            out.append((*section, group, m.group("key"), m.group("label"), kind))
        elif m.group("sib"):
            out.append((*section, group, "hermanos"))
        else:
            group = m.group("gtitle")
    return out


def test_anamnesis_questions_match_the_interface():
    ours = []
    for s in SECTIONS:
        for g in s.groups:
            ours += [(s.id, s.title, g.title, f.key, f.label, f.type) for f in g.fields]
            if g.siblings:
                ours.append((s.id, s.title, g.title, "hermanos"))
    theirs = _interface_questions()
    assert len(theirs) > 80
    assert ours == theirs, ("Las preguntas de la anamnesis cambiaron en la interfaz: actualizá "
                            "backend/app/anamnesis_form.py para que coincidan.")


def test_download_link_works_once_and_only_for_the_owner(world, db, capsys, monkeypatch):
    from app.routers import owner_export
    owner, _ = _ready_owner(db, capsys)
    body = {"reason": "Prueba", "confirm_name": world.clinic_a.name}
    ready = owner.post(f"/api/owner/clinics/{world.clinic_a.id}/export", body)
    assert ready.status_code == 200, ready.text
    data = ready.json()
    assert data["filename"].endswith(".zip") and data["patients"] == 1 and data["size_bytes"] > 0
    url = data["download_url"]
    assert TestClient(app).get(url).status_code == 401  # sin la sesión del dueño
    first = owner.get(url)
    assert first.status_code == 200 and first.content[:2] == b"PK"
    assert owner.get(url).status_code == 404  # una sola vez
    assert owner.get("/api/owner/exports/no-existe").status_code == 404
    assert owner.get("/api/owner/exports/" + "x" * 43).status_code == 404
    # Un enlace que no se usó vence.
    monkeypatch.setattr(owner_export, "EXPIRES_SECONDS", -1)
    late = owner.post(f"/api/owner/clinics/{world.clinic_a.id}/export", body).json()["download_url"]
    assert owner.get(late).status_code == 404


def test_audit_labels_match_the_interface():
    path = BACKEND_DIR.parent / "frontend" / "src" / "labels.ts"
    if not path.exists():
        pytest.skip("No está la carpeta frontend.")
    text = path.read_text(encoding="utf-8")
    block = text[text.index("export const AUDIT_ACTION_LABELS"):]
    block = block[:block.index("\n};")]
    theirs = dict(re.findall(r'^\s*"([^"]+)":\s*"((?:[^"\\]|\\.)*)",?\s*$', block, re.M))
    assert len(theirs) > 50
    assert AUDIT_ACTION_LABELS == theirs, ("Cambiaron los textos de la auditoría en la interfaz (labels.ts): "
                                           "actualizá backend/app/audit_labels.py para que coincidan.")
