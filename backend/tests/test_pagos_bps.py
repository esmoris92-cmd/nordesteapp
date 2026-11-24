"""Control de los pagos AYEX del BPS: lectura del PDF "Detalle de Item Facturable",
comparación con el arancel y con los pacientes, Excel, permisos y aislamiento entre
clínicas. Todos los datos son ficticios (el PDF se arma acá mismo)."""

import io
import zipfile
from datetime import date

from sqlalchemy import select

from app.bps_payments import read_statement
from app.models import AuditEvent, Branch, Patient

URL = "/api/bps-payments/check"
CLINIC_HEADER = "CLINICA FICTICIA DE PRUEBA - (000000000000)"


def _pdf(pages: list[list[str]]) -> bytes:
    """Un PDF mínimo con texto real: cada página es una lista de renglones."""
    objects = ["<< /Type /Catalog /Pages 2 0 R >>", None,
               "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>"]
    kids = []
    for lines in pages:
        ops = []
        for i, line in enumerate(lines):
            text = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
            ops.append(f"BT /F1 8 Tf 36 {800 - i * 12} Td ({text}) Tj ET")
        stream = "\n".join(ops).encode("latin-1")
        objects.append(f"<< /Length {len(stream)} >>\nstream\n".encode("latin-1") + stream + b"\nendstream")
        content_id = len(objects)
        objects.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 842 842] "
                       f"/Resources << /Font << /F1 3 0 R >> >> /Contents {content_id} 0 R >>")
        kids.append(len(objects))
    objects[1] = f"<< /Type /Pages /Kids [{' '.join(f'{k} 0 R' for k in kids)}] /Count {len(kids)} >>"
    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets = []
    for n, obj in enumerate(objects, start=1):
        offsets.append(out.tell())
        body = obj if isinstance(obj, bytes) else obj.encode("latin-1")
        out.write(f"{n} 0 obj\n".encode() + body + b"\nendobj\n")
    xref = out.tell()
    out.write(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode())
    for off in offsets:
        out.write(f"{off:010d} 00000 n \n".encode())
    out.write(f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    return out.getvalue()


def _row(doc: str, amount: float, name: str, month: str = "09/2026", qty: str = "1.0") -> list[str]:
    """Una fila como la escribe el BPS: el número en tres renglones y el resto en uno; el nombre
    largo sigue en el renglón siguiente."""
    first, _, rest = name.partition("|")
    lines = ["16501543-", "100000001-", "202609-00000",
             f"01-10-2026 01-10-2026 AYEX - TIPO AYUDA INSTITUTO {qty} {amount:.1f} {month} {doc} {first}"]
    if rest:
        lines.append(rest)
    return lines


def _statement(rows: list[list[str]], total: float | None = None, per_page: int = 3) -> bytes:
    if total is None:
        total = sum(float(r[3].split()[8]) for r in rows)
    pages = []
    for start in range(0, len(rows), per_page):
        lines = []
        if start == 0:
            lines += ["Detalle de Item Facturable", f"Tipo de Item AYEX Importe Item {total:.1f} Fecha Factura 03-10-2026"]
        for r in rows[start:start + per_page]:
            lines += r
        lines += [CLINIC_HEADER, f"30/10/26 17:30 Página {len(pages) + 1}"]
        pages.append(lines)
    return _pdf(pages)


def _patient(db, world, doc, first, last, affiliation="ayex", status="active", clinic="a", expires=None):
    c, branch = (world.clinic_a, world.branch_a) if clinic == "a" else (world.clinic_b, world.branch_b)
    creator = world.reception_a if clinic == "a" else world.admin_b
    p = Patient(clinic_id=c.id, first_name=first, last_name=last, affiliation=affiliation,
                status=status, document_number=doc, created_by=creator.id, branch_id=branch.id,
                ayex_expires_on=expires)
    db.add(p)
    db.commit()
    return p


def _upload(client, data: bytes, url: str = URL):
    return client.post(url, content=data, headers={"Content-Type": "application/octet-stream"})


def _set_fee(client, fee=8238):
    r = client.patch("/api/clinic", json={"ayex_fee": fee})
    assert r.status_code == 200, r.text
    return r


# ---------- Lectura del PDF ----------


def test_reads_rows_wrapped_names_and_invoice_total():
    data = _statement([
        _row("11111111", 8238, "ANA - FICTICIA PRUEBA"),
        _row("22222222", 7208, "BRUNO TOMAS INVENTADO|SUPUESTO"),
        _row("33333333", 8238, "CARLA - DEMO"),
        _row("44444444", 5149, "DIEGO - EJEMPLO"),
    ])
    s = read_statement(data)
    assert [(r.document, float(r.amount), r.month) for r in s.rows] == [
        ("11111111", 8238, "09/2026"), ("22222222", 7208, "09/2026"),
        ("33333333", 8238, "09/2026"), ("44444444", 5149, "09/2026")]
    # El nombre sigue en el renglón siguiente; el encabezado con el RUT (tiene números) no se suma.
    assert s.rows[1].name == "BRUNO TOMAS INVENTADO SUPUESTO"
    assert s.rows[2].name == "CARLA - DEMO"
    assert float(s.invoice_total) == 8238 * 2 + 7208 + 5149


# ---------- Comparación ----------


def test_fee_required_and_who_can_use_it(world, login):
    admin = login(world.admin_a)
    data = _statement([_row("11111111", 8238, "ANA - FICTICIA")])
    r = _upload(admin, data)
    assert r.status_code == 409 and "arancel" in r.json()["detail"]
    # Recepción también usa Pagos BPS (llega hasta el control del arancel).
    reception = login(world.reception_a)
    r = _upload(reception, data)
    assert r.status_code == 409 and "arancel" in r.json()["detail"]
    # Los profesionales no.
    lucia = login(world.lucia)
    assert _upload(lucia, data).status_code == 403
    assert _upload(lucia, data, URL + "/xlsx").status_code == 403
    # Solo Administración cambia el arancel.
    assert login(world.reception_a).patch("/api/clinic", json={"ayex_fee": 1}).status_code == 403
    assert admin.patch("/api/clinic", json={"ayex_fee": 0}).status_code == 422
    assert _set_fee(admin).json()["ayex_fee"] == 8238


def test_finds_every_kind_of_problem(world, login, db):
    admin = login(world.admin_a)
    _set_fee(admin)
    ok = _patient(db, world, "1.111.111-1", "Ana", "Ficticia")
    under = _patient(db, world, "22222222", "Bruno", "Inventado")
    missing = _patient(db, world, "33333333", "Carla", "Demo")
    _patient(db, world, "44444444", "Diego", "Privado", affiliation="private")
    _patient(db, world, "66666666", "Ema", "Vencida", expires=date(2026, 8, 31))
    _patient(db, world, None, "Fede", "SinDocumento")
    _patient(db, world, "77777777", "Gala", "DeAlta", status="discharged")  # no se espera en el PDF
    _patient(db, world, "55555555", "Otro", "DeClinicaB", clinic="b")       # de otra clínica

    data = _statement([
        _row("11111111", 8238, "ANA - FICTICIA"),
        _row("22222222", 7208, "BRUNO - INVENTADO"),
        _row("44444444", 8238, "DIEGO - PRIVADO"),
        _row("55555555", 8238, "OTRO - DE CLINICA B"),
        _row("11111111", 8238, "ANA - FICTICIA"),
    ])
    r = _upload(admin, data)
    assert r.status_code == 200, r.text
    out = r.json()
    assert (out["row_count"], out["ok_count"], out["fee"]) == (5, 1, 8238)
    assert out["months"] == ["09/2026"]
    assert out["totals_match"] is True and out["rows_total"] == out["invoice_total"]
    assert out["missing_amount"] == 1030
    found = {(i["kind"], i["document"]) for i in out["issues"]}
    assert found == {
        ("duplicate", "11111111"),
        ("underpaid", "22222222"),
        ("not_ayex", "44444444"),
        ("not_patient", "55555555"),     # el paciente de la clínica B no cuenta para la A
        ("not_in_bps", "33333333"),
        ("not_in_bps", "66666666"),
        ("not_in_bps", None),
    }
    by_kind = {i["kind"]: i for i in out["issues"] if i["kind"] != "not_in_bps"}
    assert by_kind["underpaid"]["difference"] == -1030
    assert by_kind["underpaid"]["name"] == "Bruno Inventado"  # el nombre de Lumen
    assert by_kind["underpaid"]["patient_id"] == str(under.id)
    assert by_kind["underpaid"]["branch_name"] == "Central"
    assert by_kind["duplicate"]["patient_id"] == str(ok.id)
    notes = {i["name"]: i["note"] for i in out["issues"] if i["kind"] == "not_in_bps"}
    assert notes["Carla Demo"] is None and missing.id
    assert "venció el 31/08/2026" in notes["Ema Vencida"]
    assert "documento" in notes["Fede SinDocumento"]


def test_totals_that_do_not_match_and_overpaid(world, login, db):
    admin = login(world.admin_a)
    _set_fee(admin)
    _patient(db, world, "11111111", "Ana", "Ficticia")
    data = _statement([_row("11111111", 9000, "ANA - FICTICIA")], total=20000)
    out = _upload(admin, data).json()
    assert out["totals_match"] is False and out["invoice_total"] == 20000
    assert [(i["kind"], i["difference"]) for i in out["issues"]] == [("overpaid", 762)]
    assert out["missing_amount"] == 0


def test_bad_files(world, login):
    admin = login(world.admin_a)
    _set_fee(admin)
    r = _upload(admin, b"documento;nombre\n1;Ana\n")
    assert r.status_code == 422 and "no es un PDF" in r.json()["detail"]
    r = _upload(admin, _pdf([["Un PDF cualquiera", "sin pagos del BPS"]]))
    assert r.status_code == 422 and "No se encontraron pagos" in r.json()["detail"]
    r = _upload(admin, b"%PDF-1.4 roto")
    assert r.status_code == 422
    assert _upload(admin, b"").status_code == 422


def test_excel_and_audit_without_personal_data(world, login, db):
    admin = login(world.admin_a)
    _set_fee(admin)
    _patient(db, world, "22222222", "Bruno", "Inventado")
    data = _statement([_row("22222222", 5149, "BRUNO - INVENTADO")])
    r = _upload(admin, data, URL + "/xlsx")
    assert r.status_code == 200, r.text
    assert 'lumen-control-pagos-bps-09-2026.xlsx' in r.headers["content-disposition"]
    sheet = zipfile.ZipFile(io.BytesIO(r.content)).read("xl/worksheets/sheet1.xml").decode()
    assert "Pago menor" in sheet and "22222222" in sheet and "-3089" in sheet
    db.expire_all()
    events = db.scalars(select(AuditEvent).where(AuditEvent.clinic_id == world.clinic_a.id,
                                                 AuditEvent.action.like("bps_payments.%"))).all()
    assert [e.action for e in events] == ["bps_payments.export"]
    assert events[0].details == {"count": 1}


def test_reception_sees_every_branch_like_admin(world, login, db):
    """Recepción ve el control de todas las sucursales, igual que Administración, aunque
    tenga asignada una sola (la de Recepción A es Central)."""
    admin = login(world.admin_a)
    _set_fee(admin)
    pando = Branch(clinic_id=world.clinic_a.id, name="Pando")
    db.add(pando)
    db.commit()
    _patient(db, world, "11111111", "Ana", "Ficticia")
    lejos = _patient(db, world, "88888888", "Hugo", "DePando")
    lejos.branch_id = pando.id
    db.commit()

    data = _statement([_row("11111111", 8238, "ANA - FICTICIA")])
    r_admin = _upload(admin, data)
    r_reception = _upload(login(world.reception_a), data)
    assert r_admin.status_code == 200 and r_reception.status_code == 200, r_reception.text
    assert r_reception.json() == r_admin.json()
    missing = [i for i in r_reception.json()["issues"] if i["kind"] == "not_in_bps"]
    assert [(i["document"], i["branch_name"]) for i in missing] == [("88888888", "Pando")]
    # El Excel también funciona para Recepción y queda en la auditoría a su nombre.
    x = _upload(login(world.reception_a), data, URL + "/xlsx")
    assert x.status_code == 200
    db.expire_all()
    actors = db.scalars(select(AuditEvent.actor_id).where(AuditEvent.action == "bps_payments.export")).all()
    assert world.reception_a.id in actors
