"""C.I. del responsable o tutor del paciente.

Obligatoria al agregar o editar un responsable (lo controla la API). Los responsables que
ya existían quedan sin C.I. y se piden completarla la próxima vez que se editen.

Revision ID: 0018_ci_responsable
Revises: 0017_instituciones
Create Date: 2026-10-23
"""

import sqlalchemy as sa
from alembic import op

revision = "0018_ci_responsable"
down_revision = "0017_instituciones"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("patient_guardians", sa.Column("document_number", sa.String(30)))


def downgrade() -> None:
    op.drop_column("patient_guardians", "document_number")
