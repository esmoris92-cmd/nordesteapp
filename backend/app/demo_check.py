"""Revisa que ninguna cuenta activa siga con la contraseña de demostración.

Se usa antes de abrir Lumen por internet (scripts/demo-internet.sh): la contraseña de
demostración figura en la documentación, así que cualquiera podría entrar con ella.

    python -m app.demo_check      (sale con código 1 si alguna cuenta todavía la usa)

No muestra contraseñas: solo los correos de las cuentas a cambiar.
"""

import sys

from sqlalchemy import select

from app.config import get_settings
from app.db import get_sessionmaker
from app.models import User
from app.security import verify_password


def accounts_with_demo_password() -> list[str]:
    demo = get_settings().demo_password
    if not demo:
        return []
    with get_sessionmaker()() as db:
        users = db.scalars(select(User).where(User.is_active.is_(True), User.archived_at.is_(None))).all()
        return sorted(u.email for u in users if verify_password(u.password_hash, demo))


def main() -> int:
    emails = accounts_with_demo_password()
    if not emails:
        print("✅ Ninguna cuenta activa usa la contraseña de demostración.")
        return 0
    print("❌ Estas cuentas todavía usan la contraseña de demostración (figura en el README):")
    for email in emails:
        print(f"   - {email}")
    print("   Cambialas antes de abrir Lumen por internet:")
    print("   - la tuya: entrá con esa cuenta → Mi cuenta → cambiar contraseña;")
    print("   - las demás: como administración de esa clínica → Usuarios → \"Restablecer")
    print("     contraseña\" (o \"Desactivar\" las que no uses).")
    return 1


if __name__ == "__main__":
    sys.exit(main())
