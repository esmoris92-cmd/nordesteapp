"""Completar una planilla Excel (.xlsx) existente sin perder su formato.

Se usa para el Cronograma del BPS: la planilla original tiene logos, listas desplegables,
fórmulas de control de la C.I. y tablas que hay que conservar tal cual. En vez de una
librería que vuelve a escribir todo el archivo (y puede perder imágenes o validaciones), aquí
solo se reemplazan las celdas indicadas dentro del XML de cada hoja; el resto del archivo
queda intacto.

Además:
* Se borran los valores calculados guardados de las fórmulas y se pide a Excel que las
  recalcule al abrir (así no quedan datos viejos ocultos en el archivo).
* Se rehace la lista de textos compartidos con solo los que se usan (los textos de celdas
  vaciadas no quedan escondidos dentro del archivo).
"""

import io
import re
import zipfile
from xml.sax.saxutils import escape

_ROW_RE = re.compile(r"<row\b[^>]*?(?:/>|>.*?</row>)", re.S)
_ROW_NUM_RE = re.compile(r'<row\b[^>]*?\br="(\d+)"')
_CELL_RE = re.compile(r"<c\b[^>]*?(?:/>|>.*?</c>)", re.S)
_CELL_REF_RE = re.compile(r'\br="([A-Z]+)(\d+)"')
_STYLE_RE = re.compile(r'\bs="(\d+)"')
_SHEET_RE = re.compile(r'<sheet\b[^>]*?\bname="([^"]+)"[^>]*?\br:id="([^"]+)"')
_REL_RE = re.compile(r'<Relationship\b[^>]*?\bId="([^"]+)"[^>]*?\bTarget="([^"]+)"')
_INVALID_XML = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def col_number(letters: str) -> int:
    n = 0
    for ch in letters:
        n = n * 26 + (ord(ch) - 64)
    return n


def col_letters(n: int) -> str:
    out = ""
    while n:
        n, rem = divmod(n - 1, 26)
        out = chr(65 + rem) + out
    return out


def _split_ref(ref: str) -> tuple[str, int]:
    m = re.fullmatch(r"([A-Z]+)(\d+)", ref)
    if not m:
        raise ValueError(f"Referencia de celda no válida: {ref}")
    return m.group(1), int(m.group(2))


def _cell_xml(ref: str, style: str | None, value) -> str:
    s = f' s="{style}"' if style is not None else ""
    if value is None or value == "":
        return f'<c r="{ref}"{s}/>'
    if isinstance(value, bool):
        value = int(value)
    if isinstance(value, (int, float)):
        return f'<c r="{ref}"{s}><v>{value}</v></c>'
    text = escape(_INVALID_XML.sub("", str(value)))
    return f'<c r="{ref}"{s} t="inlineStr"><is><t xml:space="preserve">{text}</t></is></c>'


class _Sheet:
    """El XML de una hoja, con sus filas separadas para poder cambiar celdas rápido."""

    def __init__(self, xml: str):
        start = xml.index("<sheetData")
        open_end = xml.index(">", start) + 1
        if xml[open_end - 2] == "/":  # <sheetData/> vacía
            self.head, self.tail = xml[:start] + "<sheetData>", "</sheetData>" + xml[open_end:]
            body = ""
        else:
            end = xml.index("</sheetData>")
            self.head, self.tail = xml[:open_end], xml[end:]
            body = xml[open_end:end]
        self.rows: dict[int, str] = {}
        for m in _ROW_RE.finditer(body):
            self.rows[int(_ROW_NUM_RE.search(m.group(0)).group(1))] = m.group(0)

    def set(self, ref: str, value) -> None:
        col, row = _split_ref(ref)
        row_xml = self.rows.get(row)
        if row_xml is None:
            self.rows[row] = f'<row r="{row}">{_cell_xml(ref, None, value)}</row>'
            return
        if row_xml.endswith("/>"):  # fila vacía: <row r="5" .../>
            self.rows[row] = row_xml[:-2] + ">" + _cell_xml(ref, None, value) + "</row>"
            return
        open_end = row_xml.index(">") + 1
        head, body, tail = row_xml[:open_end], row_xml[open_end:-6], "</row>"
        cells = [m.group(0) for m in _CELL_RE.finditer(body)]
        target = col_number(col)
        for i, cell in enumerate(cells):
            c_col, _ = _CELL_REF_RE.search(cell).groups()
            n = col_number(c_col)
            if n == target:
                style = _STYLE_RE.search(cell.split(">", 1)[0])
                cells[i] = _cell_xml(ref, style.group(1) if style else None, value)
                break
            if n > target:
                cells.insert(i, _cell_xml(ref, None, value))
                break
        else:
            cells.append(_cell_xml(ref, None, value))
        self.rows[row] = head + "".join(cells) + tail

    def strip_formula_values(self) -> None:
        """Quita el último valor calculado de cada fórmula (Excel lo recalcula al abrir)."""
        def clean(match: re.Match) -> str:
            cell = match.group(0)
            if "<f" not in cell:
                return cell
            cell = re.sub(r"<v>.*?</v>", "", cell, flags=re.S)
            return re.sub(r'\st="(?:str|e|b|n)"', "", cell, count=1)
        for r, row_xml in self.rows.items():
            self.rows[r] = _CELL_RE.sub(clean, row_xml)

    def xml(self) -> str:
        return self.head + "".join(self.rows[r] for r in sorted(self.rows)) + self.tail


