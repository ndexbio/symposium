"""Baseline: server configuration and owner identities.

Revision ID: 0001
Revises:
"""

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE server_config (
            k text PRIMARY KEY,
            v text NOT NULL
        );
        CREATE TABLE owners (
            handle   text PRIMARY KEY,
            reserved boolean NOT NULL DEFAULT false,
            created  timestamptz NOT NULL DEFAULT now()
        );
        CREATE TABLE owner_keys (
            kid     text PRIMARY KEY,
            handle  text NOT NULL REFERENCES owners(handle),
            jwk     jsonb NOT NULL,
            active  boolean NOT NULL DEFAULT true,
            created timestamptz NOT NULL DEFAULT now()
        );
    """)


def downgrade():
    op.execute("DROP TABLE owner_keys; DROP TABLE owners; DROP TABLE server_config;")
