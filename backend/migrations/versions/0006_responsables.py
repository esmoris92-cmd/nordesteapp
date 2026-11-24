"""Responsables / tutores de pacientes.

Revision ID: 0006_responsables
Revises: 0005_ficha_paciente
Create Date: 2026-10-18
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0006_responsables"
down_revision = "0005_ficha_paciente"
branch_labels = None
depends_on = None

UUID = postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.create_table(
        "patient_guardians",
        sa.Column("id", UUID, primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("clinic_id", UUID, nullable=False),
        sa.Column("patient_id", UUID, nullable=False),
        sa.Column("full_name", sa.String(200), nullable=False),
        sa.Column("relationship", sa.String(60), nullable=False),
        sa.Column("phone", sa.String(40)),
        sa.Column("email", sa.String(254)),
        sa.Column("is_primary", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("notes", sa.String(300)),
        sa.Column("created_by", UUID, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["clinic_id", "patient_id"], ["patients.clinic_id", "patients.id"]),
        sa.ForeignKeyConstraint(["clinic_id", "created_by"], ["users.clinic_id", "users.id"]),
    )
    op.create_index("ix_patient_guardians_patient", "patient_guardians", ["clinic_id", "patient_id"])


def downgrade() -> None:
    op.drop_index("ix_patient_guardians_patient", table_name="patient_guardians")
    op.drop_table("patient_guardians")
