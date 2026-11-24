"""Arancel AYEX de la clínica (para controlar los pagos del BPS).

Revision ID: 0026_arancel_ayex
Revises: 0025_caja
Create Date: 2026-10-30
"""

import sqlalchemy as sa
from alembic import op

revision = "0026_arancel_ayex"
down_revision = "0025_caja"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("clinics", sa.Column("ayex_fee", sa.Numeric(12, 2)))
    op.create_check_constraint("ck_clinics_ayex_fee", "clinics", "ayex_fee IS NULL OR ayex_fee > 0")


def downgrade() -> None:
    op.drop_constraint("ck_clinics_ayex_fee", "clinics", type_="check")
    op.drop_column("clinics", "ayex_fee")
