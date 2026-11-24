"""Datos para el Cronograma BPS.

* Cuentas: nombres y apellidos por separado, formación académica y quién expidió el título
  (los completa cada profesional en "Mi cuenta").
* Especialidades: la actividad del BPS que les corresponde (la elige Administración).

Revision ID: 0022_cronograma_bps
Revises: 0021_ci_usuarios
Create Date: 2026-10-23
"""

import sqlalchemy as sa
from alembic import op

revision = "0022_cronograma_bps"
down_revision = "0021_ci_usuarios"
branch_labels = None
depends_on = None

USER_COLUMNS = [("first_name", 100), ("middle_name", 100), ("last_name", 100), ("second_last_name", 100),
                ("bps_training", 60), ("degree_issuer", 60)]


def upgrade() -> None:
    for name, size in USER_COLUMNS:
        op.add_column("users", sa.Column(name, sa.String(size)))
    op.add_column("specialties", sa.Column("bps_activity", sa.String(80)))


def downgrade() -> None:
    op.drop_column("specialties", "bps_activity")
    for name, _ in reversed(USER_COLUMNS):
        op.drop_column("users", name)
