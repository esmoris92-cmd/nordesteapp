"""Secciones del informe en la ficha del paciente: Antecedentes, Diagnóstico, Encuadre y
Abordaje de cada profesional (con En suma y Sugerencias). Una versión por cada guardado.

Revision ID: 0031_secciones_informe
Revises: 0030_anamnesis_estructurada
Create Date: 2026-11-02
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0031_secciones_informe"
down_revision = "0030_anamnesis_estructurada"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "report_section_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("clinic_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("patient_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("section", sa.String(20), nullable=False),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True)),
        sa.Column("author_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("data", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["clinic_id", "patient_id"], ["patients.clinic_id", "patients.id"]),
        sa.ForeignKeyConstraint(["clinic_id", "author_id"], ["users.clinic_id", "users.id"]),
        sa.ForeignKeyConstraint(["clinic_id", "owner_id"], ["users.clinic_id", "users.id"],
                                name="fk_report_section_versions_owner"),
        sa.CheckConstraint("section IN ('antecedentes', 'diagnostico', 'encuadre', 'abordaje')",
                           name="ck_report_section_versions_section"),
        sa.CheckConstraint("(section = 'abordaje') = (owner_id IS NOT NULL)",
                           name="ck_report_section_versions_owner"),
    )
    op.create_index("ix_report_section_versions_patient", "report_section_versions",
                    ["clinic_id", "patient_id", "section", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_report_section_versions_patient", table_name="report_section_versions")
    op.drop_table("report_section_versions")
