"""Título universitario de los profesionales (foto o PDF).

Revision ID: 0020_titulo_profesional
Revises: 0019_formulario_ayex
Create Date: 2026-10-23
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0020_titulo_profesional"
down_revision = "0019_formulario_ayex"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "professional_degrees",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("clinic_id", UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", UUID(as_uuid=True), nullable=False),
        sa.Column("original_name", sa.String(200), nullable=False),
        sa.Column("content_type", sa.String(50), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("storage_key", sa.String(64), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("replaced_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(["clinic_id", "user_id"], ["users.clinic_id", "users.id"]),
    )
    op.create_index("ix_professional_degrees_user", "professional_degrees",
                    ["clinic_id", "user_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_professional_degrees_user", table_name="professional_degrees")
    op.drop_table("professional_degrees")
