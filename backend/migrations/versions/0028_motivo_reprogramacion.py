"""Motivo de la reprogramación de un turno (obligatorio desde ahora al reprogramar).

Se guarda en el turno original (el que queda como "reprogramado"). Los reprogramados antes de
este cambio quedan sin motivo.

Revision ID: 0028_motivo_reprogramacion
Revises: 0027_funciones_clinica
Create Date: 2026-10-31
"""

import sqlalchemy as sa
from alembic import op

revision = "0028_motivo_reprogramacion"
down_revision = "0027_funciones_clinica"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("appointments", sa.Column("reschedule_reason", sa.String(300)))


def downgrade() -> None:
    op.drop_column("appointments", "reschedule_reason")
