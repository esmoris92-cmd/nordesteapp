"""La revisión previa a abrir MedFlow por internet detecta la contraseña de demostración."""

from app import demo_check
from app.security import hash_password
from tests.conftest import PASSWORD


def test_detects_accounts_with_demo_password(world, db, monkeypatch):
    class FakeSettings:
        demo_password = PASSWORD  # en las pruebas, todas las cuentas usan esta contraseña

    monkeypatch.setattr(demo_check, "get_settings", lambda: FakeSettings())
    found = demo_check.accounts_with_demo_password()
    assert world.admin_a.email in found and world.reception_a.email in found
    for user in (world.admin_a, world.reception_a):
        db.get(type(user), user.id).password_hash = hash_password("Otra-Clave-Ficticia-2026")
    db.commit()
    found = demo_check.accounts_with_demo_password()
    assert world.admin_a.email not in found and world.reception_a.email not in found
    assert demo_check.main() == 1  # todavía quedan otras cuentas de prueba con esa contraseña

    class NoDemo:
        demo_password = None

    monkeypatch.setattr(demo_check, "get_settings", lambda: NoDemo())
    assert demo_check.accounts_with_demo_password() == [] and demo_check.main() == 0
