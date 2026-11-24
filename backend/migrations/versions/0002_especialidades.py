"""Especialidades editables por clínica.

Antes la especialidad de un profesional era un valor fijo en el código
('psychology' u 'occupational_therapy'). Ahora es una tabla `specialties`
que Administración puede ampliar (por ejemplo, Fonoaudiología).

La migración conserva los datos: crea "Psicología" y "Terapia ocupacional"
en cada clínica y vincula a cada profesional con la que tenía.

Revision ID: 0002_especialidades
Revises: 0001_inicial
Create Date: 2026-10-17
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0002_especialidades"
down_revision = "0001_inicial"
branch_labels = None
depends_on = None

UUID = postgresql.UUID(as_uuid=True)

# Valores antiguos -> nombre visible de la nueva tabla.
LEGACY = {"psychology": "Psicología", "occupational_therapy": "Terapia ocupacional"}


def upgrade() -> None:
    op.create_table(
        "specialties",
        sa.Column("id", UUID, primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("clinic_id", UUID, sa.ForeignKey("clinics.id"), nullable=False),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.UniqueConstraint("clinic_id", "id", name="uq_specialties_clinic_id"),
    )
    op.create_index("uq_specialties_clinic_name", "specialties",
                    ["clinic_id", sa.text("lower(name)")], unique=True)

    # Especialidades iniciales en cada clínica existente.
    for name in LEGACY.values():
        op.execute(
            sa.text("INSERT INTO specialties (clinic_id, name) SELECT id, :name FROM clinics")
            .bindparams(name=name)
        )

    op.add_column("users", sa.Column("specialty_id", UUID))
    for legacy, name in LEGACY.items():
        op.execute(
            sa.text(
                "UPDATE users u SET specialty_id = s.id FROM specialties s "
                "WHERE s.clinic_id = u.clinic_id AND s.name = :name AND u.specialty = :legacy"
            ).bindparams(name=name, legacy=legacy)
        )
    op.create_foreign_key(
        "fk_users_specialty", "users", "specialties",
        ["clinic_id", "specialty_id"], ["clinic_id", "id"],
    )
    op.drop_constraint("ck_users_specialty", "users", type_="check")
    op.drop_column("users", "specialty")


def downgrade() -> None:
    # Vuelve a la columna fija. Las especialidades nuevas (p. ej. Fonoaudiología) no
    # existían antes: esos profesionales quedan sin especialidad.
    op.add_column("users", sa.Column("specialty", sa.String(40)))
    for legacy, name in LEGACY.items():
        op.execute(
            sa.text(
                "UPDATE users u SET specialty = :legacy FROM specialties s "
                "WHERE s.id = u.specialty_id AND s.name = :name"
            ).bindparams(name=name, legacy=legacy)
        )
    op.create_check_constraint(
        "ck_users_specialty", "users",
        "specialty IS NULL OR specialty IN ('psychology', 'occupational_therapy')",
    )
    op.drop_constraint("fk_users_specialty", "users", type_="foreignkey")
    op.drop_column("users", "specialty_id")
    op.drop_index("uq_specialties_clinic_name", table_name="specialties")
    op.drop_table("specialties")
