"""Importar pacientes desde el Cronograma BPS (.xlsx): lee la hoja USUARIOS, crea pacientes
AYEX, saltea los que ya están y rechaza archivos que no son el cronograma. Datos ficticios."""

import io
import zipfile

from sqlalchemy import func, select

from app.models import AuditEvent, Patient
from app.routers.bps_schedule import TEMPLATE
from app.routers.patient_import import _split_address
from app.xlsx_template import XlsxTemplate

URL = "/api/patient-import"


def _cronograma(rows: dict[int, list]) -> bytes:
    """La planilla oficial (vacía) con estas filas en USUARIOS: {fila: [A..G]}."""
    book = XlsxTemplate(TEMPLATE.read_bytes())
    for row, values in rows.items():
        book.set_row("USUARIOS", row, "A", values)
    return book.save()


def _post(client, body: bytes, dry_run: bool, path: str = ""):
    query = "" if path else f"?dry_run={'true' if dry_run else 'false'}"
    return client.post(f"{URL}{path}{query}", content=body,
                       headers={"Content-Type": "application/octet-stream"})


def _count(db):
    db.expire_all()
    return db.scalar(select(func.count()).select_from(Patient))


def _patient(db, document):
    db.expire_all()
    return db.scalar(select(Patient).where(Patient.document_number == document))


def test_preview_and_import_from_schedule(world, login, db):
    db.add(Patient(clinic_id=world.clinic_a.id, branch_id=world.branch_a.id, first_name="Ya",
                   last_name="Cargada", document_number="3.333.333-3", affiliation="ayex",
                   created_by=world.admin_a.id))
    db.commit()
    file = _cronograma({
        2: [41234567, "Ficticio", "Prueba", "Juana", "María", 99123456,
            "Av. Siempreviva 742 apto 3, Pando, Canelones"],
        3: ["5.555.555-5", "Inventado", None, "Pedro", None, "2900 1234", "Calle Sin Departamento 123"],
        4: [33333333, "Cargada", None, "Ya", None, "teléfono raro", None],  # ya está: se saltea
        6: [6666666, "SinNombre", None, None, None, None, None],            # falta el nombre
    })
    reception = login(world.reception_a)
    before = _count(db)
    r = _post(reception, file, dry_run=True)
    assert r.status_code == 200, r.text
    data = r.json()
    assert (data["total"], data["valid"], data["invalid"], data["skipped"], data["created"]) == (4, 2, 1, 1, 0)
    assert data["ignored_columns"] == []
    rows = {row["line"]: row for row in data["rows"]}
    assert set(rows) == {2, 3, 4, 6}  # el número de fila de Excel
    assert rows[2]["full_name"] == "Juana María Ficticio Prueba" and rows[2]["affiliation"] == "ayex"
    assert rows[4]["status"] == "skipped" and rows[4]["errors"] == [] and "Ya está" in rows[4]["note"]
    assert rows[6]["status"] == "error" and "Primer nombre" in " ".join(rows[6]["errors"])
    assert _count(db) == before  # la vista previa no guarda nada

    r = _post(reception, file, dry_run=False)
    assert r.status_code == 200, r.text
    assert r.json()["created"] == 2
    assert _count(db) == before + 2
    juana = _patient(db, "41234567")
    assert (juana.first_name, juana.middle_name, juana.last_name, juana.second_last_name) == (
        "Juana", "María", "Ficticio", "Prueba")
    assert juana.affiliation == "ayex" and juana.status == "active" and juana.ayex_expires_on is None
    assert juana.branch_id == world.branch_a.id
    assert juana.phone == "099123456"  # Excel le había sacado el 0
    assert (juana.address_street, juana.address_apartment, juana.address_locality,
            juana.address_department) == ("Av. Siempreviva 742", "3", "Pando", "Canelones")
    pedro = _patient(db, "5.555.555-5")
    assert pedro.address_street == "Calle Sin Departamento 123" and pedro.address_department is None
    events = db.scalars(select(AuditEvent).where(AuditEvent.action == "patient.import")).all()
    assert len(events) == 2 and all(e.details == {"kind": "bps_schedule"} for e in events)

    # El cronograma del mes siguiente trae a los mismos: no se duplican ni dan error.
    again = _post(reception, file, dry_run=False).json()
    assert (again["created"], again["skipped"], again["invalid"]) == (0, 3, 1)


