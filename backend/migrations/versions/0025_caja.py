"""Caja diaria por sucursal: apertura, entradas y salidas, y cierre.

Revision ID: 0025_caja
Revises: 0024_dueno_sistema
Create Date: 2026-10-30
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0025_caja"
down_revision = "0024_dueno_sistema"
branch_labels = None
depends_on = None

MONEY = sa.Numeric(12, 2)
TS = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "cash_registers",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("clinic_id", UUID(as_uuid=True), nullable=False),
        sa.Column("branch_id", UUID(as_uuid=True), nullable=False),
        sa.Column("business_date", sa.Date(), nullable=False),
        sa.Column("opening_amount", MONEY, nullable=False),
        sa.Column("opened_by", UUID(as_uuid=True), nullable=False),
        sa.Column("opened_at", TS, nullable=False, server_default=sa.func.now()),
        sa.Column("counted_amount", MONEY),
        sa.Column("expected_amount", MONEY),
        sa.Column("closing_note", sa.String(300)),
        sa.Column("closed_by", UUID(as_uuid=True)),
        sa.Column("closed_at", TS),
        sa.Column("reopen_count", sa.SmallInteger(), nullable=False, server_default="0"),
        sa.ForeignKeyConstraint(["clinic_id", "branch_id"], ["branches.clinic_id", "branches.id"]),
        sa.ForeignKeyConstraint(["clinic_id", "opened_by"], ["users.clinic_id", "users.id"]),
        sa.ForeignKeyConstraint(["clinic_id", "closed_by"], ["users.clinic_id", "users.id"]),
        sa.UniqueConstraint("clinic_id", "id", name="uq_cash_registers_clinic_id"),
        sa.UniqueConstraint("clinic_id", "branch_id", "business_date", name="uq_cash_registers_branch_day"),
        sa.CheckConstraint("opening_amount >= 0", name="ck_cash_registers_opening"),
        sa.CheckConstraint("counted_amount IS NULL OR counted_amount >= 0", name="ck_cash_registers_counted"),
        sa.CheckConstraint("(closed_at IS NULL) = (counted_amount IS NULL) AND (closed_at IS NULL) = "
                           "(expected_amount IS NULL) AND (closed_at IS NULL) = (closed_by IS NULL)",
                           name="ck_cash_registers_closed"),
    )
    op.create_table(
        "cash_movements",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("clinic_id", UUID(as_uuid=True), nullable=False),
        sa.Column("register_id", UUID(as_uuid=True), nullable=False),
        sa.Column("kind", sa.String(10), nullable=False),
        sa.Column("amount", MONEY, nullable=False),
        sa.Column("concept", sa.String(200), nullable=False),
        sa.Column("created_by", UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", TS, nullable=False, server_default=sa.func.now()),
        sa.Column("voided_at", TS),
        sa.Column("voided_by", UUID(as_uuid=True)),
        sa.Column("void_reason", sa.String(200)),
        sa.ForeignKeyConstraint(["clinic_id", "register_id"],
                                ["cash_registers.clinic_id", "cash_registers.id"]),
        sa.ForeignKeyConstraint(["clinic_id", "created_by"], ["users.clinic_id", "users.id"]),
        sa.ForeignKeyConstraint(["clinic_id", "voided_by"], ["users.clinic_id", "users.id"]),
        sa.CheckConstraint("kind IN ('income', 'expense')", name="ck_cash_movements_kind"),
        sa.CheckConstraint("amount > 0", name="ck_cash_movements_amount"),
        sa.CheckConstraint("(voided_at IS NULL) = (voided_by IS NULL)", name="ck_cash_movements_void"),
    )
    op.create_index("ix_cash_movements_register", "cash_movements", ["clinic_id", "register_id"])
    # Las cajas y sus movimientos no se borran (los movimientos se anulan). Se usa la función de
    # la migración 0001, solo para DELETE: anular o cerrar sí modifica la fila.
    for table in ("cash_registers", "cash_movements"):
        op.execute(
            f"CREATE TRIGGER {table}_no_delete BEFORE DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION medflow_forbid_change();"
        )


def downgrade() -> None:
    for table in ("cash_movements", "cash_registers"):
        op.execute(f"DROP TRIGGER IF EXISTS {table}_no_delete ON {table}")
    op.drop_index("ix_cash_movements_register", table_name="cash_movements")
    op.drop_table("cash_movements")
    op.drop_table("cash_registers")
