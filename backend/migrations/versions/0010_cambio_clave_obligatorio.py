"""Cambio de contraseña obligatorio tras un restablecimiento hecho por administración.

Revision ID: 0010_cambio_clave_obligatorio
Revises: 0009_tipo_afiliacion
Create Date: 2026-10-19
"""

import sqlalchemy as sa
from alembic import op

revision = "0010_cambio_clave_obligatorio"
down_revision = "0009_tipo_afiliacion"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("must_change_password", sa.Boolean(), nullable=False,
                                     server_default=sa.text("false")))


def downgrade() -> None:
    op.drop_column("users", "must_change_password")
