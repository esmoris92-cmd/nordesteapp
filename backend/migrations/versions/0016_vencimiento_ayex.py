"""Fecha de vencimiento del AYEX del paciente.

Obligatoria al dar de alta o cambiar a AYEX (lo controla la API). Los pacientes AYEX que
ya existían quedan sin fecha: el Inicio los cuenta para que se completen.

Revision ID: 0016_vencimiento_ayex
Revises: 0015_afiliaciones
Create Date: 2026-10-21
"""

import sqlalchemy as sa
from alembic import op

revision = "0016_vencimiento_ayex"
down_revision = "0015_afiliaciones"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("patients", sa.Column("ayex_expires_on", sa.Date()))
    op.create_index("ix_patients_clinic_ayex_expires", "patients", ["clinic_id", "ayex_expires_on"])


def downgrade() -> None:
    op.drop_index("ix_patients_clinic_ayex_expires", table_name="patients")
    op.drop_column("patients", "ayex_expires_on")
