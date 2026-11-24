"""Importación de pacientes desde CSV: vista previa sin guardar, validación fila por fila,
alta solo de las filas correctas, permisos y aislamiento entre clínicas. Datos ficticios."""

from sqlalchemy import func, select

from app.models import AuditEvent, Patient, PatientAccess

URL = "/api/patient-import"

CSV_OK = (
    "Cédula;Primer nombre;Segundo nombre;Primer apellido;Segundo apellido;Sexo;Tipo de afiliación;"
    "Fecha de nacimiento;Teléfono;Correo;Profesional responsable;Observaciones\n"
    "1.111.111-1;Inés;;Ficticia;Prueba;F;Privado;14/03/2015;099 111 111;;lucia@a.test;nada\n"
    "2.222.222-2;Tomás;José;Inventado;;m;AYEX;2010-01-31;;tomas@ejemplo.test;Mateo;\n"
    ";;;;;;;;;;;\n"
    "3.333.333-3;Pía;;Supuesta;;X;Tutela Militar;;;;;\n"
)

CSV_ERRORS = (
    "documento,primer_nombre,primer_apellido,sexo,tipo_afiliacion,fecha_nacimiento,profesional_responsable\n"
    "4.444.444-4,,SinNombre,F,privado,01/01/2000,\n"              # falta el nombre
    "5.555.555-5,Fecha,Mala,F,privado,31/02/2000,\n"              # fecha inexistente
    "6.666.666-6,Sexo,Raro,Q,privado,,\n"                         # sexo no reconocido
    "7.777.777-7,Uno,Repetido,,ayex,,\n"
    "7.777.777-7,Dos,Repetido,,ayex,,\n"                       # documento repetido en el archivo
    "8.888.888-8,Sin,Responsable,,ayex,,Bruno\n"               # profesional de otra clínica
    "9.999.999-9,Futuro,Nacido,,ayex,01/01/2999,\n"            # fecha en el futuro
    "1.010.101-0,Correcto,Ficticio,,militar,,\n"               # esta sí es válida
    "1.212.121-2,Sin,Afiliacion,,,,\n"                         # falta el tipo de afiliación
    "1.313.131-3,Otra,Afiliacion,,mutualista X,,\n"            # tipo no reconocido
)


def _post(client, body: str, dry_run: bool, encoding="utf-8"):
    return client.post(f"{URL}?dry_run={'true' if dry_run else 'false'}",
                       content=body.encode(encoding),
                       headers={"Content-Type": "application/octet-stream"})


def _count(db):
    db.expire_all()
    return db.scalar(select(func.count()).select_from(Patient))


def test_preview_does_not_save_and_import_creates(world, login, db):
    reception = login(world.reception_a)
    before = _count(db)
    r = _post(reception, CSV_OK, dry_run=True)
    assert r.status_code == 200, r.text
    data = r.json()
    assert (data["total"], data["valid"], data["invalid"], data["created"]) == (3, 3, 0, 0)
    assert data["ignored_columns"] == ["Observaciones"]
    assert data["rows"][0]["full_name"] == "Inés Ficticia Prueba"
    assert data["rows"][1]["responsible_name"] == "Mateo"
    assert _count(db) == before  # la vista previa no guarda nada

    r = _post(reception, CSV_OK, dry_run=False)
    assert r.status_code == 200, r.text
    assert r.json()["created"] == 3
    assert _count(db) == before + 3
    ines = db.scalar(select(Patient).where(Patient.document_number == "1.111.111-1"))
    pia = db.scalar(select(Patient).where(Patient.document_number == "3.333.333-3"))
    assert (ines.affiliation, pia.affiliation) == ("private", "military")
    assert ines.sex == "female" and str(ines.birth_date) == "2015-03-14" and ines.middle_name is None
    access = db.scalar(select(PatientAccess).where(PatientAccess.patient_id == ines.id))
    assert access.user_id == world.lucia.id and access.level == "responsible"
    # Lucía ya la ve en su listado.
    assert "Inés" in {p["first_name"] for p in login(world.lucia).get("/api/patients").json()}
    events = db.scalars(select(AuditEvent).where(AuditEvent.action == "patient.import")).all()
    assert len(events) == 3 and all(e.details == {} for e in events)

    # Volver a importar el mismo archivo no duplica: los documentos ya existen.
    r = _post(reception, CSV_OK, dry_run=False)
    assert r.json()["created"] == 0 and r.json()["invalid"] == 3


