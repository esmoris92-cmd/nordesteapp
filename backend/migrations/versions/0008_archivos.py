"""Archivos adjuntos de pacientes.

Revision ID: 0008_archivos
Revises: 0007_tipos_registro_clinico
Create Date: 2026-10-18
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0008_archivos"
down_revision = "0007_tipos_registro_clinico"
branch_labels = None
depends_on = None

UUID = postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.create_table(
        "patient_files",
        sa.Column("id", UUID, primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("clinic_id", UUID, nullable=False),
        sa.Column("patient_id", UUID, nullable=False),
        sa.Column("uploaded_by", UUID, nullable=False),
        sa.Column("original_name", sa.String(200), nullable=False),
        sa.Column("content_type", sa.String(50), nullable=False),
        sa.Column("size_bytes", sa.Integer, nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("storage_key", sa.String(64), nullable=False, unique=True),
        sa.Column("description", sa.String(300)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("withdrawn_at", sa.DateTime(timezone=True)),
        sa.Column("withdrawn_by", UUID),
        sa.Column("withdraw_reason", sa.String(300)),
        sa.ForeignKeyConstraint(["clinic_id", "patient_id"], ["patients.clinic_id", "patients.id"]),
        sa.ForeignKeyConstraint(["clinic_id", "uploaded_by"], ["users.clinic_id", "users.id"]),
        sa.ForeignKeyConstraint(["clinic_id", "withdrawn_by"], ["users.clinic_id", "users.id"]),
        sa.CheckConstraint("(withdrawn_at IS NULL) = (withdrawn_by IS NULL)", name="ck_patient_files_withdrawn"),
    )
    op.create_index("ix_patient_files_patient", "patient_files", ["clinic_id", "patient_id", "created_at"])
    # No se borran; solo se pueden retirar una vez, sin cambiar nada más.
    op.execute(
        """
        CREATE FUNCTION medflow_files_guard() RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'MedFlow: los archivos no se borran; se retiran'
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            IF OLD.withdrawn_at IS NOT NULL
               OR NEW.clinic_id <> OLD.clinic_id OR NEW.patient_id <> OLD.patient_id
               OR NEW.uploaded_by <> OLD.uploaded_by OR NEW.storage_key <> OLD.storage_key
               OR NEW.sha256 <> OLD.sha256 OR NEW.size_bytes <> OLD.size_bytes
               OR NEW.original_name <> OLD.original_name OR NEW.created_at <> OLD.created_at THEN
                RAISE EXCEPTION 'MedFlow: un archivo solo puede retirarse una vez'
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        "CREATE TRIGGER patient_files_guard BEFORE UPDATE OR DELETE ON patient_files "
        "FOR EACH ROW EXECUTE FUNCTION medflow_files_guard();"
    )


def downgrade() -> None:
    op.drop_table("patient_files")
    op.execute("DROP FUNCTION IF EXISTS medflow_files_guard()")
