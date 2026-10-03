"""Ports run inside the service (R-M1): one row per port, started by the admin into an existing
empty community and checked by its id. At most one runs at a time, server-wide. The sentinels
of the one-time start-up port are dropped: a port is now refused by its community's files.

Revision ID: 0007
Revises: 0006
"""

from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE ports (
            id        uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            community text NOT NULL REFERENCES communities (name),
            source    text NOT NULL,
            state     text NOT NULL DEFAULT 'running'
                      CHECK (state IN ('running', 'ok', 'refused', 'failed')),
            result    jsonb,
            started   timestamptz NOT NULL DEFAULT now(),
            finished  timestamptz
        );
        CREATE UNIQUE INDEX ports_one_running ON ports ((true)) WHERE state = 'running';
        DELETE FROM server_config WHERE k IN ('port_source', 'port_admin');
    """)


def downgrade():
    op.execute("DROP TABLE ports;")
