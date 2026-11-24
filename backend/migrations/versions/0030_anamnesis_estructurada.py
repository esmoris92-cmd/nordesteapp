"""Anamnesis estructurada (ficha multidisciplinaria): una versión por cada guardado.

Revision ID: 0030_anamnesis_estructurada
Revises: 0029_motivo_ausencia
Create Date: 2026-11-02
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0030_anamnesis_estructurada"
down_revision = "0029_motivo_ausencia"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "anamnesis_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("clinic_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("patient_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("author_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("data", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["clinic_id", "patient_id"], ["patients.clinic_id", "patients.id"]),
        sa.ForeignKeyConstraint(["clinic_id", "author_id"], ["users.clinic_id", "users.id"]),
    )
    op.create_index("ix_anamnesis_versions_patient", "anamnesis_versions",
                    ["clinic_id", "patient_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_anamnesis_versions_patient", table_name="anamnesis_versions")
    op.drop_table("anamnesis_versions")
