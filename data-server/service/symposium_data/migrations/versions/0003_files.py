"""Files and versions: collections with their sequence, payloads, files and versions.

Revision ID: 0003
Revises: 0002
"""

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        -- seq and last_created are the per-collection clock: every version written into the
        -- collection takes the next seq and a strictly later created, under this row's lock.
        CREATE TABLE collections (
            community    text NOT NULL,
            name         text NOT NULL,
            owner        text NOT NULL,
            seq          bigint NOT NULL DEFAULT 0,
            last_created timestamptz,
            PRIMARY KEY (community, name)
        );
        CREATE TABLE payloads (
            id          uuid PRIMARY KEY,
            sha256      text,
            size        bigint,
            state       text NOT NULL CHECK (state IN ('pending', 'ready', 'purging', 'purged')),
            s3_key      text NOT NULL,
            upload_id   text,
            first_owner text NOT NULL,
            created     timestamptz NOT NULL DEFAULT now(),
            scrubbed_at timestamptz,
            scrub_ok    boolean NOT NULL DEFAULT true
        );
        CREATE UNIQUE INDEX payloads_ready_sha ON payloads (sha256) WHERE state = 'ready';
        CREATE INDEX payloads_pending ON payloads (created) WHERE state = 'pending';
        -- A name is reserved (committed) before any bytes are streamed, so a concurrent
        -- duplicate fails at once; the file turns live in the same transaction as its v1.
        CREATE TABLE files (
            id          uuid PRIMARY KEY,
            community   text NOT NULL,
            collection  text NOT NULL,
            name        text NOT NULL,
            state       text NOT NULL DEFAULT 'live' CHECK (state IN ('reserved', 'live')),
            reserved_by text,
            reserved_at timestamptz,
            UNIQUE (community, collection, name),
            FOREIGN KEY (community, collection) REFERENCES collections (community, name)
        );
        CREATE INDEX files_reserved ON files (reserved_at) WHERE state = 'reserved';
        CREATE TABLE versions (
            file_id      uuid NOT NULL REFERENCES files (id),
            n            integer NOT NULL,
            payload_id   uuid NOT NULL REFERENCES payloads (id),
            metadata     jsonb NOT NULL DEFAULT '{}'::jsonb,
            content_type text NOT NULL DEFAULT 'application/octet-stream',
            created      timestamptz NOT NULL,
            seq          bigint NOT NULL,
            created_by   text NOT NULL,
            key_id       text,
            deleted      boolean NOT NULL DEFAULT false,
            reason       text,
            purged       boolean NOT NULL DEFAULT false,
            PRIMARY KEY (file_id, n)
        );
        CREATE INDEX versions_metadata ON versions USING GIN (metadata);
        CREATE INDEX versions_payload ON versions (payload_id);
        CREATE INDEX files_collection ON files (community, collection);
    """)


def downgrade():
    op.execute(
        "DROP TABLE versions; DROP TABLE files; DROP TABLE payloads; DROP TABLE collections;"
    )
