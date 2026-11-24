"""Sucursal del paciente (obligatoria).

Los pacientes existentes quedan en la primera sucursal de su clínica ("Central").

Revision ID: 0013_paciente_sucursal
Revises: 0012_sucursales
Create Date: 2026-10-19
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0013_paciente_sucursal"
down_revision = "0012_sucursales"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("patients", sa.Column("branch_id", postgresql.UUID(as_uuid=True)))
    op.execute(
        "UPDATE patients p SET branch_id = (SELECT b.id FROM branches b WHERE b.clinic_id = p.clinic_id "
        "ORDER BY b.created_at, b.name LIMIT 1)"
    )
    op.alter_column("patients", "branch_id", nullable=False)
    op.create_foreign_key("fk_patients_branch", "patients", "branches",
                          ["clinic_id", "branch_id"], ["clinic_id", "id"])
    op.create_index("ix_patients_clinic_branch", "patients", ["clinic_id", "branch_id"])


def downgrade() -> None:
    op.drop_index("ix_patients_clinic_branch", table_name="patients")
    op.drop_constraint("fk_patients_branch", "patients", type_="foreignkey")
    op.drop_column("patients", "branch_id")
