"""Plan de tratamiento: objetivos y registros de avance.

Los objetivos no se borran ni se reescribe su texto (solo cambian estado y avance), y los
registros de avance solo se agregan. Lo garantizan dos disparadores de la base.

Revision ID: 0011_objetivos
Revises: 0010_cambio_clave_obligatorio
Create Date: 2026-10-19
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0011_objetivos"
down_revision = "0010_cambio_clave_obligatorio"
branch_labels = None
depends_on = None

UUID = postgresql.UUID(as_uuid=True)
_STATUS = "('active', 'achieved', 'discontinued')"


def upgrade() -> None:
    op.create_table(
        "treatment_goals",
        sa.Column("id", UUID, primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("clinic_id", UUID, nullable=False),
        sa.Column("patient_id", UUID, nullable=False),
        sa.Column("created_by", UUID, nullable=False),
        sa.Column("area", sa.String(80), nullable=False),
        sa.Column("description", sa.Text, nullable=False),
        sa.Column("target_date", sa.Date),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("progress", sa.SmallInteger, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("clinic_id", "id", name="uq_treatment_goals_clinic_id"),
        sa.ForeignKeyConstraint(["clinic_id", "patient_id"], ["patients.clinic_id", "patients.id"]),
        sa.ForeignKeyConstraint(["clinic_id", "created_by"], ["users.clinic_id", "users.id"]),
        sa.CheckConstraint(f"status IN {_STATUS}", name="ck_treatment_goals_status"),
        sa.CheckConstraint("progress BETWEEN 0 AND 100", name="ck_treatment_goals_progress"),
    )
    op.create_index("ix_treatment_goals_patient", "treatment_goals", ["clinic_id", "patient_id"])
    op.create_table(
        "goal_updates",
        sa.Column("id", UUID, primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("clinic_id", UUID, nullable=False),
        sa.Column("goal_id", UUID, nullable=False),
        sa.Column("author_id", UUID, nullable=False),
        sa.Column("session_date", sa.Date),
        sa.Column("progress", sa.SmallInteger, nullable=False),
        sa.Column("new_status", sa.String(20)),
        sa.Column("note", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["clinic_id", "goal_id"], ["treatment_goals.clinic_id", "treatment_goals.id"]),
        sa.ForeignKeyConstraint(["clinic_id", "author_id"], ["users.clinic_id", "users.id"]),
        sa.CheckConstraint("progress BETWEEN 0 AND 100", name="ck_goal_updates_progress"),
        sa.CheckConstraint(f"new_status IS NULL OR new_status IN {_STATUS}", name="ck_goal_updates_status"),
    )
    op.create_index("ix_goal_updates_goal", "goal_updates", ["clinic_id", "goal_id", "created_at"])
    op.execute(
        """
        CREATE FUNCTION medflow_goals_guard() RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'MedFlow: los objetivos no se borran; se discontinúan'
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            IF NEW.clinic_id <> OLD.clinic_id OR NEW.patient_id <> OLD.patient_id
               OR NEW.created_by <> OLD.created_by OR NEW.area <> OLD.area
               OR NEW.description <> OLD.description
               OR NEW.target_date IS DISTINCT FROM OLD.target_date
               OR NEW.created_at <> OLD.created_at THEN
                RAISE EXCEPTION 'MedFlow: de un objetivo solo cambian el estado y el avance'
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        "CREATE TRIGGER treatment_goals_guard BEFORE UPDATE OR DELETE ON treatment_goals "
        "FOR EACH ROW EXECUTE FUNCTION medflow_goals_guard();"
    )
    op.execute(
        """
        CREATE FUNCTION medflow_goal_updates_guard() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'MedFlow: los registros de avance no se modifican ni se borran'
                USING ERRCODE = 'integrity_constraint_violation';
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        "CREATE TRIGGER goal_updates_guard BEFORE UPDATE OR DELETE ON goal_updates "
        "FOR EACH ROW EXECUTE FUNCTION medflow_goal_updates_guard();"
    )


def downgrade() -> None:
    op.drop_table("goal_updates")
    op.drop_table("treatment_goals")
    op.execute("DROP FUNCTION IF EXISTS medflow_goal_updates_guard()")
    op.execute("DROP FUNCTION IF EXISTS medflow_goals_guard()")
