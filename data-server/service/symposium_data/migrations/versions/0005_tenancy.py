"""Communities as tenants (R-G8): a communities table, identity per (community, handle), the
server admin in its own table, and payloads deduplicated within a community.

Existing rows are converted: each owner becomes one owner per community whose roster lists it,
with its keys; the admin's keys move to admin_keys; each payload takes the community of the
first version that references it.

Revision ID: 0005
Revises: 0004
"""

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        -- A name keeps the case it was created with, and is unique ignoring case.
        CREATE TABLE communities (
            name    text PRIMARY KEY,
            created timestamptz NOT NULL DEFAULT now()
        );
        CREATE UNIQUE INDEX communities_name_ci ON communities (lower(name));
        INSERT INTO communities (name)
            SELECT community FROM collections UNION SELECT community FROM roster;
        ALTER TABLE collections ADD FOREIGN KEY (community) REFERENCES communities (name);
        ALTER TABLE roster ADD FOREIGN KEY (community) REFERENCES communities (name);

        -- The server-wide admin, bound from its key file, is not a member of any community.
        CREATE TABLE admin_keys (
            kid     text PRIMARY KEY,
            handle  text NOT NULL,
            jwk     jsonb NOT NULL,
            active  boolean NOT NULL DEFAULT true,
            created timestamptz NOT NULL DEFAULT now(),
            retired timestamptz
        );
        INSERT INTO admin_keys (kid, handle, jwk, active, created, retired)
            SELECT k.kid, k.handle, k.jwk, k.active, k.created, k.retired
            FROM owner_keys k JOIN server_config c ON c.k = 'admin' AND c.v = k.handle;

        -- An owner is a (community, handle) pair with its own keys.
        CREATE TABLE community_owners (
            community     text NOT NULL REFERENCES communities (name),
            handle        text NOT NULL,
            reserved      boolean NOT NULL DEFAULT false,
            created       timestamptz NOT NULL DEFAULT now(),
            suspect_after timestamptz,
            PRIMARY KEY (community, handle)
        );
        INSERT INTO community_owners (community, handle, reserved, created, suspect_after)
            SELECT r.community, o.handle, o.reserved, o.created, o.suspect_after
            FROM owners o JOIN roster r ON r.handle = o.handle;
        CREATE TABLE community_owner_keys (
            community text NOT NULL,
            kid       text NOT NULL,
            handle    text NOT NULL,
            jwk       jsonb NOT NULL,
            active    boolean NOT NULL DEFAULT true,
            created   timestamptz NOT NULL DEFAULT now(),
            retired   timestamptz,
            PRIMARY KEY (community, kid),
            FOREIGN KEY (community, handle) REFERENCES community_owners (community, handle)
        );
        INSERT INTO community_owner_keys (community, kid, handle, jwk, active, created, retired)
            SELECT o.community, k.kid, k.handle, k.jwk, k.active, k.created, k.retired
            FROM owner_keys k JOIN community_owners o ON o.handle = k.handle;
        DROP TABLE owner_keys;
        DROP TABLE owners;
        ALTER TABLE community_owners RENAME TO owners;
        ALTER TABLE community_owner_keys RENAME TO owner_keys;

        -- A challenge belongs to a community's handle, or (NULL) to the server admin.
        DELETE FROM challenges;
        ALTER TABLE challenges ADD COLUMN community text;

        -- Content is deduplicated within a community; quota is per (community, handle).
        ALTER TABLE payloads ADD COLUMN community text;
        UPDATE payloads p SET community = (
            SELECT f.community FROM versions v JOIN files f ON f.id = v.file_id
            WHERE v.payload_id = p.id ORDER BY v.seq LIMIT 1
        );
        DROP INDEX payloads_ready_sha;
        CREATE UNIQUE INDEX payloads_ready_sha ON payloads (community, sha256)
            WHERE state = 'ready';
    """)


def downgrade():
    raise RuntimeError("0005 converts identities per community and cannot be reversed")
