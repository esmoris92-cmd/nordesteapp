"""Avisos de Recepción y Administración a los profesionales (todo ficticio)."""

from sqlalchemy import select

from app.models import AuditEvent, Branch, UserBranch


def test_reception_notice_to_one_professional(world, login, db):
    rec = login(world.reception_a)
    lucia = login(world.lucia)
    mateo = login(world.mateo)
    names = [p["full_name"] for p in rec.get("/api/notices/recipients").json()]
    assert names == sorted([world.lucia.full_name, world.mateo.full_name])
    r = rec.post("/api/notices", json={"message": "  Llamar a la familia de Ana antes del viernes.  ",
                                       "professional_id": str(world.lucia.id)})
    assert r.status_code == 201, r.text
    notice = r.json()
    assert notice["message"] == "Llamar a la familia de Ana antes del viernes."
    assert notice["to_all"] is False and notice["branch_name"] == "Central"
    assert [x["full_name"] for x in notice["recipients"]] == [world.lucia.full_name]
    # Lucía lo ve en su barra; Mateo no.
    mine = lucia.get("/api/notices/mine").json()
    assert [n["message"] for n in mine] == [notice["message"]]
    assert mine[0]["author_name"] == world.reception_a.full_name and mine[0]["author_role"] == "reception"
    assert mateo.get("/api/notices/mine").json() == []
    # Mateo no puede marcar como leído un aviso que no es suyo.
    assert mateo.post(f"/api/notices/{notice['id']}/read").status_code == 404
    # "Entendido": desaparece de la barra y Recepción ve que fue leído.
    assert lucia.post(f"/api/notices/{notice['id']}/read").status_code == 204
    assert lucia.get("/api/notices/mine").json() == []
    sent = rec.get("/api/notices").json()
    assert sent[0]["recipients"][0]["read_at"] is not None
    actions = set(db.scalars(select(AuditEvent.action).where(AuditEvent.entity_type == "notice")))
    assert actions == {"notice.create", "notice.read"}


def test_notice_to_all_and_withdraw(world, login, db):
    admin = login(world.admin_a)
    lucia = login(world.lucia)
    r = admin.post("/api/notices", json={"message": "Mañana se corta la luz de 9 a 10."})
    assert r.status_code == 201, r.text
    notice = r.json()
    assert notice["to_all"] is True
    assert len(notice["recipients"]) == 2  # Lucía y Mateo (los activos de la clínica A)
    assert len(lucia.get("/api/notices/mine").json()) == 1
    # Retirar: deja de verse en la barra aunque no se haya leído.
    r = admin.post(f"/api/notices/{notice['id']}/withdraw")
    assert r.status_code == 200 and r.json()["withdrawn_at"] is not None
    assert lucia.get("/api/notices/mine").json() == []


def test_permissions_and_scope(world, login, db):
    rec = login(world.reception_a)
    lucia = login(world.lucia)
    # Los profesionales no dejan avisos ni ven la lista de enviados.
    assert lucia.post("/api/notices", json={"message": "Hola"}).status_code == 403
    assert lucia.get("/api/notices").status_code == 403
    # Mensaje vacío o demasiado largo.
    assert rec.post("/api/notices", json={"message": "   "}).status_code == 422
    assert rec.post("/api/notices", json={"message": "x" * 501}).status_code == 422
    # Recepción no puede avisar a un profesional de otra sucursal ni de otra clínica.
    pando = Branch(clinic_id=world.clinic_a.id, name="Pando")
    db.add(pando)
    db.flush()
    db.query(UserBranch).filter(UserBranch.user_id == world.mateo.id).update({"branch_id": pando.id})
    db.commit()
    assert rec.post("/api/notices", json={"message": "Hola", "professional_id": str(world.mateo.id)}).status_code == 422
    assert rec.post("/api/notices", json={"message": "Hola", "professional_id": str(world.bruno.id)}).status_code == 422
    # "A todos" desde Recepción: solo los de su sucursal.
    r = rec.post("/api/notices", json={"message": "Reunión de equipo el lunes."})
    assert [x["full_name"] for x in r.json()["recipients"]] == [world.lucia.full_name]
    # La otra clínica no ve ni puede retirar el aviso.
    other = login(world.admin_b)
    assert other.get("/api/notices").json() == []
    assert other.post(f"/api/notices/{r.json()['id']}/withdraw").status_code == 404
    assert login(world.bruno).get("/api/notices/mine").json() == []
