"""Lectura del "Detalle de Item Facturable" que el BPS manda cada mes (PDF) con los pagos
de AYEX, y comparación con el arancel de la clínica y con sus pacientes.

El PDF trae texto real (no es una imagen), así que se lee con pypdf. Cada fila tiene:
número, fecha de ejecución, fecha de emisión, concepto, cantidad, importe, mes de cargo,
documento y nombre del beneficiario. El nombre puede ocupar más de un renglón; termina
en el primer renglón que tenga números (la fila siguiente, el pie de página o el
encabezado con el RUT de la clínica).

Privacidad: el PDF no se guarda en ningún lado. Se lee en memoria y se descarta.
"""

import io
import logging
import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

from pypdf import PdfReader
from pypdf.errors import PdfReadError

MAX_PAGES = 200

# Los datos fijos de una fila, desde la fecha de ejecución hasta el documento. Entre un
# campo y otro puede haber espacios o saltos de renglón, según cómo se armó el PDF.
_ROW = re.compile(
    r"(?P<exec>\d{2}-\d{2}-\d{4})\s+(?P<issued>\d{2}-\d{2}-\d{4})\s+"
    r"(?P<concept>[A-ZÁÉÍÓÚÑ][^\n\d]*?)\s+"
    r"(?P<qty>\d+(?:\.\d+)?)\s+(?P<amount>\d+(?:\.\d+)?)\s+"
    r"(?P<month>\d{2}/\d{4})\s+(?P<doc>\d{5,12})[ \t]*"
)
_HEADER_TOTAL = re.compile(r"Importe\s+Item\s+(\d+(?:\.\d+)?)")
_MAX_NAME_LINES = 3


class BpsPdfError(ValueError):
    """El archivo no es un PDF legible o no tiene filas del BPS."""


@dataclass
class BpsRow:
    document: str
    name: str
    month: str          # "09/2026"
    concept: str
    quantity: Decimal
    amount: Decimal


@dataclass
class BpsStatement:
    rows: list[BpsRow] = field(default_factory=list)
    invoice_total: Decimal | None = None  # "Importe Item" del encabezado


def _name_after(text: str, start: int) -> str:
    """El nombre: lo que queda del renglón y los renglones siguientes sin números."""
    lines = text[start:].split("\n")
    parts = [lines[0].strip()] if lines[0].strip() else []
    for line in lines[1:]:
        if len(parts) >= _MAX_NAME_LINES or not line.strip() or re.search(r"\d", line):
            break
        parts.append(line.strip())
    return " ".join(" ".join(parts).split())


def _decimal(text: str) -> Decimal:
    try:
        return Decimal(text)
    except InvalidOperation as exc:  # pragma: no cover - la expresión ya garantiza números
        raise BpsPdfError("El PDF tiene un importe que no se pudo leer.") from exc


def read_statement(data: bytes) -> BpsStatement:
    if not data.startswith(b"%PDF"):
        raise BpsPdfError("El archivo no es un PDF. Subí el PDF tal como lo manda el BPS.")
    # pypdf avisa por el registro cuando un PDF tiene detalles raros; no hace falta.
    logging.getLogger("pypdf").setLevel(logging.ERROR)
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            raise BpsPdfError("El PDF está protegido con contraseña: no se puede leer.")
        if len(reader.pages) > MAX_PAGES:
            raise BpsPdfError(f"El PDF tiene más de {MAX_PAGES} páginas.")
        texts = [(page.extract_text() or "").replace("\r", "") for page in reader.pages]
    except BpsPdfError:
        raise
    except (PdfReadError, ValueError, KeyError, TypeError, IndexError, OSError) as exc:
        raise BpsPdfError("No se pudo leer el PDF. Revisá que sea el archivo original del BPS.") from exc

    statement = BpsStatement()
    for i, text in enumerate(texts):
        if i == 0:
            total = _HEADER_TOTAL.search(text)
            if total:
                statement.invoice_total = _decimal(total.group(1))
        for m in _ROW.finditer(text):
            statement.rows.append(BpsRow(
                document=m.group("doc"),
                name=_name_after(text, m.end()),
                month=m.group("month"),
                concept=" ".join(m.group("concept").split()),
                quantity=_decimal(m.group("qty")),
                amount=_decimal(m.group("amount")),
            ))
    if not statement.rows:
        raise BpsPdfError(
            "No se encontraron pagos en el PDF. Tiene que ser el «Detalle de Item Facturable» del BPS "
            "(si es una foto o un escaneo, no se puede leer)."
        )
    return statement
