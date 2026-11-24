"""Motivo de la ausencia de un turno (opcional, al marcarlo como ausente).

Revision ID: 0029_motivo_ausencia
Revises: 0028_motivo_reprogramacion
Create Date: 2026-10-31
"""

import sqlalchemy as sa
from alembic import op

revision = "0029_motivo_ausencia"
down_revision = "0028_motivo_reprogramacion"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("appointments", sa.Column("no_show_reason", sa.String(300)))


def downgrade() -> None:
    op.drop_column("appointments", "no_show_reason")
