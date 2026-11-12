"""One API, one key format: every caller presents an API key, and collections decide access.

`api_keys` holds every key the server issues. A session key comes from the session management routes and
lasts minutes; an issued key is made by a signed-in caller for an application and lasts until
it is revoked or expires. Grants name a Member or a non-member key, so an application reads a
collection the same way a Member does. Read keys (`read_keys`) are gone: a file has its
collection's access.

Revision ID: 0009
Revises: 0008
"""

from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        DROP TABLE read_keys;
        DROP TABLE api_keys;

        CREATE TABLE api_keys (
            id          uuid PRIMARY KEY,
            hash        text NOT NULL UNIQUE,
            kind        text NOT NULL CHECK (kind IN ('session', 'issued')),
            role        text NOT NULL CHECK (role IN ('admin', 'member', 'non-member')),
            -- the key's community; an admin session works in every community
            community   text,
            -- the Member a member key acts as, or the admin; a non-member key names nobody
            handle      text,
            label       text,
            -- the public key whose private key file obtained a session: retiring it ends the session
            ed25519_kid text,
            -- issued keys only: the value, sealed so its owner can read it back
            ciphertext  bytea,
            nonce       bytea,
            enc_kid     text,
            created_by  text NOT NULL,
            created     timestamptz NOT NULL DEFAULT now(),
            expires     timestamptz,
            revoked     timestamptz,
            revoked_by  text,
            last_used   timestamptz,
            CHECK ((role = 'non-member') = (handle IS NULL)),
            CHECK (role <> 'admin' OR kind = 'session'),
            CHECK ((community IS NULL) = (role = 'admin')),
            CHECK ((kind = 'session') = (ed25519_kid IS NOT NULL)),
            CHECK ((kind = 'issued') = (label IS NOT NULL))
        );
        CREATE INDEX api_keys_handle ON api_keys (community, handle);
        CREATE INDEX api_keys_issuer ON api_keys (community, created_by);
        CREATE INDEX api_keys_session ON api_keys (ed25519_kid) WHERE kind = 'session';
        CREATE UNIQUE INDEX api_keys_label ON api_keys (community, created_by, label)
            WHERE kind = 'issued' AND revoked IS NULL;

        ALTER TABLE grants DROP CONSTRAINT grants_pkey;
        ALTER TABLE grants ALTER COLUMN handle DROP NOT NULL;
        ALTER TABLE grants
            ADD COLUMN api_key_id uuid REFERENCES api_keys (id) ON DELETE CASCADE;
        ALTER TABLE grants ADD CHECK ((handle IS NULL) <> (api_key_id IS NULL));
        ALTER TABLE grants ADD CHECK (api_key_id IS NULL OR perm = 'read');
        CREATE UNIQUE INDEX grants_member ON grants (community, collection, handle, perm)
            WHERE handle IS NOT NULL;
        CREATE UNIQUE INDEX grants_key ON grants (community, collection, api_key_id, perm)
            WHERE api_key_id IS NOT NULL;
    """)


def downgrade():
    op.execute("""
        DELETE FROM grants WHERE api_key_id IS NOT NULL;
        DROP INDEX grants_key;
        DROP INDEX grants_member;
        ALTER TABLE grants DROP COLUMN api_key_id;
        ALTER TABLE grants ALTER COLUMN handle SET NOT NULL;
        ALTER TABLE grants ADD PRIMARY KEY (community, collection, handle, perm);

        DROP TABLE api_keys;
        CREATE TABLE api_keys (
            id          uuid PRIMARY KEY,
            hash        text NOT NULL UNIQUE,
            ciphertext  bytea,
            nonce       bytea,
            enc_kid     text,
            community   text NOT NULL,
            role        text NOT NULL CHECK (role IN ('non-member', 'member')),
            handle      text,
            label       text NOT NULL,
            created_by  text NOT NULL,
            created     timestamptz NOT NULL DEFAULT now(),
            expires     timestamptz,
            revoked     timestamptz,
            revoked_by  text,
            last_used   timestamptz,
            uses        bigint NOT NULL DEFAULT 0,
            CHECK ((role = 'member') = (handle IS NOT NULL))
        );
        CREATE INDEX api_keys_owner ON api_keys (community, handle);
        CREATE UNIQUE INDEX api_keys_member_label ON api_keys (community, handle, label)
            WHERE revoked IS NULL AND handle IS NOT NULL;
        CREATE UNIQUE INDEX api_keys_app_label ON api_keys (community, label)
            WHERE revoked IS NULL AND handle IS NULL;

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
