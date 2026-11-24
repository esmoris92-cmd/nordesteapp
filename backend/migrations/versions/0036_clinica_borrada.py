"""Clínica borrada: fecha en que el dueño del sistema borró todos sus datos.

La fila de la clínica se conserva (solo con su nombre y fechas) porque la auditoría del dueño
la nombra; todos sus datos (pacientes, historia clínica, cuentas, archivos…) se borran.

Revision ID: 0036_clinica_borrada
Revises: 0035_tipo_espacio
Create Date: 2026-11-10
"""

import sqlalchemy as sa
from alembic import op

revision = "0036_clinica_borrada"
down_revision = "0035_tipo_espacio"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("clinics", sa.Column("purged_at", sa.DateTime(timezone=True)))


def downgrade() -> None:
    op.drop_column("clinics", "purged_at")
