"""Ficha del paciente: segundo nombre, segundo apellido, documento y sexo.

Revision ID: 0005_ficha_paciente
Revises: 0004_pacientes_simultaneos
Create Date: 2026-10-18
"""

import sqlalchemy as sa
from alembic import op

revision = "0005_ficha_paciente"
down_revision = "0004_pacientes_simultaneos"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("patients", sa.Column("middle_name", sa.String(100)))
    op.add_column("patients", sa.Column("second_last_name", sa.String(100)))
    op.add_column("patients", sa.Column("document_number", sa.String(30)))
    op.add_column("patients", sa.Column("sex", sa.String(20)))
    op.create_check_constraint(
        "ck_patients_sex", "patients", "sex IS NULL OR sex IN ('male', 'female', 'unspecified')"
    )
    op.create_index(
        "uq_patients_clinic_document", "patients", ["clinic_id", "document_number"], unique=True,
        postgresql_where=sa.text("document_number IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_patients_clinic_document", table_name="patients")
    op.drop_constraint("ck_patients_sex", "patients", type_="check")
    for col in ("sex", "document_number", "second_last_name", "middle_name"):
        op.drop_column("patients", col)
