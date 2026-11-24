"""Primera instalación: crea la clínica, sus sucursales y la primera cuenta de Administración.

Se ejecuta una sola vez, en una base vacía (lo hace scripts/servidor/instalar.sh al instalar
por primera vez; en la Mac se puede correr a mano):

    python -m app.instalar_clinica --correo admin@ejemplo.com --nombre "Nombre Apellido"

Si ya hay una clínica en la base, no hace nada. Muestra UNA contraseña temporal: con ella se
entra, se elige una contraseña nueva y desde Administración se crean las demás cuentas.
"""

import argparse
import sys

from pydantic import TypeAdapter, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import audit
from app.db import get_sessionmaker
from app.models import Branch, Clinic, Role, Specialty, User
from app.schemas import Email, FullName
from app.security import hash_password, temporary_password

CLINIC_NAME = "Centro Interdisciplinario Nordeste"
BRANCHES = ("Central", "Anexo", "Pando")
SPECIALTIES = ("Psicología", "Terapia ocupacional", "Fonoaudiología")
TIMEZONE = "America/Montevideo"
# Provisorio: se cambia desde Administración → Usuarios cuando la clínica tenga su correo real.
DEFAULT_ADMIN_EMAIL = "administracion@nordeste.example.com"
DEFAULT_ADMIN_NAME = "Administración Nordeste"


def install(db: Session, admin_email: str, admin_name: str) -> str | None:
    """Crea todo y devuelve la contraseña temporal del administrador.

    Devuelve None (sin tocar nada) si la base ya tiene una clínica."""
    if db.scalar(select(Clinic.id).limit(1)):
        return None
    clinic = Clinic(name=CLINIC_NAME, timezone=TIMEZONE)
    db.add(clinic)
    db.flush()
    for name in BRANCHES:
        db.add(Branch(clinic_id=clinic.id, name=name))
    for name in SPECIALTIES:
        db.add(Specialty(clinic_id=clinic.id, name=name, is_active=True))
    password = temporary_password()
    # Administración entra a todas las sucursales activas: no necesita asignarlas.
    admin = User(clinic_id=clinic.id, email=admin_email, full_name=admin_name, role=Role.admin.value,
                 password_hash=hash_password(password), must_change_password=True)
    db.add(admin)
    db.flush()
    audit.record(db, clinic_id=clinic.id, actor_id=None, action="system.clinic_create",
                 entity_type="clinic", entity_id=clinic.id)
    audit.record(db, clinic_id=clinic.id, actor_id=None, action="system.user_create",
                 entity_type="user", entity_id=admin.id, details={"role": admin.role})
    db.commit()
    return password


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--correo", default=DEFAULT_ADMIN_EMAIL)
    parser.add_argument("--nombre", default=DEFAULT_ADMIN_NAME)
    args = parser.parse_args(argv)
    try:
        email = TypeAdapter(Email).validate_python(args.correo)
        name = TypeAdapter(FullName).validate_python(args.nombre)
    except ValidationError as exc:
        print(f"❌ Correo o nombre no válido: {exc.errors()[0]['msg']}")
        return 1
    with get_sessionmaker()() as db:
        password = install(db, email, name)
    if password is None:
        print("ℹ️  La clínica ya está creada: no se cambió nada.")
        return 0
    print(f"✅ {CLINIC_NAME} creada con las sucursales {', '.join(BRANCHES)}.")
    print("")
    print(f"   Administración:       {email}")
    print(f"   Contraseña temporal:  {password}")
    print("")
    print("   Anotala: no se vuelve a mostrar. Al entrar se pide elegir una contraseña nueva.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
