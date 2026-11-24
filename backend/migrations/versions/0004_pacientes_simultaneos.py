"""Pacientes simultáneos por profesional.

Permite agendar a varios pacientes en el mismo horario con un mismo profesional
(sesiones grupales), hasta un máximo por profesional. Por defecto, 3.

Revision ID: 0004_pacientes_simultaneos
Revises: 0003_archivar_usuarios
Create Date: 2026-10-17
"""

import sqlalchemy as sa
from alembic import op

revision = "0004_pacientes_simultaneos"
down_revision = "0003_archivar_usuarios"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("max_concurrent_patients", sa.SmallInteger(),
                                     nullable=False, server_default="3"))
    op.create_check_constraint("ck_users_max_concurrent", "users",
                               "max_concurrent_patients BETWEEN 1 AND 10")


def downgrade() -> None:
    op.drop_constraint("ck_users_max_concurrent", "users", type_="check")
    op.drop_column("users", "max_concurrent_patients")
