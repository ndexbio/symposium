"""The Symposium Data API's tables (api/DESIGN.md §1.3, §4.2, §10.5): API keys, the open streams
that the stream caps count, and the derived index of each community's record. A trigger
notifies the API's streams whenever a version is written, so they wake without polling.

Revision ID: 0008
Revises: 0007
"""

from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE api_keys (
            id          uuid PRIMARY KEY,
            hash        text NOT NULL UNIQUE,
            ciphertext  bytea,
            nonce       bytea,
            enc_kid     text,
            username    text NOT NULL,
            role        text NOT NULL CHECK (role IN ('non-member', 'member', 'admin')),
            admin_kid   text,
            community   text,
            label       text,
            created_by  text NOT NULL,
            created     timestamptz NOT NULL DEFAULT now(),
            expires     timestamptz,
            revoked     timestamptz,
            revoked_by  text,
            last_used   timestamptz,
            uses        bigint NOT NULL DEFAULT 0,
            CHECK (community IS NOT NULL OR role = 'admin'),
            CHECK ((role = 'admin') = (admin_kid IS NOT NULL))
        );
        CREATE INDEX api_keys_scope ON api_keys (community, username);

        CREATE TABLE api_streams (
            id          uuid PRIMARY KEY,
            key_id      uuid,
            role        text,
            client_addr text,
            opened      timestamptz NOT NULL DEFAULT now(),
            seen        timestamptz NOT NULL DEFAULT now()
        );

        CREATE TABLE api_index (
            community    text NOT NULL,
            name         text NOT NULL,
            seq          bigint NOT NULL,
            created      timestamptz NOT NULL,
            type         text NOT NULL,
            published_by text NOT NULL,
            file_id      uuid NOT NULL,
            sha256       text NOT NULL,
            doc          jsonb NOT NULL,
            findings     jsonb NOT NULL,
            PRIMARY KEY (community, name)
        );
        CREATE INDEX api_index_seq ON api_index (community, seq);

        CREATE TABLE api_citations (
            community    text NOT NULL,
            target       text NOT NULL,
            via          text NOT NULL,
            address      text NOT NULL,
            from_name    text NOT NULL,
            from_seq     bigint NOT NULL,
            from_created timestamptz NOT NULL,
            from_type    text NOT NULL,
            ground       text
        );
        CREATE INDEX api_citations_target ON api_citations (community, target, from_seq);

        CREATE TABLE api_index_position (
            community text PRIMARY KEY,
            seq       bigint NOT NULL
        );

        CREATE FUNCTION api_notify() RETURNS trigger AS $$
        BEGIN
            PERFORM pg_notify('symposium_api', '');
            RETURN NULL;
        END;
        $$ LANGUAGE plpgsql;
        CREATE TRIGGER versions_api_notify AFTER INSERT ON versions
            FOR EACH STATEMENT EXECUTE FUNCTION api_notify();
    """)


def downgrade():
    op.execute("""
        DROP TRIGGER versions_api_notify ON versions;
        DROP FUNCTION api_notify();
        DROP TABLE api_index_position;
        DROP TABLE api_citations;
        DROP TABLE api_index;
        DROP TABLE api_streams;
        DROP TABLE api_keys;
    """)
