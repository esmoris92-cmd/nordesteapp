"""Funciones habilitadas por clínica (las decide el dueño del sistema).

Se guarda la lista de funciones DESHABILITADAS: vacía = todo activado, como hasta ahora.

Revision ID: 0027_funciones_clinica
Revises: 0026_arancel_ayex
Create Date: 2026-10-31
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0027_funciones_clinica"
down_revision = "0026_arancel_ayex"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("clinics", sa.Column(
        "disabled_features", postgresql.ARRAY(sa.String(40)), nullable=False, server_default="{}"))


def downgrade() -> None:
    op.drop_column("clinics", "disabled_features")