def test_schedule_exported_by_lumen_can_be_imported(world, login, db):
    db.add(Patient(clinic_id=world.clinic_a.id, branch_id=world.branch_a.id, first_name="Lola",
                   middle_name="Sol", last_name="Ficticia", second_last_name="Demo",
                   document_number="1.234.567-2", affiliation="ayex", phone="099 555 555",
                   address_street="Calle Inventada", address_number="1234", address_apartment="5",
                   address_locality="Pando", address_department="Canelones", created_by=world.admin_a.id))
    db.commit()
    exported = login(world.admin_a).get("/api/bps-schedule")
    assert exported.status_code == 200
    # Otra clínica importa esa misma planilla.
    r = _post(login(world.admin_b), exported.content, dry_run=False)
    assert r.status_code == 200, r.text
    assert r.json()["created"] == 1
    lola = db.scalar(select(Patient).where(Patient.clinic_id == world.clinic_b.id,
                                           Patient.first_name == "Lola"))
    assert (lola.middle_name, lola.last_name, lola.second_last_name) == ("Sol", "Ficticia", "Demo")
    assert lola.document_number == "12345672" and lola.affiliation == "ayex"
    assert lola.phone == "099 555 555"
    assert (lola.address_street, lola.address_apartment, lola.address_locality,
            lola.address_department) == ("Calle Inventada 1234", "5", "Pando", "Canelones")


