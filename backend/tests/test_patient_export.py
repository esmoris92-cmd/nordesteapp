"""Exportar pacientes a Excel: permisos, filtros, aislamiento entre clínicas, contenido
correcto del archivo, texto que nunca se ejecuta como fórmula y auditoría. Datos ficticios."""

import io
import zipfile
import xml.etree.ElementTree as ET
from datetime import date, timedelta

import pytest
from sqlalchemy import select

from app.models import AuditEvent

URL = "/api/patient-export"
NS = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}


def _rows(content: bytes) -> list[list[str]]:
    """Lee la hoja: texto de cada celda (los números/fechas como su valor crudo)."""
    with zipfile.ZipFile(io.BytesIO(content)) as zf:
        sheet = ET.fromstring(zf.read("xl/worksheets/sheet1.xml"))
    rows = []
    for row in sheet.find("x:sheetData", NS):
        values = [None] * 20
        for c in row:
            letter = "".join(ch for ch in c.get("r") if ch.isalpha())
            index = sum((ord(ch) - 64) * 26 ** i for i, ch in enumerate(reversed(letter))) - 1
            t = c.find("x:is/x:t", NS)
            v = c.find("x:v", NS)
            assert c.find("x:f", NS) is None  # nunca hay fórmulas
            values[index] = t.text if t is not None else v.text
        rows.append(values)
    return rows


def test_export_contents_and_isolation(world, login, db):
    reception = login(world.reception_a)
    reception.patch(f"/api/patients/{world.patient_a.id}", json={
        "document_number": "1.234.567-8", "sex": "female", "birth_date": "2015-03-14"})
    r = reception.get(URL)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    assert "attachment" in r.headers["content-disposition"]
    assert r.headers["content-disposition"].endswith('.xlsx"')
    rows = _rows(r.content)
    assert rows[0][:9] == ["documento", "primer_nombre", "segundo_nombre", "primer_apellido",
                           "segundo_apellido", "sexo", "tipo_afiliacion", "vencimiento_ayex",
                           "fecha_nacimiento"]
    assert len(rows) == 2  # Ana; Beto es de otra clínica y no aparece
    ana = rows[1]
    assert ana[0] == "1.234.567-8" and ana[1] == "Ana" and ana[3] == "Prueba"
    assert ana[5] == "F" and ana[6] == "Privado"
    assert ana[7] is None  # privada: sin vencimiento de AYEX
    assert date(1899, 12, 30) + timedelta(days=int(ana[8])) == date(2015, 3, 14)
    assert "Lucia" in ana and "Activo" in ana

    events = db.scalars(select(AuditEvent).where(AuditEvent.action == "patient.export")).all()
    assert len(events) == 1 and events[0].details == {"count": 1}


def test_export_respects_filters_and_roles(world, login):
    admin = login(world.admin_a)
    admin.post("/api/patients", json={"first_name": "Rosa", "last_name": "Militar",
                                      "affiliation": "military"})
    names = lambda **params: [r[1] for r in _rows(admin.get(URL, params=params).content)[1:]]
    assert sorted(names()) == ["Ana", "Rosa"]
    assert names(affiliation="military") == ["Rosa"]
    assert names(q="Prueba") == ["Ana"]
    assert names(status="paused") == []
    assert login(world.lucia).get(URL).status_code == 403  # profesionales no exportan


def test_export_ayex_expiry(world, login):
    admin = login(world.admin_a)
    admin.post("/api/patients", json={"first_name": "Dante", "last_name": "Ficticio",
                                      "affiliation": "ayex", "ayex_expires_on": "2030-06-15"})
    dante = next(r for r in _rows(admin.get(URL).content)[1:] if r[1] == "Dante")
    assert dante[6] == "AYEX" and date(1899, 12, 30) + timedelta(days=int(dante[7])) == date(2030, 6, 15)


def test_text_is_never_a_formula(world, login):
    reception = login(world.reception_a)
    reception.post("/api/patients", json={"first_name": "=HYPERLINK(\"http://x\")",
                                          "last_name": "+1-2", "affiliation": "ayex", "ayex_expires_on": "2030-12-31"})
    rows = _rows(reception.get(URL).content)  # _rows ya verifica que no haya fórmulas
    assert ["=HYPERLINK(\"http://x\")", "+1-2"] in [[r[1], r[3]] for r in rows]


def test_file_opens_in_a_spreadsheet_library(world, login):
    """Comprobación extra con openpyxl, solo si está instalado (no es una dependencia)."""
    openpyxl = pytest.importorskip("openpyxl")
    content = login(world.reception_a).get(URL).content
    sheet = openpyxl.load_workbook(io.BytesIO(content)).active
    assert sheet["B1"].value == "primer_nombre" and sheet["B2"].value == "Ana"
    assert sheet.freeze_panes == "A2"
