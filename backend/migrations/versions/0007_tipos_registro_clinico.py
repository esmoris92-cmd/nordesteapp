"""Nuevos tipos de registro clínico: anamnesis, entrevista y evaluación.

Siguen las mismas reglas que las notas: no se editan ni se borran (las
correcciones crean una versión nueva con motivo).

Revision ID: 0007_tipos_registro_clinico
Revises: 0006_responsables
Create Date: 2026-10-18
"""

from alembic import op

revision = "0007_tipos_registro_clinico"
down_revision = "0006_responsables"
branch_labels = None
depends_on = None

OLD = "kind IN ('session', 'background', 'progress')"
NEW = "kind IN ('session', 'background', 'progress', 'anamnesis', 'interview', 'evaluation')"


def upgrade() -> None:
    op.drop_constraint("ck_clinical_notes_kind", "clinical_notes", type_="check")
    op.create_check_constraint("ck_clinical_notes_kind", "clinical_notes", NEW)


def downgrade() -> None:
    # Si ya existen registros de los tipos nuevos, la base rechaza la regla antigua y la
    # reversión FALLA a propósito: la historia clínica nunca se borra para poder revertir.
    op.drop_constraint("ck_clinical_notes_kind", "clinical_notes", type_="check")
    op.create_check_constraint("ck_clinical_notes_kind", "clinical_notes", OLD)