def _hand_made_xlsx(sheets: dict[str, str], shared: list[str], doctype: str = "") -> bytes:
    """Un .xlsx mínimo como lo guarda Excel: textos en sharedStrings y hojas con <c t="s">."""
    ns = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" ' \
         'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
    sheet_tags = "".join(f'<sheet name="{n}" sheetId="{i}" r:id="rId{i}"/>' for i, n in enumerate(sheets, 1))
    rels = "".join(
        f'<Relationship Id="rId{i}" Type="http://schemas.openxmlformats.org/officeDocument/2006/'
        f'relationships/worksheet" Target="worksheets/sheet{i}.xml"/>' for i in range(1, len(sheets) + 1))
    rels += ('<Relationship Id="rIdS" Type="http://schemas.openxmlformats.org/officeDocument/2006/'
             'relationships/sharedStrings" Target="sharedStrings.xml"/>')
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        z.writestr("xl/workbook.xml", f'<?xml version="1.0"?>{doctype}<workbook {ns}><sheets>{sheet_tags}</sheets></workbook>')
        z.writestr("xl/_rels/workbook.xml.rels",
                   '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   f"{rels}</Relationships>")
        z.writestr("xl/sharedStrings.xml", f"<sst {ns}>" + "".join(shared) + "</sst>")
        for i, body in enumerate(sheets.values(), 1):
            z.writestr(f"xl/worksheets/sheet{i}.xml", f"<worksheet {ns}><sheetData>{body}</sheetData></worksheet>")
    return out.getvalue()


HEADER = ["DOCUMENTO", "1er APELLIDO", "2do APELLIDO", "1er NOMBRE", "2do NOMBRE", "TELÉFONO", "DIRECCIÓN"]


def test_file_saved_by_excel_with_shared_strings(world, login, db):
    shared = [f"<si><t>{h}</t></si>" for h in HEADER] + [
        "<si><r><t>Fic</t></r><r><rPr><b/></rPr><t>ticia</t></r><rPh><t>X</t></rPh></si>",  # 7
        "<si><t xml:space=\"preserve\"> Rosa </t></si>",                                       # 8
    ]
    header = "".join(f'<c r="{c}1" t="s"><v>{i}</v></c>' for i, c in enumerate("ABCDEFG"))
    usuarios = (
        f'<row r="1">{header}</row>'
        '<row r="2"><c r="A2"><v>4.7654321E7</v></c><c r="B2" t="s"><v>7</v></c>'
        '<c r="D2" t="s"><v>8</v></c><c r="F2" t="str"><f>"099 "&amp;"222 333"</f><v>099 222 333</v></c>'
        '<c r="H2" t="str"><f>B2</f><v>Ficticia</v></c></row>'
        '<row r="3"><c r="H3" t="e"><v>#N/A</v></c><c r="I3"><f>1+1</f><v>2</v></c></row>'
    )
    file = _hand_made_xlsx({"PROV": "", "USUARIOS": usuarios}, shared)
    data = _post(login(world.admin_a), file, dry_run=False).json()
    assert (data["total"], data["created"]) == (1, 1), data
    rosa = _patient(db, "47654321")
    assert (rosa.first_name, rosa.last_name, rosa.phone) == ("Rosa", "Ficticia", "099 222 333")


def test_files_that_are_not_the_schedule_are_rejected(world, login, db):
    admin = login(world.admin_a)
    header = "".join(f'<c r="{c}1" t="s"><v>{i}</v></c>' for i, c in enumerate("ABCDEFG"))
    shared = [f"<si><t>{h}</t></si>" for h in HEADER]
    cases = [
        (_hand_made_xlsx({"Hoja1": f'<row r="1">{header}</row>'}, shared), "no es un Cronograma"),
        (_hand_made_xlsx({"USUARIOS": '<row r="1"><c r="A1" t="s"><v>3</v></c></row>'}, shared),
         "no es un Cronograma"),
        (b"PK\x03\x04no es un zip de verdad", "no es un Excel"),
        (_hand_made_xlsx({"USUARIOS": f'<row r="1">{header}</row>'}, shared,
                         doctype='<!DOCTYPE x [<!ENTITY a "aaaa">]>'), "no permitido"),
    ]
    for body, message in cases:
        r = _post(admin, body, dry_run=True)
        assert r.status_code == 422 and message in r.json()["detail"], r.text
    file = _cronograma({2: [11111111, "Uno", None, "Ficticio", None, None, None]})
    assert _post(login(world.lucia), file, dry_run=True).status_code == 403  # solo Recepción y Administración


def test_error_rows_come_back_as_csv_that_can_be_fixed_and_imported(world, login, db):
    file = _cronograma({
        2: [12121212, "Correcta", None, "Fila", None, None, None],
        3: [13131313, "Mala", None, "Fila", None, "no es teléfono", "Calle Falsa 123, Montevideo"],
    })
    admin = login(world.admin_a)
    r = _post(admin, file, dry_run=True, path="/errors")
    assert r.status_code == 200, r.text
    lines = r.content.decode("utf-8-sig").strip().split("\r\n")
    assert lines[0] == ("documento;primer_apellido;segundo_apellido;primer_nombre;segundo_nombre;"
                        "telefono;direccion;tipo_afiliacion;errores")
    assert len(lines) == 2 and lines[1].startswith("13131313;Mala") and "Teléfono" in lines[1]
    fixed = lines[0] + "\r\n" + lines[1].replace("no es teléfono", "099 777 777") + "\r\n"
    data = _post(admin, fixed.encode("utf-8"), dry_run=False).json()
    assert data["created"] == 1 and data["ignored_columns"] == ["errores"], data
    mala = _patient(db, "13131313")
    assert mala.affiliation == "ayex" and mala.address_street == "Calle Falsa 123"
    assert mala.address_department == "Montevideo"


def test_split_address():
    assert _split_address("Bv. Artigas 1000 ap. 4B,  Montevideo") == {
        "address_department": "Montevideo", "address_street": "Bv. Artigas 1000", "address_apartment": "4B"}
    assert _split_address("Calle Apolo 12, Barrio Sur, montevideo") == {
        "address_department": "Montevideo", "address_locality": "Barrio Sur", "address_street": "Calle Apolo 12"}
    assert _split_address("Ruta 8 km 30, Paso Carrasco, Canelones")["address_locality"] == "Paso Carrasco"
    assert _split_address("Ruta 8 km 30 casa 2") == {"address_street": "Ruta 8 km 30 casa 2"}
    assert _split_address("Calle X 5, Ciudad Inventada") == {"address_street": "Calle X 5, Ciudad Inventada"}
    assert _split_address("Rio Negro 1500 apto 2, Fray Bentos, Rio Negro")["address_department"] == "Río Negro"
