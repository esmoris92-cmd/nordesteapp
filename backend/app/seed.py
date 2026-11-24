"""Carga datos de demostración 100 % FICTICIOS.

Uso (desde la carpeta backend, con el entorno virtual activo):
    python -m app.seed            # crea los datos si todavía no existen
    python -m app.seed --reiniciar  # BORRA TODO y vuelve a crearlos (pide confirmación)

Ningún nombre, nota o informe corresponde a personas reales.
Se niega a ejecutarse si ENVIRONMENT=production.
"""

import argparse
import sys
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_sessionmaker
from app.models import (
    AccessLevel,
    AffiliationType,
    Branch,
    Appointment,
    Availability,
    Clinic,
    ClinicalNote,
    Patient,
    PatientAccess,
    Report,
    Role,
    Specialty,
    User,
    UserBranch,
)
from app.security import hash_password, password_problem

ALL_TABLES = (
    "cash_movements, cash_registers, audit_log, professional_degrees, user_branches, goal_updates, treatment_goals, reports, patient_files, report_section_versions, anamnesis_versions, clinical_notes, appointments, availability, patient_access, patient_guardians, "
    "patient_institutions, patients, auth_sessions, users, specialties, branches, clinics"
)
DEMO_CLINIC_A = "Clínica Demo Aurora (ficticia)"
DEMO_CLINIC_B = "Consultorio Demo Boreal (ficticio)"
TAG = "[DATO FICTICIO] "


def _specialties(db, clinic, *names):
    """Crea las especialidades de la clínica y devuelve {nombre: especialidad}."""
    result = {}
    for name in names:
        sp = Specialty(clinic_id=clinic.id, name=name, is_active=True)
        db.add(sp)
        result[name] = sp
    db.flush()
    return result


def _user(db, clinic, email, name, role, password_hash, specialty=None):
    u = User(clinic_id=clinic.id, email=email, full_name=name, role=role.value,
             specialty_id=specialty.id if specialty else None, password_hash=password_hash)
    db.add(u)
    db.flush()
    return u


def _branch(db, clinic, name):
    br = Branch(clinic_id=clinic.id, name=name)
    db.add(br)
    db.flush()
    return br


def _patient(db, clinic, creator, first, last, birth, phone, affiliation=AffiliationType.private,
             branch=None):
    if branch is None:  # Central (las sucursales de la demo se crean en el mismo instante)
        branch = db.scalar(select(Branch).where(Branch.clinic_id == clinic.id, Branch.name == "Central"))
    p = Patient(clinic_id=clinic.id, first_name=first, last_name=last, birth_date=birth,
                phone=phone, email=None, affiliation=affiliation.value, created_by=creator.id,
                branch_id=branch.id)
    db.add(p)
    db.flush()
    return p


def _access(db, clinic, patient, user, level, granted_by, reason):
    db.add(PatientAccess(clinic_id=clinic.id, patient_id=patient.id, user_id=user.id,
                         level=level.value, granted_by=granted_by.id, reason=reason))


def _next_weekday(base: date, weekday: int) -> date:
    return base + timedelta(days=(weekday - base.weekday()) % 7)


