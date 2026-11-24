"""Datos para el formulario de AYEX del BPS.

* Domicilio del paciente (opcional).
* Datos de la clínica como proveedor del BPS (opcionales).
* Primer nombre y primer apellido del responsable del paciente, por separado. Los
  responsables que ya existían quedan sin ellos y se piden al editarlos.

Revision ID: 0019_formulario_ayex
Revises: 0018_ci_responsable
Create Date: 2026-10-23
"""

import sqlalchemy as sa
from alembic import op

revision = "0019_formulario_ayex"
down_revision = "0018_ci_responsable"
branch_labels = None
depends_on = None

PATIENT_COLUMNS = [
    ("address_department", 40), ("address_locality", 80), ("address_street", 120),
    ("address_number", 20), ("address_apartment", 20), ("address_solar", 20), ("address_block", 20),
]
CLINIC_COLUMNS = [
    ("bps_provider_number", 30), ("bps_company_number", 30), ("phone", 40), ("email", 254),
    ("address_street", 120), ("address_number", 20), ("address_locality", 80),
    ("address_department", 40), ("address_annex", 40), ("monthly_budget", 40),
]

GUARDIAN_COLUMNS = ["first_name", "middle_name", "last_name", "second_last_name"]


def upgrade() -> None:
    for name, size in PATIENT_COLUMNS:
        op.add_column("patients", sa.Column(name, sa.String(size)))
    for name, size in CLINIC_COLUMNS:
        op.add_column("clinics", sa.Column(name, sa.String(size)))
    op.add_column("clinics", sa.Column("transport_included", sa.Boolean()))
    for name in GUARDIAN_COLUMNS:
        op.add_column("patient_guardians", sa.Column(name, sa.String(100)))


def downgrade() -> None:
    for name in reversed(GUARDIAN_COLUMNS):
        op.drop_column("patient_guardians", name)
    op.drop_column("clinics", "transport_included")
    for name, _ in reversed(CLINIC_COLUMNS):
        op.drop_column("clinics", name)
    for name, _ in reversed(PATIENT_COLUMNS):
        op.drop_column("patients", name)
