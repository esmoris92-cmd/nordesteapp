"""Esquema inicial de MedFlow.

Crea las tablas, las claves foráneas compuestas (aislamiento por clínica) y los
disparadores que hacen de solo-agregar la historia clínica y la auditoría.

Revision ID: 0001_inicial
Revises:
Create Date: 2026-10-17
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001_inicial"
down_revision = None
branch_labels = None
depends_on = None

UUID = postgresql.UUID(as_uuid=True)
TS = sa.DateTime(timezone=True)


def _id():
    return sa.Column("id", UUID, primary_key=True, server_default=sa.text("gen_random_uuid()"))


def _now(name="created_at"):
    return sa.Column(name, TS, nullable=False, server_default=sa.func.now())


def _fk_user(col: str):
    return sa.ForeignKeyConstraint(["clinic_id", col], ["users.clinic_id", "users.id"])


def _fk_patient():
    return sa.ForeignKeyConstraint(["clinic_id", "patient_id"], ["patients.clinic_id", "patients.id"])


def upgrade() -> None:
    op.create_table(
        "clinics",
        _id(),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("timezone", sa.String(64), nullable=False, server_default="America/Montevideo"),
        _now(),
    )

    op.create_table(
        "users",
        _id(),
        sa.Column("clinic_id", UUID, sa.ForeignKey("clinics.id"), nullable=False, index=True),
        sa.Column("email", sa.String(254), nullable=False, unique=True),
        sa.Column("full_name", sa.String(200), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("specialty", sa.String(40)),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("failed_login_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("locked_until", TS),
        _now(),
        _now("updated_at"),
        sa.UniqueConstraint("clinic_id", "id", name="uq_users_clinic_id"),
        sa.CheckConstraint("role IN ('admin', 'reception', 'professional')", name="ck_users_role"),
        sa.CheckConstraint(
            "specialty IS NULL OR specialty IN ('psychology', 'occupational_therapy')",
            name="ck_users_specialty",
        ),
    )

    op.create_table(
        "auth_sessions",
        _id(),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("csrf_token", sa.String(64), nullable=False),
        sa.Column("clinic_id", UUID, nullable=False),
        sa.Column("user_id", UUID, nullable=False, index=True),
        _now(),
        sa.Column("last_seen_at", TS, nullable=False),
        sa.Column("expires_at", TS, nullable=False),
        sa.Column("revoked_at", TS),
        _fk_user("user_id"),
    )

    op.create_table(
        "patients",
        _id(),
        sa.Column("clinic_id", UUID, sa.ForeignKey("clinics.id"), nullable=False),
        sa.Column("first_name", sa.String(100), nullable=False),
        sa.Column("last_name", sa.String(100), nullable=False),
        sa.Column("birth_date", sa.Date),
        sa.Column("phone", sa.String(40)),
        sa.Column("email", sa.String(254)),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("created_by", UUID, nullable=False),
        _now(),
        _now("updated_at"),
        sa.UniqueConstraint("clinic_id", "id", name="uq_patients_clinic_id"),
        sa.CheckConstraint(
            "status IN ('active', 'paused', 'discharged', 'inactive')", name="ck_patients_status"
        ),
        _fk_user("created_by"),
    )
    op.create_index("ix_patients_clinic_last_name", "patients", ["clinic_id", "last_name"])

    op.create_table(
        "patient_access",
        _id(),
        sa.Column("clinic_id", UUID, nullable=False),
        sa.Column("patient_id", UUID, nullable=False, index=True),
        sa.Column("user_id", UUID, nullable=False, index=True),
        sa.Column("level", sa.String(20), nullable=False),
        sa.Column("reason", sa.String(300)),
        sa.Column("granted_by", UUID, nullable=False),
        sa.Column("granted_at", TS, nullable=False, server_default=sa.func.now()),
        sa.Column("revoked_by", UUID),
        sa.Column("revoked_at", TS),
        sa.Column("revoke_reason", sa.String(300)),
        sa.CheckConstraint("level IN ('responsible', 'collaborator')", name="ck_patient_access_level"),
        sa.CheckConstraint(
            "(revoked_at IS NULL) = (revoked_by IS NULL)", name="ck_patient_access_revoked_pair"
        ),
        _fk_patient(),
        _fk_user("user_id"),
        _fk_user("granted_by"),
        _fk_user("revoked_by"),
    )
    op.create_index(
        "uq_patient_access_active", "patient_access", ["patient_id", "user_id"], unique=True,
        postgresql_where=sa.text("revoked_at IS NULL"),
    )
    op.create_index(
        "uq_patient_access_one_responsible", "patient_access", ["patient_id"], unique=True,
        postgresql_where=sa.text("revoked_at IS NULL AND level = 'responsible'"),
    )

    op.create_table(
        "availability",
        _id(),
        sa.Column("clinic_id", UUID, nullable=False),
        sa.Column("professional_id", UUID, nullable=False, index=True),
        sa.Column("weekday", sa.SmallInteger, nullable=False),
        sa.Column("start_time", sa.Time, nullable=False),
        sa.Column("end_time", sa.Time, nullable=False),
        _now(),
        _fk_user("professional_id"),
        sa.CheckConstraint("weekday BETWEEN 0 AND 6", name="ck_availability_weekday"),
        sa.CheckConstraint("end_time > start_time", name="ck_availability_range"),
    )

    op.create_table(
        "appointments",
        _id(),
        sa.Column("clinic_id", UUID, nullable=False),
        sa.Column("patient_id", UUID, nullable=False, index=True),
        sa.Column("professional_id", UUID, nullable=False),
        sa.Column("starts_at", TS, nullable=False),
        sa.Column("ends_at", TS, nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="scheduled"),
        sa.Column("cancel_reason", sa.String(300)),
        sa.Column("rescheduled_to_id", UUID, sa.ForeignKey("appointments.id")),
        sa.Column("created_by", UUID, nullable=False),
        _now(),
        _now("updated_at"),
        _fk_patient(),
        _fk_user("professional_id"),
        _fk_user("created_by"),
        sa.CheckConstraint(
            "status IN ('scheduled', 'completed', 'no_show', 'cancelled', 'rescheduled')",
            name="ck_appointments_status",
        ),
        sa.CheckConstraint("ends_at > starts_at", name="ck_appointments_range"),
    )
    op.create_index(
        "ix_appointments_prof_start", "appointments", ["clinic_id", "professional_id", "starts_at"]
    )

    op.create_table(
        "clinical_notes",
        _id(),
        sa.Column("clinic_id", UUID, nullable=False),
        sa.Column("patient_id", UUID, nullable=False),
        sa.Column("author_id", UUID, nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("session_date", sa.Date),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("supersedes_id", UUID, sa.ForeignKey("clinical_notes.id")),
        sa.Column("correction_reason", sa.String(300)),
        _now(),
        _fk_patient(),
        _fk_user("author_id"),
        sa.CheckConstraint(
            "kind IN ('session', 'background', 'progress')", name="ck_clinical_notes_kind"
        ),
        sa.CheckConstraint(
            "(supersedes_id IS NULL) = (correction_reason IS NULL)",
            name="ck_clinical_notes_correction_reason",
        ),
        sa.UniqueConstraint("supersedes_id", name="uq_clinical_notes_supersedes"),
    )
    op.create_index(
        "ix_clinical_notes_patient", "clinical_notes", ["clinic_id", "patient_id", "created_at"]
    )

    op.create_table(
        "reports",
        _id(),
        sa.Column("clinic_id", UUID, nullable=False),
        sa.Column("patient_id", UUID, nullable=False),
        sa.Column("author_id", UUID, nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("status", sa.String(10), nullable=False, server_default="draft"),
        _now(),
        _now("updated_at"),
        sa.Column("finalized_at", TS),
        _fk_patient(),
        _fk_user("author_id"),
        sa.CheckConstraint("status IN ('draft', 'final')", name="ck_reports_status"),
    )
    op.create_index("ix_reports_patient", "reports", ["clinic_id", "patient_id", "created_at"])

    op.create_table(
        "audit_log",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("clinic_id", UUID, sa.ForeignKey("clinics.id"), nullable=False),
        sa.Column("actor_id", UUID),
        sa.Column("action", sa.String(60), nullable=False),
        sa.Column("entity_type", sa.String(40)),
        sa.Column("entity_id", sa.String(64)),
        sa.Column("patient_id", UUID),
        sa.Column("details", postgresql.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("ip", sa.String(45)),
        _now(),
        _fk_user("actor_id"),
        _fk_patient(),
    )
    op.create_index("ix_audit_clinic_created", "audit_log", ["clinic_id", "created_at"])
    op.create_index("ix_audit_clinic_patient", "audit_log", ["clinic_id", "patient_id"])

    # ---- Disparadores de integridad ----
    # 1) Historia clínica y auditoría: prohibido modificar o borrar filas.
    op.execute(
        """
        CREATE FUNCTION medflow_forbid_change() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'MedFlow: la tabla % es de solo-agregar; no se permite %',
                TG_TABLE_NAME, TG_OP USING ERRCODE = 'integrity_constraint_violation';
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    for table in ("clinical_notes", "audit_log"):
        op.execute(
            f"CREATE TRIGGER {table}_append_only BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION medflow_forbid_change();"
        )

    # 2) Informes: no se borran; un informe final no se modifica.
    op.execute(
        """
        CREATE FUNCTION medflow_reports_guard() RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'MedFlow: los informes no se borran'
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            IF OLD.status = 'final' THEN
                RAISE EXCEPTION 'MedFlow: un informe final no puede modificarse'
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            IF NEW.clinic_id <> OLD.clinic_id OR NEW.patient_id <> OLD.patient_id
               OR NEW.author_id <> OLD.author_id OR NEW.created_at <> OLD.created_at THEN
                RAISE EXCEPTION 'MedFlow: no se puede cambiar el paciente, autor o fecha de un informe'
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        "CREATE TRIGGER reports_guard BEFORE UPDATE OR DELETE ON reports "
        "FOR EACH ROW EXECUTE FUNCTION medflow_reports_guard();"
    )

    # 3) Accesos: no se borran; solo se puede revocar una vez (sin cambiar lo demás).
    op.execute(
        """
        CREATE FUNCTION medflow_access_guard() RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'MedFlow: los accesos no se borran; se revocan'
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            IF OLD.revoked_at IS NOT NULL
               OR NEW.clinic_id <> OLD.clinic_id OR NEW.patient_id <> OLD.patient_id
               OR NEW.user_id <> OLD.user_id OR NEW.level <> OLD.level
               OR NEW.granted_by <> OLD.granted_by OR NEW.granted_at <> OLD.granted_at
               OR NEW.reason IS DISTINCT FROM OLD.reason THEN
                RAISE EXCEPTION 'MedFlow: un acceso solo puede revocarse una vez'
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        "CREATE TRIGGER patient_access_guard BEFORE UPDATE OR DELETE ON patient_access "
        "FOR EACH ROW EXECUTE FUNCTION medflow_access_guard();"
    )


def downgrade() -> None:
    # Revierte todo el esquema. ¡Borra los datos! Úsalo solo en desarrollo.
    for table in (
        "audit_log", "reports", "clinical_notes", "appointments", "availability",
        "patient_access", "patients", "auth_sessions", "users", "clinics",
    ):
        op.drop_table(table)
    op.execute("DROP FUNCTION IF EXISTS medflow_forbid_change()")
    op.execute("DROP FUNCTION IF EXISTS medflow_reports_guard()")
    op.execute("DROP FUNCTION IF EXISTS medflow_access_guard()")
