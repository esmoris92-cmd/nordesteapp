"""Configuración de Nordeste.

Los valores se leen de variables de entorno o del archivo ``backend/.env``.
Nunca escribas contraseñas ni claves directamente en el código.
"""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env", env_file_encoding="utf-8", extra="ignore"
    )

    environment: str = "development"
    # Obligatoria: sin valor por defecto para no esconder credenciales en el código.
    database_url: str
    test_database_url: str | None = None

    session_max_hours: int = 8
    session_idle_minutes: int = 60
    cookie_secure: bool = False

    login_max_failures: int = 5
    login_lock_minutes: int = 15

    # Carpeta donde se guardan los archivos adjuntos (fuera de la carpeta pública).
    files_dir: str = str(BACKEND_DIR / "storage" / "files")
    max_upload_mb: int = 10

    # Carpeta de las copias de seguridad: FUERA del proyecto, para que nunca se suban a Git.
    backup_dir: str = str(Path.home() / "MedFlow-copias")

    @property
    def is_production(self) -> bool:
        return self.environment.lower() == "production"

    @property
    def secure_cookies(self) -> bool:
        # En producción la cookie siempre exige HTTPS, aunque alguien olvide configurarlo.
        return self.cookie_secure or self.is_production


@lru_cache
def get_settings() -> Settings:
    return Settings()
