"""Anamnesis, entrevista y evaluación como registros clínicos."""


def test_new_kinds_are_clinical_records(world, login):
    lucia = login(world.lucia)
    pid = world.patient_a.id
    for kind in ("anamnesis", "interview", "evaluation"):
        r = lucia.post(f"/api/patients/{pid}/notes", json={"kind": kind, "content": f"Registro {kind} ficticio"})
        assert r.status_code == 201, r.text
    kinds = sorted(n["kind"] for n in lucia.get(f"/api/patients/{pid}/notes").json())
    assert kinds == ["anamnesis", "evaluation", "interview"]
    # Misma protección que la historia clínica: recepción no los ve.
    assert login(world.reception_a).get(f"/api/patients/{pid}/notes").status_code == 403


def test_corrections_keep_kind(world, login):
    lucia = login(world.lucia)
    note = lucia.post(f"/api/patients/{world.patient_a.id}/notes",
                      json={"kind": "evaluation", "content": "v1"}).json()
    r = lucia.post(f"/api/notes/{note['id']}/corrections", json={"content": "v2", "reason": "Ajuste de puntaje"})
    assert r.status_code == 201 and r.json()["kind"] == "evaluation"
