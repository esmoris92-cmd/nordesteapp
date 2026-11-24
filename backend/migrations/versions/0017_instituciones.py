"""Instituciones educativas del paciente, con sus reportes y archivos.

* patient_institutions: nombre, nivel (inicial, primaria, secundaria, UTU, universidad, otra),
  teléfono, correo y si es la institución actual.
* Los reportes son notas de historia clínica de tipo "institution" (solo-agregar, con
  correcciones) que apuntan a la institución; los archivos son archivos del paciente que
  apuntan a ella.

Revision ID: 0017_instituciones
Revises: 0016_vencimiento_ayex
Create Date: 2026-10-23
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0017_instituciones"
down_revision = "0016_vencimiento_ayex"
branch_labels = None
depends_on = None

OLD_KINDS = "kind IN ('session', 'background', 'progress', 'anamnesis', 'interview', 'evaluation')"
NEW_KINDS = ("kind IN ('session', 'background', 'progress', 'anamnesis', 'interview', 'evaluation', "
             "'institution')")


def upgrade() -> None:
    op.create_table(
        "patient_institutions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("clinic_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("patient_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("level", sa.String(20), nullable=False),
        sa.Column("phone", sa.String(40)),
        sa.Column("email", sa.String(254)),
        sa.Column("is_current", sa.Boolean(), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["clinic_id", "patient_id"], ["patients.clinic_id", "patients.id"]),
        sa.ForeignKeyConstraint(["clinic_id", "created_by"], ["users.clinic_id", "users.id"]),
        sa.UniqueConstraint("clinic_id", "id", name="uq_patient_institutions_clinic_id"),
        sa.CheckConstraint("level IN ('inicial', 'primaria', 'secundaria', 'utu', 'universidad', 'otra')",
                           name="ck_patient_institutions_level"),
    )
    op.create_index("ix_patient_institutions_patient", "patient_institutions", ["clinic_id", "patient_id"])

    op.add_column("clinical_notes", sa.Column("institution_id", postgresql.UUID(as_uuid=True)))
    op.create_foreign_key("fk_clinical_notes_institution", "clinical_notes", "patient_institutions",
                          ["clinic_id", "institution_id"], ["clinic_id", "id"])
    op.drop_constraint("ck_clinical_notes_kind", "clinical_notes", type_="check")
    op.create_check_constraint("ck_clinical_notes_kind", "clinical_notes", NEW_KINDS)
    op.create_check_constraint("ck_clinical_notes_institution", "clinical_notes",
                               "(kind = 'institution') = (institution_id IS NOT NULL)")

    op.add_column("patient_files", sa.Column("institution_id", postgresql.UUID(as_uuid=True)))
    op.create_foreign_key("fk_patient_files_institution", "patient_files", "patient_institutions",
                          ["clinic_id", "institution_id"], ["clinic_id", "id"])


def downgrade() -> None:
    # Con reportes de instituciones ya guardados, la regla antigua de tipos FALLA a propósito:
    # la historia clínica nunca se borra para poder revertir.
    op.drop_constraint("fk_patient_files_institution", "patient_files", type_="foreignkey")
    op.drop_column("patient_files", "institution_id")
    op.drop_constraint("ck_clinical_notes_institution", "clinical_notes", type_="check")
    op.drop_constraint("ck_clinical_notes_kind", "clinical_notes", type_="check")
    op.create_check_constraint("ck_clinical_notes_kind", "clinical_notes", OLD_KINDS)
    op.drop_constraint("fk_clinical_notes_institution", "clinical_notes", type_="foreignkey")
    op.drop_column("clinical_notes", "institution_id")
    op.drop_index("ix_patient_institutions_patient", table_name="patient_institutions")
    op.drop_table("patient_institutions")
