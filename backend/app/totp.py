"""Códigos de 6 dígitos de una app del celular (Google Authenticator, Microsoft
Authenticator, etc.) para el segundo paso al entrar como dueño del sistema.

Es el estándar TOTP (RFC 6238), que usan todas esas apps: el celular y el servidor comparten
una clave secreta y calculan el mismo código cada 30 segundos con HMAC-SHA1. Solo usa las
funciones criptográficas de la biblioteca estándar de Python (hmac, hashlib, secrets); no hay
criptografía propia.
"""

import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote

STEP_SECONDS = 30
DIGITS = 6
ISSUER = "Nordeste"


def new_secret() -> str:
    """Clave nueva de 160 bits en base32 (el formato que piden las apps)."""
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")


def _key(secret: str) -> bytes:
    secret = secret.replace(" ", "").upper()
    return base64.b32decode(secret + "=" * (-len(secret) % 8))


def code_at(secret: str, step: int) -> str:
    digest = hmac.new(_key(secret), struct.pack(">Q", step), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    number = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(number % 10**DIGITS).zfill(DIGITS)


def current_step(now: float | None = None) -> int:
    return int((time.time() if now is None else now) // STEP_SECONDS)


def verify(secret: str, code: str, last_step: int | None, now: float | None = None) -> int | None:
    """Si el código es válido devuelve su "paso" (para guardarlo); si no, None.

    Acepta el código anterior y el siguiente (por si el reloj del celular está un poco
    corrido) y nunca uno ya usado: un código robado no sirve para entrar de nuevo.
    """
    code = "".join(ch for ch in (code or "") if ch.isdigit())
    if len(code) != DIGITS:
        return None
    now_step = current_step(now)
    for step in (now_step - 1, now_step, now_step + 1):
        if last_step is not None and step <= last_step:
            continue
        if hmac.compare_digest(code_at(secret, step), code):
            return step
    return None


def provisioning_uri(secret: str, account: str) -> str:
    """Enlace otpauth:// que entienden las apps (también sirve para generar un código QR)."""
    label = quote(f"{ISSUER}:{account}", safe=":@")
    return f"otpauth://totp/{label}?secret={secret}&issuer={ISSUER}&digits={DIGITS}&period={STEP_SECONDS}"


def grouped(secret: str) -> str:
    """'ABCDEFGH...' -> 'ABCD EFGH ...': más fácil de copiar a mano en la app."""
    return " ".join(secret[i:i + 4] for i in range(0, len(secret), 4))
