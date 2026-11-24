"""Agenda por sucursal: la disponibilidad y los turnos indican en qué sucursal son.

* Los horarios de disponibilidad existentes quedan en la primera sucursal ("Central").
* Los turnos existentes: si el paciente es de ASSE o Convenio militar, en la sucursal del
  paciente (solo puede atenderse allí); si es privado, en la primera sucursal.

Revision ID: 0014_agenda_sucursal
Revises: 0013_paciente_sucursal
Create Date: 2026-10-20
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0014_agenda_sucursal"
down_revision = "0013_paciente_sucursal"
branch_labels = None
depends_on = None

FIRST_BRANCH = ("(SELECT b.id FROM branches b WHERE b.clinic_id = {t}.clinic_id "
                "ORDER BY b.created_at, b.name LIMIT 1)")


def upgrade() -> None:
    op.add_column("availability", sa.Column("branch_id", postgresql.UUID(as_uuid=True)))
    op.execute(f"UPDATE availability SET branch_id = {FIRST_BRANCH.format(t='availability')}")
    op.alter_column("availability", "branch_id", nullable=False)
    op.create_foreign_key("fk_availability_branch", "availability", "branches",
                          ["clinic_id", "branch_id"], ["clinic_id", "id"])

    op.add_column("appointments", sa.Column("branch_id", postgresql.UUID(as_uuid=True)))
    op.execute(
        "UPDATE appointments a SET branch_id = p.branch_id FROM patients p "
        "WHERE p.id = a.patient_id AND p.clinic_id = a.clinic_id AND p.affiliation <> 'private'"
    )
    op.execute(f"UPDATE appointments SET branch_id = {FIRST_BRANCH.format(t='appointments')} "
               "WHERE branch_id IS NULL")
    op.alter_column("appointments", "branch_id", nullable=False)
    op.create_foreign_key("fk_appointments_branch", "appointments", "branches",
                          ["clinic_id", "branch_id"], ["clinic_id", "id"])
    op.create_index("ix_appointments_branch_start", "appointments",
                    ["clinic_id", "branch_id", "starts_at"])


def downgrade() -> None:
    op.drop_index("ix_appointments_branch_start", table_name="appointments")
    op.drop_constraint("fk_appointments_branch", "appointments", type_="foreignkey")
    op.drop_column("appointments", "branch_id")
    op.drop_constraint("fk_availability_branch", "availability", type_="foreignkey")
    op.drop_column("availability", "branch_id")
