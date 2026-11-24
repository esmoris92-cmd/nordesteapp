"""Cuenta del dueño del sistema, desde la Terminal del servidor (o de la Mac, para probar).

No hay forma de crearla desde la pantalla: alguien tiene que ser el primero. Este comando
también sirve para recuperarla si perdés el celular o la contraseña.

    python -m app.dueno_sistema crear --correo vos@ejemplo.com --nombre "Tu Nombre"
    python -m app.dueno_sistema restablecer --correo vos@ejemplo.com
    python -m app.dueno_sistema listar

"crear" y "restablecer" muestran UNA contraseña temporal. Con ella entrás a /sistema, elegís
una contraseña nueva y configurás la app del celular. "restablecer" además borra el código del
celular configurado (para configurarlo de nuevo) y cierra las sesiones abiertas.
"""

import argparse
import sys

from pydantic import TypeAdapter, ValidationError
from sqlalchemy import select, update

from app.db import get_sessionmaker
from app.deps import utcnow
from app.models import OwnerSession, SystemOwner
from app.owner_deps import record
from app.schemas import Email, FullName
from app.security import hash_password, temporary_password


def _valid(adapter_type, value: str, label: str) -> str:
    try:
        return TypeAdapter(adapter_type).validate_python(value)
    except ValidationError:
        sys.exit(f"❌ {label} no válido: {value!r}")


def _show(email: str, password: str) -> None:
    print("")
    print(f"   Correo:               {email}")
    print(f"   Contraseña temporal:  {password}")
    print("")
    print("   Anotala: no se vuelve a mostrar. Entrá a https://<tu-dominio>/sistema (o")
    print("   http://localhost:8000/sistema en la Mac), elegí una contraseña nueva y configurá")
    print("   el código del celular. Hasta que lo hagas no podés usar el resto.")


def crear(email: str, name: str) -> None:
    email = _valid(Email, email, "Correo")
    name = _valid(FullName, name, "Nombre")
    with get_sessionmaker()() as db:
        if db.scalar(select(SystemOwner.id).where(SystemOwner.email == email)):
            sys.exit("❌ Ya existe una cuenta de dueño con ese correo. Para recuperarla usá: restablecer")
        password = temporary_password()
        owner = SystemOwner(email=email, full_name=name, password_hash=hash_password(password),
                            must_change_password=True)
        db.add(owner)
        db.flush()
        record(db, owner_id=owner.id, action="owner.created")
        db.commit()
    print("✅ Cuenta de dueño del sistema creada.")
    _show(email, password)


def restablecer(email: str) -> None:
    email = _valid(Email, email, "Correo")
    with get_sessionmaker()() as db:
        owner = db.scalar(select(SystemOwner).where(SystemOwner.email == email))
        if owner is None:
            sys.exit("❌ No hay ninguna cuenta de dueño con ese correo. Revisá con: listar")
        password = temporary_password()
        owner.password_hash = hash_password(password)
        owner.must_change_password = True
        owner.totp_secret = None
        owner.totp_enabled = False
        owner.totp_last_step = None
        owner.failed_login_count = 0
        owner.locked_until = None
        owner.is_active = True
        db.execute(update(OwnerSession).where(OwnerSession.owner_id == owner.id,
                                              OwnerSession.revoked_at.is_(None)).values(revoked_at=utcnow()))
        record(db, owner_id=owner.id, action="owner.reset")
        db.commit()
    print("✅ Cuenta restablecida: contraseña nueva y código del celular borrado.")
    _show(email, password)


def listar() -> None:
    with get_sessionmaker()() as db:
        owners = db.scalars(select(SystemOwner).order_by(SystemOwner.created_at)).all()
    if not owners:
        print("No hay cuentas de dueño todavía. Creá una con: crear --correo ... --nombre \"...\"")
    for o in owners:
        state = "activa" if o.is_active else "desactivada"
        code = "con código del celular" if o.totp_enabled else "SIN código del celular todavía"
        print(f"- {o.email} ({o.full_name}) · {state} · {code}")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m app.dueno_sistema",
                                     description="Cuenta del dueño del sistema de Lumen.")
    sub = parser.add_subparsers(dest="command", required=True)
    p_crear = sub.add_parser("crear", help="crea la cuenta y muestra una contraseña temporal")
    p_crear.add_argument("--correo", required=True)
    p_crear.add_argument("--nombre", required=True)
    p_rest = sub.add_parser("restablecer", help="contraseña temporal nueva y borra el código del celular")
    p_rest.add_argument("--correo", required=True)
    sub.add_parser("listar", help="muestra las cuentas de dueño")
    args = parser.parse_args(argv)
    if args.command == "crear":
        crear(args.correo, args.nombre)
    elif args.command == "restablecer":
        restablecer(args.correo)
    else:
        listar()


if __name__ == "__main__":
    main()
