"""Logo de la clínica (PNG o JPG): sale en el encabezado de lo que se imprime desde Nordeste.

Revision ID: 0034_logo_clinica
Revises: 0033_cierre_informe
Create Date: 2026-11-03
"""

import sqlalchemy as sa
from alembic import op

revision = "0034_logo_clinica"
down_revision = "0033_cierre_informe"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("clinics", sa.Column("logo", sa.LargeBinary()))
    op.add_column("clinics", sa.Column("logo_content_type", sa.String(20)))
    op.add_column("clinics", sa.Column("logo_updated_at", sa.DateTime(timezone=True)))


def downgrade() -> None:
    op.drop_column("clinics", "logo_updated_at")
    op.drop_column("clinics", "logo_content_type")
    op.drop_column("clinics", "logo")
