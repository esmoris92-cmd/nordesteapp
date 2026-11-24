"""Tipo de afiliación del paciente (Privado, ASSE o Convenio militar), obligatorio.

Los pacientes que ya existían quedan como "Privado" (decisión del usuario); se corrige a
mano el que corresponda. Después se quita el valor por defecto: desde ahora cada alta debe
indicarlo.

Revision ID: 0009_tipo_afiliacion
Revises: 0008_archivos
Create Date: 2026-10-19
"""

import sqlalchemy as sa
from alembic import op

revision = "0009_tipo_afiliacion"
down_revision = "0008_archivos"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("patients", sa.Column("affiliation", sa.String(20), nullable=False,
                                        server_default="private"))
    op.create_check_constraint(
        "ck_patients_affiliation", "patients", "affiliation IN ('private', 'asse', 'military')"
    )
    op.alter_column("patients", "affiliation", server_default=None)


def downgrade() -> None:
    op.drop_constraint("ck_patients_affiliation", "patients", type_="check")
    op.drop_column("patients", "affiliation")
