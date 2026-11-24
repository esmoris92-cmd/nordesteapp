""""Eliminar" una cuenta la archiva: se oculta y desactiva, pero se conserva su historial."""

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.main import app
from app.models import AuditEvent, ClinicalNote, User
from tests.conftest import PASSWORD


def test_archive_hides_deactivates_and_keeps_history(world, login, db):
    lucia = login(world.lucia)
    lucia.post(f"/api/patients/{world.patient_a.id}/notes",
               json={"kind": "session", "content": "Nota ficticia de Lucía"})
    admin = login(world.admin_a)

    # Lucía es responsable de Ana: al eliminarla hay que elegir quién la reemplaza.
    r = admin.post(f"/api/users/{world.lucia.id}/archive", json={"reassignments": [
        {"patient_id": str(world.patient_a.id), "professional_id": str(world.mateo.id)}]})
    assert r.status_code == 200, r.text
    assert r.json()["is_active"] is False and r.json()["archived_at"] is not None

    # Sale de la lista normal, aparece con include_archived.
    assert "lucia@a.test" not in {u["email"] for u in admin.get("/api/users").json()}
    archived = {u["email"] for u in admin.get("/api/users?include_archived=true").json()}
    assert "lucia@a.test" in archived
    # Tampoco aparece para elegir en agenda o accesos.
    assert "Lucia" not in {p["full_name"] for p in admin.get("/api/professionals").json()}

    # Pierde el acceso de inmediato y no puede volver a entrar.
    assert lucia.get("/api/auth/me").status_code == 401
    r = TestClient(app).post("/api/auth/login", json={"email": "lucia@a.test", "password": PASSWORD})
    assert r.status_code == 401

    # Su historial sigue intacto: la nota conserva su autora.
    note = db.scalar(select(ClinicalNote).where(ClinicalNote.author_id == world.lucia.id))
    assert note is not None
    assert db.get(User, world.lucia.id) is not None
    actions = db.scalars(select(AuditEvent.action)).all()
    assert "user.archive" in actions


def test_restore_returns_account_deactivated(world, login):
    admin = login(world.admin_a)
    admin.post(f"/api/users/{world.mateo.id}/archive")
    # Mientras está eliminada no se puede editar.
    assert admin.patch(f"/api/users/{world.mateo.id}", json={"full_name": "X Y"}).status_code == 409
    r = admin.post(f"/api/users/{world.mateo.id}/restore")
    assert r.status_code == 200 and r.json()["archived_at"] is None
    assert r.json()["is_active"] is False  # vuelve desactivada: hay que reactivarla a propósito
    r = admin.patch(f"/api/users/{world.mateo.id}", json={"is_active": True})
    assert r.status_code == 200 and r.json()["is_active"] is True


def test_cannot_archive_self_or_twice(world, login):
    admin = login(world.admin_a)
    assert admin.post(f"/api/users/{world.admin_a.id}/archive").status_code == 409
    assert admin.post(f"/api/users/{world.mateo.id}/archive").status_code == 200
    assert admin.post(f"/api/users/{world.mateo.id}/archive").status_code == 409
    assert admin.post(f"/api/users/{world.lucia.id}/restore").status_code == 409


def test_email_of_archived_account_stays_reserved(world, login):
    admin = login(world.admin_a)
    admin.post(f"/api/users/{world.mateo.id}/archive")
    r = admin.post("/api/users", json={
        "email": "mateo@a.test", "full_name": "Otro Mateo", "role": "reception", "document_number": "5555555-5",
        "password": "contraseña-de-prueba-123",
    })
    assert r.status_code == 409 and "eliminadas" in r.json()["detail"]


def test_only_admin_of_same_clinic_can_archive(world, login):
    assert login(world.reception_a).post(f"/api/users/{world.mateo.id}/archive").status_code == 403
    assert login(world.lucia).post(f"/api/users/{world.mateo.id}/archive").status_code == 403
    assert login(world.admin_b).post(f"/api/users/{world.mateo.id}/archive").status_code == 404
    assert login(world.admin_b).post(f"/api/users/{world.mateo.id}/restore").status_code == 404
