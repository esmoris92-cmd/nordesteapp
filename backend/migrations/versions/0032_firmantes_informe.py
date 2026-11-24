"""Firmantes del informe: al generarlo, firman todos los profesionales que intervienen.

Revision ID: 0032_firmantes_informe
Revises: 0031_secciones_informe
Create Date: 2026-11-02
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0032_firmantes_informe"
down_revision = "0031_secciones_informe"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("reports", sa.Column("signers", postgresql.JSONB()))


def downgrade() -> None:
    op.drop_column("reports", "signers")
