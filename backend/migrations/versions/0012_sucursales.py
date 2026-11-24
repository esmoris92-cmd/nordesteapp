"""Sucursales: lista por clínica, sucursales permitidas por cuenta y sucursal de la sesión.

Cada clínica existente recibe la sucursal "Central" y todas sus cuentas (salvo
Administración, que entra a todas) quedan asignadas a ella.

Revision ID: 0012_sucursales
Revises: 0011_objetivos
Create Date: 2026-10-19
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0012_sucursales"
down_revision = "0011_objetivos"
branch_labels = None
depends_on = None

UUID = postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.create_table(
        "branches",
        sa.Column("id", UUID, primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("clinic_id", UUID, sa.ForeignKey("clinics.id"), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("clinic_id", "id", name="uq_branches_clinic_id"),
    )
    op.create_index("ix_branches_clinic_id", "branches", ["clinic_id"])
    op.execute("CREATE UNIQUE INDEX uq_branches_clinic_name ON branches (clinic_id, lower(name))")
    op.create_table(
        "user_branches",
        sa.Column("user_id", UUID, primary_key=True),
        sa.Column("branch_id", UUID, primary_key=True),
        sa.Column("clinic_id", UUID, nullable=False),
        sa.ForeignKeyConstraint(["clinic_id", "user_id"], ["users.clinic_id", "users.id"]),
        sa.ForeignKeyConstraint(["clinic_id", "branch_id"], ["branches.clinic_id", "branches.id"]),
    )
    op.add_column("auth_sessions", sa.Column("branch_id", UUID))
    op.create_foreign_key("fk_auth_sessions_branch", "auth_sessions", "branches",
                          ["clinic_id", "branch_id"], ["clinic_id", "id"])
    # Datos existentes: una sucursal "Central" por clínica, con todas sus cuentas.
    op.execute("INSERT INTO branches (clinic_id, name) SELECT id, 'Central' FROM clinics")
    op.execute(
        "INSERT INTO user_branches (user_id, branch_id, clinic_id) "
        "SELECT u.id, b.id, u.clinic_id FROM users u JOIN branches b ON b.clinic_id = u.clinic_id "
        "WHERE u.role <> 'admin'"
    )


def downgrade() -> None:
    op.drop_constraint("fk_auth_sessions_branch", "auth_sessions", type_="foreignkey")
    op.drop_column("auth_sessions", "branch_id")
    op.drop_table("user_branches")
    op.drop_index("ix_branches_clinic_id", table_name="branches")
    op.drop_table("branches")
