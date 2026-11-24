"""Tipos de afiliación corregidos: AYEX (en lugar de ASSE), Tutela Militar (antes
"Convenio militar") y la nueva Tutela Policial.

* Los pacientes guardados como ASSE pasan a AYEX: era un error de nombre, no otra cobertura.
* "Convenio militar" solo cambia de nombre en pantalla (Tutela Militar); el dato no cambia.

Revision ID: 0015_afiliaciones
Revises: 0014_agenda_sucursal
Create Date: 2026-10-20
"""

from alembic import op

revision = "0015_afiliaciones"
down_revision = "0014_agenda_sucursal"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("ck_patients_affiliation", "patients", type_="check")
    op.execute("UPDATE patients SET affiliation = 'ayex' WHERE affiliation = 'asse'")
    op.create_check_constraint(
        "ck_patients_affiliation", "patients",
        "affiliation IN ('private', 'ayex', 'military', 'police')",
    )


def downgrade() -> None:
    conn = op.get_bind()
    if conn.exec_driver_sql("SELECT 1 FROM patients WHERE affiliation = 'police' LIMIT 1").first():
        raise RuntimeError("Hay pacientes con Tutela Policial: cámbialos antes de volver atrás.")
    op.drop_constraint("ck_patients_affiliation", "patients", type_="check")
    op.execute("UPDATE patients SET affiliation = 'asse' WHERE affiliation = 'ayex'")
    op.create_check_constraint(
        "ck_patients_affiliation", "patients", "affiliation IN ('private', 'asse', 'military')"
    )
