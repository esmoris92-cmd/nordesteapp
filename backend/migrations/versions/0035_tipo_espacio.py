"""Tipo de espacio: clínica o profesional independiente.

Todas las clínicas que ya existen quedan como "clinic", así que nada cambia para ellas.

Revision ID: 0035_tipo_espacio
Revises: 0034_logo_clinica
Create Date: 2026-11-05
"""

import sqlalchemy as sa
from alembic import op

revision = "0035_tipo_espacio"
down_revision = "0034_logo_clinica"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("clinics", sa.Column("kind", sa.String(20), nullable=False, server_default="clinic"))
    op.create_check_constraint("ck_clinics_kind", "clinics", "kind IN ('clinic', 'independent')")


def downgrade() -> None:
    op.drop_constraint("ck_clinics_kind", "clinics", type_="check")
    op.drop_column("clinics", "kind")
