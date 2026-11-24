"""Leer los valores de una hoja de un Excel (.xlsx) sin librerías externas.

Se usa para importar pacientes desde el Cronograma del BPS. Solo se leen los valores de las
celdas (no formatos, imágenes ni listas desplegables). Para una fórmula se toma el último
resultado que guardó Excel.

Como el archivo viene de afuera, se lee con cuidado:
* Límite de tamaño descomprimido (un .xlsx es un ZIP y podría "inflarse" muchísimo).
* Se rechaza cualquier XML con DOCTYPE o ENTITY: un .xlsx normal no los usa y podrían
  servir para trucos que agoten la memoria.
"""

import io
import math
import posixpath
import re
import zipfile
import xml.etree.ElementTree as ET

MAX_TOTAL_BYTES = 60 * 1024 * 1024  # todo el archivo, descomprimido
MAX_PART_BYTES = 25 * 1024 * 1024   # cada XML que se lee

_REF_RE = re.compile(r"([A-Z]+)(\d+)$")

Value = str | int | float


class XlsxReadError(ValueError):
    """El archivo no es un Excel (.xlsx) que se pueda leer."""


def is_xlsx(data: bytes) -> bool:
    """Un .xlsx es un ZIP: empieza con "PK"."""
    return data[:4] == b"PK\x03\x04"


def _local(tag: str) -> str:
    """'{espacio de nombres}row' -> 'row' (así sirve para cualquier variante de Excel)."""
    return tag.rsplit("}", 1)[-1]


def _children(element, name: str):
    return [c for c in element if _local(c.tag) == name]


def _child(element, name: str):
    return next((c for c in element if _local(c.tag) == name), None)


def _col_number(letters: str) -> int:
    n = 0
    for ch in letters:
        n = n * 26 + (ord(ch) - 64)
    return n


def _rich_text(element) -> str:
    """Texto de un <si> o <is>: puede venir entero (<t>) o en partes con formato (<r><t>).
    Las ayudas de pronunciación (<rPh>) se ignoran."""
    parts = []
    for child in element:
        name = _local(child.tag)
        if name == "t":
            parts.append(child.text or "")
        elif name == "r":
            t = _child(child, "t")
            parts.append(t.text or "" if t is not None else "")
    return "".join(parts)


def _number(text: str) -> Value:
    """'12345678' o '1.2345678E7' -> 12345678 (entero si no tiene decimales)."""
    try:
        value = float(text)
    except ValueError:
        return text
    if math.isfinite(value) and value.is_integer() and abs(value) < 1e15:
        return int(value)
    return value


class XlsxReader:
    def __init__(self, data: bytes):
        try:
            self._zip = zipfile.ZipFile(io.BytesIO(data))
        except zipfile.BadZipFile:
            raise XlsxReadError("El archivo no es un Excel (.xlsx) válido o está dañado.") from None
        if sum(info.file_size for info in self._zip.infolist()) > MAX_TOTAL_BYTES:
            raise XlsxReadError("El Excel es demasiado grande.")
        workbook = self._xml("xl/workbook.xml")
        rels = self._relationships("xl/_rels/workbook.xml.rels")
        self._sheets: dict[str, str] = {}
        sheets = _child(workbook, "sheets")
        for sheet in (_children(sheets, "sheet") if sheets is not None else []):
            rid = next((v for k, v in sheet.attrib.items() if _local(k) == "id"), None)
            if sheet.get("name") and rid in rels:
                self._sheets[sheet.get("name")] = rels[rid][1]
        strings_path = next((path for kind, path in rels.values() if kind.endswith("/sharedStrings")), None)
        self._shared: list[str] = []
        if strings_path:
            self._shared = [_rich_text(si) for si in _children(self._xml(strings_path), "si")]

    def _xml(self, name: str):
        try:
            info = self._zip.getinfo(name)
        except KeyError:
            raise XlsxReadError("El archivo no es un Excel (.xlsx) válido o está dañado.") from None
        if info.file_size > MAX_PART_BYTES:
            raise XlsxReadError("El Excel es demasiado grande.")
        raw = self._zip.read(info)
        if b"<!DOCTYPE" in raw or b"<!ENTITY" in raw:
            raise XlsxReadError("El Excel tiene contenido no permitido.")
        try:
            return ET.fromstring(raw)
        except ET.ParseError:
            raise XlsxReadError("El archivo no es un Excel (.xlsx) válido o está dañado.") from None

    def _relationships(self, name: str) -> dict[str, tuple[str, str]]:
        """{Id: (tipo, ruta dentro del ZIP)}."""
        out = {}
        for rel in self._xml(name):
            target = rel.get("Target") or ""
            if rel.get("TargetMode") == "External" or not target:
                continue
            path = target.lstrip("/") if target.startswith("/") else posixpath.normpath(posixpath.join("xl", target))
            out[rel.get("Id")] = (rel.get("Type") or "", path)
        return out

    def sheet_names(self) -> list[str]:
        return list(self._sheets)

    def rows(self, sheet: str, last_col: int) -> list[tuple[int, list[Value | None]]]:
        """Filas de la hoja con sus valores de la columna A hasta ``last_col`` (1 = A).

        Cada fila: (número de fila de Excel, [valores]). Una celda vacía es None; un texto
        llega como str (sin espacios al principio ni al final) y un número como int o float.
        Las filas sin ningún valor en esas columnas no se devuelven.
        """
        root = self._xml(self._sheets[sheet])
        data = _child(root, "sheetData")
        out = []
        row_number = 0
        for row in (_children(data, "row") if data is not None else []):
            row_number = int(row.get("r")) if (row.get("r") or "").isdigit() else row_number + 1
            values: list[Value | None] = [None] * last_col
            col = 0
            for cell in _children(row, "c"):
                m = _REF_RE.match(cell.get("r") or "")
                col = _col_number(m.group(1)) if m else col + 1
                if col <= last_col:
                    values[col - 1] = self._value(cell)
            if any(v not in (None, "") for v in values):
                out.append((row_number, values))
        return out

    def _value(self, cell) -> Value | None:
        kind = cell.get("t", "n")
        if kind == "inlineStr":
            inline = _child(cell, "is")
            return _rich_text(inline).strip() if inline is not None else None
        v = _child(cell, "v")
        if v is None or v.text is None:
            return None
        text = v.text
        if kind == "s":
            index = int(text) if text.isdigit() else -1
            return self._shared[index].strip() if 0 <= index < len(self._shared) else None
        if kind == "str":
            return text.strip()
        if kind == "e":  # error de fórmula (#N/A, #REF!...): como si estuviera vacía
            return None
        if kind == "b":
            return text
        return _number(text)
