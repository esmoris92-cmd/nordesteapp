"""Avisos de Recepción y Administración a los profesionales.

Revision ID: 0023_avisos
Revises: 0022_cronograma_bps
Create Date: 2026-10-24
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0023_avisos"
down_revision = "0022_cronograma_bps"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "notices",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("clinic_id", UUID(as_uuid=True), nullable=False),
        sa.Column("author_id", UUID(as_uuid=True), nullable=False),
        sa.Column("branch_id", UUID(as_uuid=True)),
        sa.Column("to_all", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("message", sa.String(500), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("withdrawn_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(["clinic_id", "author_id"], ["users.clinic_id", "users.id"]),
        sa.ForeignKeyConstraint(["clinic_id", "branch_id"], ["branches.clinic_id", "branches.id"]),
        sa.UniqueConstraint("clinic_id", "id", name="uq_notices_clinic_id"),
    )
    op.create_index("ix_notices_clinic_created", "notices", ["clinic_id", "created_at"])
    op.create_table(
        "notice_recipients",
        sa.Column("notice_id", UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", UUID(as_uuid=True), primary_key=True),
        sa.Column("clinic_id", UUID(as_uuid=True), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(["clinic_id", "notice_id"], ["notices.clinic_id", "notices.id"]),
        sa.ForeignKeyConstraint(["clinic_id", "user_id"], ["users.clinic_id", "users.id"]),
    )
    op.create_index("ix_notice_recipients_user", "notice_recipients", ["clinic_id", "user_id", "read_at"])


def downgrade() -> None:
    op.drop_index("ix_notice_recipients_user", table_name="notice_recipients")
    op.drop_table("notice_recipients")
    op.drop_index("ix_notices_clinic_created", table_name="notices")
    op.drop_table("notices")
