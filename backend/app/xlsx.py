"""Generador mínimo de archivos Excel (.xlsx) sin librerías externas.

Un .xlsx es un ZIP con algunos XML adentro. Aquí se escribe una sola hoja con:
encabezado en negrita, fila de encabezado fija, filtro automático, ancho de columnas y
fechas como fechas reales de Excel (formato DD/MM/AAAA).

Seguridad: todo el texto se guarda como texto ("inlineStr"), nunca como fórmula, así que un
valor como "=HIPERVINCULO(...)" no se ejecuta al abrir el archivo.
"""

import io
import re
import zipfile
from datetime import date, datetime
from xml.sax.saxutils import escape

Cell = str | int | float | date | datetime | None

# Caracteres de control que XML no permite (Excel daría el archivo por dañado).
_INVALID_XML = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
_EXCEL_EPOCH = date(1899, 12, 30)


def _col(index: int) -> str:
    """0 -> A, 25 -> Z, 26 -> AA."""
    name = ""
    index += 1
    while index:
        index, rem = divmod(index - 1, 26)
        name = chr(65 + rem) + name
    return name


def _text(value: str) -> str:
    return escape(_INVALID_XML.sub("", value))


def _cell(ref: str, value: Cell, header: bool) -> str:
    if value is None or value == "":
        return ""
    if isinstance(value, datetime):
        serial = (value.date() - _EXCEL_EPOCH).days + (
            value.hour * 3600 + value.minute * 60 + value.second) / 86400
        return f'<c r="{ref}" s="3"><v>{serial}</v></c>'
    if isinstance(value, date):
        return f'<c r="{ref}" s="2"><v>{(value - _EXCEL_EPOCH).days}</v></c>'
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        style = ' s="1"' if header else ""
        return f'<c r="{ref}" t="inlineStr"{style}><is><t xml:space="preserve">{_text(str(value))}</t></is></c>'
    return f'<c r="{ref}"><v>{value}</v></c>'


def build_xlsx(sheet_name: str, headers: list[str], rows: list[list[Cell]],
               widths: list[int] | None = None) -> bytes:
    last_col = _col(len(headers) - 1)
    lines = []
    for r, values in enumerate([headers, *rows], start=1):
        cells = "".join(_cell(f"{_col(c)}{r}", v, header=(r == 1)) for c, v in enumerate(values))
        lines.append(f'<row r="{r}">{cells}</row>')
    cols = ""
    if widths:
        cols = "<cols>" + "".join(
            f'<col min="{i}" max="{i}" width="{w}" customWidth="1"/>' for i, w in enumerate(widths, start=1)
        ) + "</cols>"
    sheet = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" '
        'activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>'
        f'{cols}<sheetData>{"".join(lines)}</sheetData>'
        f'<autoFilter ref="A1:{last_col}{len(rows) + 1}"/>'
        '</worksheet>'
    )
    styles = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<numFmts count="2"><numFmt numFmtId="164" formatCode="dd/mm/yyyy"/>'
        '<numFmt numFmtId="165" formatCode="dd/mm/yyyy hh:mm"/></numFmts>'
        '<fonts count="2"><font><sz val="11"/><name val="Calibri"/><family val="2"/></font>'
        '<font><b/><sz val="11"/><name val="Calibri"/><family val="2"/></font></fonts>'
        '<fills count="2"><fill><patternFill patternType="none"/></fill>'
        '<fill><patternFill patternType="gray125"/></fill></fills>'
        '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
        '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
        '<cellXfs count="4">'
        '<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
        '<xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1"/>'
        '<xf numFmtId="164" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>'
        '<xf numFmtId="165" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>'
        '</cellXfs>'
        '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>'
        '</styleSheet>'
    )
    safe_name = _text(sheet_name)[:31]
    files = {
        "[Content_Types].xml": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            '<Override PartName="/xl/worksheets/sheet1.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            '<Override PartName="/xl/styles.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
            '</Types>'
        ),
        "_rels/.rels": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
            'Target="xl/workbook.xml"/></Relationships>'
        ),
        "xl/workbook.xml": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            f'<sheets><sheet name="{safe_name}" sheetId="1" r:id="rId1"/></sheets>'
            '<definedNames><definedName name="_xlnm._FilterDatabase" localSheetId="0" hidden="1">'
            f"'{safe_name}'!$A$1:${last_col}${len(rows) + 1}</definedName></definedNames>"
            '</workbook>'
        ),
        "xl/_rels/workbook.xml.rels": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
            'Target="worksheets/sheet1.xml"/>'
            '<Relationship Id="rId2" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" '
            'Target="styles.xml"/></Relationships>'
        ),
        "xl/worksheets/sheet1.xml": sheet,
        "xl/styles.xml": styles,
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, content in files.items():
            zf.writestr(name, content)
    return buffer.getvalue()
