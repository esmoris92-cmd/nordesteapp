"""Contraseñas y tokens. Usa bibliotecas probadas; no implementa criptografía propia."""

import hashlib
import hmac
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

# Argon2id con los parámetros recomendados por la biblioteca (RFC 9106).
_hasher = PasswordHasher()
# Hash de relleno para que "usuario inexistente" tarde lo mismo que "contraseña incorrecta".
_DUMMY_HASH = _hasher.hash(secrets.token_urlsafe(16))

MIN_PASSWORD_LENGTH = 12


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def burn_verify_time(password: str) -> None:
    verify_password(_DUMMY_HASH, password)


def password_needs_rehash(password_hash: str) -> bool:
    return _hasher.check_needs_rehash(password_hash)


def new_token() -> str:
    """Token aleatorio de 256 bits, apto para cookies de sesión y CSRF."""
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def tokens_equal(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


def temporary_password() -> str:
    """Contraseña temporal fácil de dictar (sin 0/O ni 1/l) y difícil de adivinar."""
    alphabet = "abcdefghjkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    groups = ["".join(secrets.choice(alphabet) for _ in range(4)) for _ in range(4)]
    return "-".join(groups)  # p. ej. "k7Pq-Xm3T-..." (19 caracteres)


def password_problem(password: str) -> str | None:
    """Devuelve un mensaje si la contraseña no cumple la política mínima."""
    if len(password) < MIN_PASSWORD_LENGTH:
        return f"La contraseña debe tener al menos {MIN_PASSWORD_LENGTH} caracteres."
    if len(password) > 128:
        return "La contraseña no puede superar los 128 caracteres."
    if password.strip() != password:
        return "La contraseña no puede empezar ni terminar con espacios."
    return None