def seed(db: Session, password: str) -> None:
    pw = hash_password(password)  # un único hash: las cuentas demo comparten contraseña

    # ---- Clínica A ----
    a = Clinic(name=DEMO_CLINIC_A, timezone="America/Montevideo")
    db.add(a)
    db.flush()
    sp_a = _specialties(db, a, "Psicología", "Terapia ocupacional", "Fonoaudiología")
    admin = _user(db, a, "admin@aurora.demo", "Admin Aurora (demo)", Role.admin, pw)
    recep = _user(db, a, "recepcion@aurora.demo", "Recepción Aurora (demo)", Role.reception, pw)
    lucia = _user(db, a, "lucia@aurora.demo", "Lic. Lucía Ficticia", Role.professional, pw,
                  sp_a["Psicología"])
    mateo = _user(db, a, "mateo@aurora.demo", "Lic. Mateo Inventado", Role.professional, pw,
                  sp_a["Terapia ocupacional"])
    sofia = _user(db, a, "sofia@aurora.demo", "Lic. Sofía Supuesta", Role.professional, pw,
                  sp_a["Psicología"])
    recep_pando = _user(db, a, "recepcion.pando@aurora.demo", "Recepción Pando (demo)", Role.reception, pw)
    recep_anexo = _user(db, a, "recepcion.anexo@aurora.demo", "Recepción Anexo (demo)", Role.reception, pw)
    central, pando, anexo = (_branch(db, a, n) for n in ("Central", "Pando", "Anexo"))
    for u, branches in ((recep, [central]), (recep_pando, [pando]), (recep_anexo, [anexo]),
                        (lucia, [central, pando]), (mateo, [central, anexo]), (sofia, [central])):
        for br in branches:
            db.add(UserBranch(user_id=u.id, branch_id=br.id, clinic_id=a.id))

    valentina = _patient(db, a, recep, "Valentina", "Ejemplo", date(1990, 3, 14), "099 000 001")
    martin = _patient(db, a, recep, "Martín", "Prueba", date(1985, 7, 2), "099 000 002",
                      AffiliationType.ayex, pando)
    carla = _patient(db, a, recep, "Carla", "Ficticia", date(2001, 11, 23), "099 000 003")
    diego = _patient(db, a, recep, "Diego", "Simulado", date(2012, 5, 9), "099 000 004",
                     AffiliationType.military, anexo)
    elena = _patient(db, a, recep, "Elena", "Muestra", date(1978, 1, 30), "099 000 005")

    for p in (valentina, martin, carla):
        _access(db, a, p, lucia, AccessLevel.responsible, admin, "Asignación inicial (demo)")
    _access(db, a, diego, mateo, AccessLevel.responsible, admin, "Asignación inicial (demo)")
    _access(db, a, elena, sofia, AccessLevel.responsible, admin, "Asignación inicial (demo)")
    # Acceso compartido interdisciplinario concedido por la responsable.
    _access(db, a, valentina, mateo, AccessLevel.collaborator, lucia,
            "Abordaje interdisciplinario (demo)")

    # Disponibilidad (hora de Montevideo), por sucursal: 09:00-13:00 y 14:00-18:00.
    #   Lucía: Central de lunes a miércoles, Pando jueves y viernes.
    #   Mateo: Central lunes, miércoles y jueves; Anexo martes y viernes.
    #   Sofía: Central de lunes a viernes.
    week = {
        lucia: {0: central, 1: central, 2: central, 3: pando, 4: pando},
        mateo: {0: central, 1: anexo, 2: central, 3: central, 4: anexo},
        sofia: {wd: central for wd in range(5)},
    }
    for prof, days in week.items():
        for wd, br in days.items():
            for start_h, end_h in ((9, 13), (14, 18)):
                db.add(Availability(clinic_id=a.id, professional_id=prof.id, branch_id=br.id,
                                    weekday=wd, start_time=time(start_h), end_time=time(end_h)))

    # Turnos de ejemplo en los próximos días hábiles, en la sucursal donde está el profesional.
    tz = ZoneInfo(a.timezone)
    today = datetime.now(tz).date()
    slots = [
        (lucia, valentina, 0, 10), (lucia, martin, 3, 11), (lucia, carla, 2, 15),
        (mateo, diego, 1, 9), (mateo, valentina, 3, 16), (sofia, elena, 4, 10),
    ]
    for prof, pat, wd, hour in slots:
        day = _next_weekday(today + timedelta(days=1), wd)
        start = datetime.combine(day, time(hour), tzinfo=tz)
        db.add(Appointment(clinic_id=a.id, patient_id=pat.id, professional_id=prof.id,
                           branch_id=week[prof][wd].id,
                           starts_at=start.astimezone(UTC),
                           ends_at=(start + timedelta(minutes=50)).astimezone(UTC),
                           created_by=recep.id))

    db.add(ClinicalNote(
        clinic_id=a.id, patient_id=valentina.id, author_id=lucia.id, kind="background",
        content=TAG + "Consulta por ansiedad ante evaluaciones laborales. Sin antecedentes "
                      "de tratamientos previos. Vive con su pareja.",
    ))
    db.add(ClinicalNote(
        clinic_id=a.id, patient_id=valentina.id, author_id=lucia.id, kind="session",
        session_date=today - timedelta(days=7),
        content=TAG + "Primera sesión. Se acuerda encuadre semanal y objetivos iniciales.",
    ))
    db.add(ClinicalNote(
        clinic_id=a.id, patient_id=diego.id, author_id=mateo.id, kind="progress",
        session_date=today - timedelta(days=3),
        content=TAG + "Mejora en motricidad fina; se sugiere continuar con actividades de enhebrado.",
    ))
    db.add(Report(
        clinic_id=a.id, patient_id=valentina.id, author_id=lucia.id,
        title="Informe de evolución (demo)",
        content=TAG + "Borrador de informe de evolución para uso de demostración.",
    ))

    # ---- Clínica B (para comprobar el aislamiento entre clínicas) ----
    b = Clinic(name=DEMO_CLINIC_B, timezone="America/Montevideo")
    db.add(b)
    db.flush()
    sp_b = _specialties(db, b, "Psicología", "Terapia ocupacional")
    admin_b = _user(db, b, "admin@boreal.demo", "Admin Boreal (demo)", Role.admin, pw)
    bruno = _user(db, b, "bruno@boreal.demo", "Lic. Bruno Imaginario", Role.professional, pw,
                  sp_b["Psicología"])
    db.add(UserBranch(user_id=bruno.id, branch_id=_branch(db, b, "Central").id, clinic_id=b.id))
    pablo = _patient(db, b, admin_b, "Pablo", "Boreal-Demo", date(1995, 9, 1), "099 000 101")
    _access(db, b, pablo, bruno, AccessLevel.responsible, admin_b, "Asignación inicial (demo)")
    db.add(ClinicalNote(clinic_id=b.id, patient_id=pablo.id, author_id=bruno.id, kind="session",
                        content=TAG + "Nota de la clínica Boreal; nadie de Aurora debe verla."))
    db.commit()


