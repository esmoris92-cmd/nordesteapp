"""C.I. (obligatoria) y teléfono de cada cuenta de usuario.

Las cuentas que ya existían quedan sin C.I.: Lumen les muestra un aviso hasta que la completan
en "Mi cuenta". La C.I. no puede repetirse dentro de la clínica.

Revision ID: 0021_ci_usuarios
Revises: 0020_titulo_profesional
Create Date: 2026-10-23
"""

import sqlalchemy as sa
from alembic import op

revision = "0021_ci_usuarios"
down_revision = "0020_titulo_profesional"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("document_number", sa.String(30)))
    op.add_column("users", sa.Column("phone", sa.String(40)))
    op.create_index("uq_users_clinic_document", "users", ["clinic_id", "document_number"], unique=True,
                    postgresql_where=sa.text("document_number IS NOT NULL"))


def downgrade() -> None:
    op.drop_index("uq_users_clinic_document", table_name="users")
    op.drop_column("users", "phone")
    op.drop_column("users", "document_number")
