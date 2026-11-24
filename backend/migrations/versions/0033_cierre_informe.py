"""Cierre del informe generado: con qué versiones de las secciones se armó y quiénes no
participan (marcados por el responsable del paciente).

Revision ID: 0033_cierre_informe
Revises: 0032_firmantes_informe
Create Date: 2026-11-02
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0033_cierre_informe"
down_revision = "0032_firmantes_informe"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("reports", sa.Column("section_version_ids", postgresql.JSONB()))
    op.add_column("reports", sa.Column("excluded_ids", postgresql.JSONB()))


def downgrade() -> None:
    op.drop_column("reports", "excluded_ids")
    op.drop_column("reports", "section_version_ids")