class XlsxTemplate:
    def __init__(self, data: bytes):
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            self._names = z.namelist()
            self._parts = {n: z.read(n) for n in self._names}
        workbook = self._parts["xl/workbook.xml"].decode("utf-8")
        rels = self._parts["xl/_rels/workbook.xml.rels"].decode("utf-8")
        targets = {rid: target.lstrip("/") for rid, target in _REL_RE.findall(rels)}
        self._sheet_paths = {
            name: (t if t.startswith("xl/") else f"xl/{t}")
            for name, rid in _SHEET_RE.findall(workbook) for t in [targets[rid]]
        }
        self._sheets: dict[str, _Sheet] = {}

    @property
    def sheet_names(self) -> list[str]:
        return list(self._sheet_paths)

    def _sheet(self, name: str) -> _Sheet:
        if name not in self._sheets:
            self._sheets[name] = _Sheet(self._parts[self._sheet_paths[name]].decode("utf-8"))
        return self._sheets[name]

    def set(self, sheet: str, ref: str, value) -> None:
        self._sheet(sheet).set(ref, value)

    def set_row(self, sheet: str, row: int, first_col: str, values: list) -> None:
        start = col_number(first_col)
        for i, value in enumerate(values):
            self.set(sheet, f"{col_letters(start + i)}{row}", value)

    def clear_range(self, sheet: str, first_col: str, last_col: str, first_row: int, last_row: int) -> None:
        sh = self._sheet(sheet)
        a, b = col_number(first_col), col_number(last_col)
        for r in [r for r in sh.rows if first_row <= r <= last_row]:
            for c in range(a, b + 1):
                ref = f"{col_letters(c)}{r}"
                if f'r="{ref}"' in sh.rows[r]:
                    sh.set(ref, None)

    def max_row(self, sheet: str) -> int:
        rows = self._sheet(sheet).rows
        return max(rows) if rows else 0

    def save(self) -> bytes:
        for name in self._sheet_paths:
            self._sheet(name).strip_formula_values()
        for name, sheet in self._sheets.items():
            self._parts[self._sheet_paths[name]] = sheet.xml().encode("utf-8")
        self._rebuild_shared_strings()
        self._recalculate_on_open()
        out = io.BytesIO()
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
            for n in self._names:
                z.writestr(n, self._parts[n])
        return out.getvalue()

    def _recalculate_on_open(self) -> None:
        wb = self._parts["xl/workbook.xml"].decode("utf-8")
        if "<calcPr" in wb:
            wb = re.sub(r"<calcPr\b([^>]*?)/?>",
                        lambda m: "<calcPr" + re.sub(r'\sfullCalcOnLoad="[^"]*"', "", m.group(1).rstrip("/"))
                        + ' fullCalcOnLoad="1"/>', wb, count=1)
        else:
            wb = wb.replace("</workbook>", '<calcPr fullCalcOnLoad="1"/></workbook>')
        self._parts["xl/workbook.xml"] = wb.encode("utf-8")

    def _rebuild_shared_strings(self) -> None:
        path = "xl/sharedStrings.xml"
        if path not in self._parts:
            return
        sst = self._parts[path].decode("utf-8")
        items = re.findall(r"<si>.*?</si>|<si/>", sst, re.S)
        used: dict[int, int] = {}
        pattern = re.compile(r'(<c\b[^>]*\bt="s"[^>]*>\s*<v>)(\d+)(</v>)')
        sheets = {n: self._parts[p].decode("utf-8") for n, p in self._sheet_paths.items()}
        count = 0
        for text in sheets.values():
            for m in pattern.finditer(text):
                count += 1
                old = int(m.group(2))
                if old not in used:
                    used[old] = len(used)
        for n, text in sheets.items():
            text = pattern.sub(lambda m: f"{m.group(1)}{used[int(m.group(2))]}{m.group(3)}", text)
            self._parts[self._sheet_paths[n]] = text.encode("utf-8")
        new_items = [items[old] for old, _ in sorted(used.items(), key=lambda kv: kv[1])]
        head = sst[:sst.index("<sst")]
        open_tag = re.search(r"<sst\b[^>]*>", sst).group(0)
        open_tag = re.sub(r'\scount="\d+"', f' count="{count}"', open_tag)
        open_tag = re.sub(r'\suniqueCount="\d+"', f' uniqueCount="{len(new_items)}"', open_tag)
        self._parts[path] = (head + open_tag + "".join(new_items) + "</sst>").encode("utf-8")

    def replace_in_part(self, name: str, pattern: str, repl: str) -> None:
        """Para datos fuera de las hojas (autor de comentarios, propiedades del archivo)."""
        if name in self._parts:
            text = self._parts[name].decode("utf-8")
            self._parts[name] = re.sub(pattern, repl, text, flags=re.S).encode("utf-8")