def main() -> int:
    parser = argparse.ArgumentParser(description="Carga datos de demostración ficticios.")
    parser.add_argument("--reiniciar", action="store_true",
                        help="Borra TODOS los datos de la base y vuelve a cargar la demo.")
    args = parser.parse_args()

    settings = get_settings()
    if settings.is_production:
        print("Error: no se cargan datos de demostración con ENVIRONMENT=production.")
        return 1
    password = settings.demo_password
    if not password:
        print("Error: definí DEMO_PASSWORD en backend/.env (ver .env.example).")
        return 1
    problem = password_problem(password)
    if problem:
        print(f"Error en DEMO_PASSWORD: {problem}")
        return 1

    with get_sessionmaker()() as db:
        if args.reiniciar:
            answer = input("Esto BORRA todos los datos de la base local. Escribí BORRAR para seguir: ")
            if answer.strip() != "BORRAR":
                print("Cancelado. No se borró nada.")
                return 1
            db.execute(text(f"TRUNCATE {ALL_TABLES} RESTART IDENTITY CASCADE"))
            db.commit()
        elif db.scalar(select(Clinic.id).where(Clinic.name == DEMO_CLINIC_A)):
            print("Los datos de demostración ya existen. No se cambió nada.")
            return 0
        seed(db, password)
    print("Datos de demostración (ficticios) cargados.")
    print("Cuentas: admin@aurora.demo, recepcion@aurora.demo, lucia@aurora.demo, "
          "mateo@aurora.demo, sofia@aurora.demo, admin@boreal.demo, bruno@boreal.demo")
    print("Contraseña: la definida en DEMO_PASSWORD de backend/.env")
    return 0


if __name__ == "__main__":
    sys.exit(main())
