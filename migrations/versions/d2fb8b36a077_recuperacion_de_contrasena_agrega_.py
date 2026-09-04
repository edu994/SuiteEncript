"""Recuperación de contraseña: agrega email y reset_token a users

Se escribe a mano (no autogenerada) siguiendo el mismo criterio ya
documentado en las migraciones anteriores: cambio simple y predecible
(agregar 3 columnas nullable), revisado a mano antes de aplicar en vez de
confiar ciegamente en el autogenerado.

Revision ID: d2fb8b36a077
Revises: dd3e6766ea93
Create Date: 2026-08-27 00:00:00.000000

"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = 'd2fb8b36a077'
down_revision = 'dd3e6766ea93'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('email', sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column('reset_token', sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column('reset_token_expires_at', sa.DateTime(), nullable=True))
        batch_op.create_unique_constraint('uq_users_email', ['email'])
        batch_op.create_unique_constraint('uq_users_reset_token', ['reset_token'])


def downgrade():
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_constraint('uq_users_reset_token', type_='unique')
        batch_op.drop_constraint('uq_users_email', type_='unique')
        batch_op.drop_column('reset_token_expires_at')
        batch_op.drop_column('reset_token')
        batch_op.drop_column('email')
