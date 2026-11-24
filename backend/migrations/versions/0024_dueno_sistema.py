"""Dueño del sistema: cuenta propia (fuera de las clínicas), sus sesiones, su auditoría y la
suspensión de clínicas.

Revision ID: 0024_dueno_sistema
Revises: 0023_avisos
Create Date: 2026-10-30
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0024_dueno_sistema"
down_revision = "0023_avisos"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("clinics", sa.Column("suspended_at", sa.DateTime(timezone=True)))

    op.create_table(
        "system_owners",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("email", sa.String(254), nullable=False, unique=True),
        sa.Column("full_name", sa.String(200), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("must_change_password", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("totp_secret", sa.String(64)),
        sa.Column("totp_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("totp_last_step", sa.BigInteger()),
        sa.Column("failed_login_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("locked_until", sa.DateTime(timezone=True)),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("NOT totp_enabled OR totp_secret IS NOT NULL", name="ck_system_owners_totp"),
    )
    op.create_table(
        "owner_sessions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("csrf_token", sa.String(64), nullable=False),
        sa.Column("owner_id", UUID(as_uuid=True), sa.ForeignKey("system_owners.id"), nullable=False, index=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
    )
    op.create_table(
        "owner_audit_log",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("owner_id", UUID(as_uuid=True), sa.ForeignKey("system_owners.id")),
        sa.Column("action", sa.String(60), nullable=False),
        sa.Column("clinic_id", UUID(as_uuid=True), sa.ForeignKey("clinics.id")),
        sa.Column("target_user_id", UUID(as_uuid=True)),
        sa.Column("details", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("ip", sa.String(45)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_owner_audit_created", "owner_audit_log", ["created_at"])
    # Igual que la auditoría de las clínicas: solo se agregan filas (función de la migración 0001).
    op.execute(
        "CREATE TRIGGER owner_audit_log_append_only BEFORE UPDATE OR DELETE ON owner_audit_log "
        "FOR EACH ROW EXECUTE FUNCTION medflow_forbid_change();"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS owner_audit_log_append_only ON owner_audit_log")
    op.drop_index("ix_owner_audit_created", table_name="owner_audit_log")
    op.drop_table("owner_audit_log")
    op.drop_table("owner_sessions")
    op.drop_table("system_owners")
    op.drop_column("clinics", "suspended_at")