def test_row_errors_are_reported_and_only_valid_rows_import(world, login, db):
    admin = login(world.admin_a)
    data = _post(admin, CSV_ERRORS, dry_run=True).json()
    errors = {row["line"]: " ".join(row["errors"]) for row in data["rows"]}
    assert "Primer nombre" in errors[2]
    assert "DD/MM/AAAA" in errors[3]
    assert "Sexo" in errors[4]
    assert errors[5] == ""
    assert "repetido" in errors[6] and "línea 5" in errors[6]
    assert "no encontrado" in errors[7]  # Bruno es de otra clínica
    assert "futuro" in errors[8]
    assert errors[9] == ""
    assert errors[10] == "Tipo de afiliación: Este campo es obligatorio."
    assert errors[11] == "Tipo de afiliación no reconocido: usá Privado, AYEX, Tutela Militar o Tutela Policial."
    before = _count(db)
    r = _post(admin, CSV_ERRORS, dry_run=False)
    assert r.json()["created"] == 2
    assert _count(db) == before + 2


def test_permissions_and_file_checks(world, login):
    assert _post(login(world.lucia), CSV_OK, dry_run=True).status_code == 403
    reception = login(world.reception_a)
    # Columnas obligatorias.
    r = _post(reception, "documento;telefono\n1.234.567-8;099\n", dry_run=True)
    assert r.status_code == 422 and "primer_nombre" in r.json()["detail"]
    # Vacío.
    assert _post(reception, "", dry_run=True).status_code == 422
    # Demasiado grande.
    big = "primer_nombre;primer_apellido\n" + "A;B\n" * 600000
    assert _post(reception, big, dry_run=True).status_code == 413


def test_excel_windows_encoding_is_understood(world, login):
    body = "primer_nombre;primer_apellido;tipo_afiliacion\nNicolás;Muñoz;Privado\n"
    r = _post(login(world.reception_a), body, dry_run=True, encoding="cp1252")
    assert r.status_code == 200
    assert r.json()["rows"][0]["full_name"] == "Nicolás Muñoz"


def test_template_download(world, login):
    r = login(world.reception_a).get(f"{URL}/template")
    assert r.status_code == 200
    assert "attachment" in r.headers["content-disposition"]
    header = r.content.decode("utf-8-sig").strip()
    assert header.startswith("documento;primer_nombre") and "tipo_afiliacion" in header
    assert login(world.lucia).get(f"{URL}/template").status_code == 403


def test_same_document_written_differently_is_a_duplicate(world, login, db):
    admin = login(world.admin_a)
    body = ("documento;primer_nombre;primer_apellido;tipo_afiliacion\n"
            "4.321.987-6;Uno;Ficticio;privado\n"
            "43219876;Dos;Ficticio;privado\n")  # el mismo documento, sin puntos ni guion
    rows = _post(admin, body, dry_run=False).json()["rows"]
    assert rows[0]["status"] == "created"
    assert "línea 2" in " ".join(rows[1]["errors"])
    # Y en una importación posterior, contra el que ya está en la clínica.
    again = _post(admin, "documento;primer_nombre;primer_apellido;tipo_afiliacion\n"
                         "4 321 987-6;Tres;Ficticio;ayex\n", dry_run=True).json()["rows"][0]
    assert "Ya existe" in " ".join(again["errors"])


def test_download_rows_with_errors(world, login, db):
    admin = login(world.admin_a)
    before = _count(db)
    r = admin.post(f"{URL}/errors", content=CSV_ERRORS.encode(),
                   headers={"Content-Type": "application/octet-stream"})
    assert r.status_code == 200 and "con-errores" in r.headers["content-disposition"]
    text = r.content.decode("utf-8-sig")
    lines = text.strip().split("\r\n")
    assert lines[0].endswith(";errores") and lines[0].startswith("documento;primer_nombre")
    assert len(lines) == 1 + 8  # las 8 filas con errores, sin las 2 correctas
    assert "Correcto" not in text and "DD/MM/AAAA" in text
    assert _count(db) == before  # no guarda nada
    assert login(world.lucia).post(f"{URL}/errors", content=CSV_ERRORS.encode(),
                                   headers={"Content-Type": "application/octet-stream"}).status_code == 403
