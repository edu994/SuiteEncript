"""esquema inicial: crea users, passwords, encrypted_files, audit_logs

Se escribe a mano (no autogenerada) porque, cuando se creo la primera
migracion "baseline" (25c3d03285ea), se genero comparando contra Neon, que
ya tenia estas tablas desde antes de que existiera Alembic en el proyecto
(por el viejo db.create_all()). Esa migracion solo contiene los ALTER TABLE
que hacian falta ahi, nunca aprendio a crear las tablas desde cero. Contra
una base de datos nueva (por ejemplo, la de un `docker compose up` limpio,
o la que se usara en produccion en Render) no habia nada que las creara.
Esta migracion se inserta ANTES de la baseline (ver down_revision) para que
una base de datos vacia pueda llegar al mismo estado final que Neon.

Revision ID: d670eb48874a
Revises:
Create Date: 2026-08-22 10:57:50.562476

"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = 'd670eb48874a'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'users',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('username', sa.String(length=80), nullable=False),
        sa.Column('password_hash', sa.String(length=256), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.UniqueConstraint('username'),
    )

    op.create_table(
        'passwords',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('service', sa.String(length=120), nullable=False),
        sa.Column('username_site', sa.String(length=120), nullable=False),
        sa.Column('encrypted_password', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
    )

    op.create_table(
        'encrypted_files',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('original_filename', sa.String(length=255), nullable=False),
        sa.Column('stored_filename', sa.String(length=255), nullable=False),
        sa.Column('file_size_bytes', sa.Integer(), nullable=False),
        sa.Column('file_hash', sa.String(length=64), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('is_one_time_download', sa.Boolean(), nullable=True),
        sa.Column('download_count', sa.Integer(), nullable=True),
        sa.Column('expires_at', sa.DateTime(), nullable=True),
        sa.Column('share_token', sa.String(length=64), nullable=True),
        sa.Column('share_password_hash', sa.String(length=256), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.UniqueConstraint('stored_filename'),
        sa.UniqueConstraint('share_token'),
    )

    op.create_table(
        'audit_logs',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('action', sa.String(length=50), nullable=False),
        sa.Column('details', sa.String(length=255), nullable=True),
        sa.Column('ip_address', sa.String(length=45), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='SET NULL'),
    )


def downgrade():
    op.drop_table('audit_logs')
    op.drop_table('encrypted_files')
    op.drop_table('passwords')
    op.drop_table('users')
