"""Sharing: public collections and read keys for non-members.

Revision ID: 0004
Revises: 0003
"""

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        ALTER TABLE collections ADD COLUMN public boolean NOT NULL DEFAULT false;

        -- Read keys let non-members read a collection, or one file in it. Only the hash of
        -- the secret is stored; every use is counted and timestamped.
        CREATE TABLE read_keys (
            id         uuid PRIMARY KEY,
            hash       text NOT NULL UNIQUE,
            community  text NOT NULL,
            collection text NOT NULL,
            file_id    uuid REFERENCES files (id),
            label      text NOT NULL,
            created_by text NOT NULL,
            created    timestamptz NOT NULL DEFAULT now(),
            expires    timestamptz,
            revoked    timestamptz,
            uses       bigint NOT NULL DEFAULT 0,
            last_used  timestamptz,
            FOREIGN KEY (community, collection) REFERENCES collections (community, name)
        );
        CREATE INDEX read_keys_collection ON read_keys (community, collection);
    """)


def downgrade():
    op.execute("DROP TABLE read_keys; ALTER TABLE collections DROP COLUMN public;")
