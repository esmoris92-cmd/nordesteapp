"""Archivar cuentas de usuario.

"Eliminar" una cuenta la ARCHIVA: queda desactivada y oculta de la lista, pero no se
borra, porque notas, informes, accesos y auditoría guardan quién hizo cada cosa.

Revision ID: 0003_archivar_usuarios
Revises: 0002_especialidades
Create Date: 2026-10-17
"""

import sqlalchemy as sa
from alembic import op

revision = "0003_archivar_usuarios"
down_revision = "0002_especialidades"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("archived_at", sa.DateTime(timezone=True)))
    # Una cuenta archivada nunca puede estar activa.
    op.create_check_constraint(
        "ck_users_archived_inactive", "users", "archived_at IS NULL OR is_active = false"
    )


def downgrade() -> None:
    op.drop_constraint("ck_users_archived_inactive", "users", type_="check")
    op.drop_column("users", "archived_at")
