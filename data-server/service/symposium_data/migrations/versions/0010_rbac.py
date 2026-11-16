"""Role-based access: users, their keys and role assignments.

Every identity becomes a user: the server's root (from server_config) is a server-level user
holding `server-root`; each (community, handle) owner or roster entry is a user homed in that
community. Grants become role assignments, collection owners become user ids, and the tables
of the per-community identity model go.

Revision ID: 0010
Revises: 0009
"""

import logging

from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None

log = logging.getLogger("symposium_data")

# what every roster member held by default: these become `community-member` on every collection
DEFAULTS = {
    ("inbox", "write"),
    ("files", "write"),
    ("files", "read"),
    ("record", "read"),
}


def upgrade():
    conn = op.get_bind()
    op.execute("""
        CREATE TABLE users (
            id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            handle        text NOT NULL,
            -- the user's community; NULL for a server-level user
            home          text REFERENCES communities (name),
            created       timestamptz NOT NULL DEFAULT now(),
            suspect_after timestamptz,
            -- a removed user stays as a tombstone: its handle is never used again
            removed       timestamptz,
            removed_by    text
        );
        CREATE UNIQUE INDEX users_handle ON users (COALESCE(home, ''), handle);

        CREATE TABLE user_keys (
            user_id uuid NOT NULL REFERENCES users (id) ON DELETE RESTRICT,
            kid     text NOT NULL,
            jwk     jsonb NOT NULL,
            active  boolean NOT NULL DEFAULT true,
            created timestamptz NOT NULL DEFAULT now(),
            retired timestamptz,
            PRIMARY KEY (user_id, kid)
        );
        CREATE UNIQUE INDEX user_keys_one_active ON user_keys (user_id) WHERE active;
        CREATE INDEX user_keys_kid ON user_keys (kid);

        ALTER TABLE api_keys ADD COLUMN user_id uuid REFERENCES users (id) ON DELETE RESTRICT;

        CREATE TABLE role_assignments (
            id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id     uuid REFERENCES users (id) ON DELETE RESTRICT,
            api_key_id  uuid REFERENCES api_keys (id) ON DELETE CASCADE,
            role_id     text NOT NULL,
            -- community-member and community-observer only: {*}, {} or collection names
            collections text[],
            created_by  text NOT NULL,
            created     timestamptz NOT NULL DEFAULT now(),
            revoked     timestamptz,
            revoked_by  text,
            CHECK ((user_id IS NULL) <> (api_key_id IS NULL))
        );
        CREATE UNIQUE INDEX role_assignments_user_live ON role_assignments (user_id, role_id)
            WHERE revoked IS NULL AND user_id IS NOT NULL;
        CREATE UNIQUE INDEX role_assignments_key_live ON role_assignments (api_key_id, role_id)
            WHERE revoked IS NULL AND api_key_id IS NOT NULL;
    """)

    admin = conn.exec_driver_sql(
        "SELECT v FROM server_config WHERE k = 'admin'"
    ).scalar()
    if admin is not None:
        root = conn.exec_driver_sql(
            "INSERT INTO users (handle) VALUES (%s) RETURNING id", (admin,)
        ).scalar()
        conn.exec_driver_sql(
            "INSERT INTO user_keys (user_id, kid, jwk, active, created, retired) "
            "SELECT %s, kid, jwk, active, created, retired FROM admin_keys WHERE handle = %s",
            (root, admin),
        )
        conn.exec_driver_sql(
            "INSERT INTO role_assignments (user_id, role_id, created_by) "
            "VALUES (%s, 'server-root', %s)",
            (root, admin),
        )
    else:
        root = None

    # every owner and every roster entry becomes a user homed in its community; an owner no
    # longer on the roster was removed, and stays as a tombstone
    op.execute(f"""
        INSERT INTO users (handle, home, created, suspect_after, removed, removed_by)
            SELECT o.handle, o.community, o.created, o.suspect_after,
                   CASE WHEN r.handle IS NULL THEN now() END,
                   CASE WHEN r.handle IS NULL THEN {_literal(admin)} END
            FROM owners o
            LEFT JOIN roster r ON r.community = o.community AND r.handle = o.handle;
        INSERT INTO users (handle, home)
            SELECT r.handle, r.community FROM roster r
            WHERE NOT EXISTS (
                SELECT 1 FROM owners o WHERE o.community = r.community AND o.handle = r.handle
            );
        INSERT INTO user_keys (user_id, kid, jwk, active, created, retired)
            SELECT u.id, k.kid, k.jwk, k.active, k.created, k.retired
            FROM owner_keys k JOIN users u ON u.home = k.community AND u.handle = k.handle;
    """)

    # grants become assignments
    rows = conn.exec_driver_sql(
        "SELECT u.id, u.handle, u.home, g.collection, g.perm FROM grants g "
        "JOIN users u ON u.home = g.community AND u.handle = g.handle AND u.removed IS NULL"
    ).fetchall()
    held: dict = {}
    for user_id, handle, home, collection, perm in rows:
        held.setdefault((user_id, handle, home), set()).add((collection, perm))
    for (user_id, handle, home), grants in held.items():
        role_id, names = _role_for(grants)
        if role_id == "community-observer" and any(p == "write" for _, p in grants):
            log.warning(
                "%s/%s held %s; it reads them as community-observer on %s",
                home,
                handle,
                sorted(grants),
                names,
            )
        conn.exec_driver_sql(
            "INSERT INTO role_assignments (user_id, role_id, collections, created_by) "
            "VALUES (%s, %s, %s, %s)",
            (user_id, role_id, names, admin or "migration"),
        )
    # roster entries without grants, and the authors a port added, still count as members
    conn.exec_driver_sql(
        "INSERT INTO role_assignments (user_id, role_id, collections, created_by) "
        "SELECT u.id, 'community-member', '{*}', %s FROM users u "
        "WHERE u.home IS NOT NULL AND u.removed IS NULL AND NOT EXISTS ("
        "SELECT 1 FROM role_assignments a WHERE a.user_id = u.id)",
        (admin or "migration",),
    )
    # every key starts afresh: sessions are signed in again, and keys are issued with roles
    op.execute("DELETE FROM api_keys")

    # collection owners become user ids: the owner's user in that community, or root
    op.execute(f"""
        ALTER TABLE collections ADD COLUMN owner_id uuid REFERENCES users (id) ON DELETE RESTRICT;
        UPDATE collections c SET owner_id = u.id FROM users u
            WHERE u.home = c.community AND u.handle = c.owner;
        UPDATE collections SET owner_id = {_literal(root)}::uuid WHERE owner_id IS NULL;
        ALTER TABLE collections DROP COLUMN owner;
        ALTER TABLE collections RENAME COLUMN owner_id TO owner;
    """)

    # invites carry their home and roles from here on
    op.execute("""
        DROP TABLE invites;
        CREATE TABLE invites (
            hash       text PRIMARY KEY,
            secret     text,
            handle     text NOT NULL,
            home       text REFERENCES communities (name),
            roles      jsonb NOT NULL DEFAULT '[]'::jsonb,
            user_id    uuid REFERENCES users (id) ON DELETE RESTRICT,
            created_by text NOT NULL,
            created    timestamptz NOT NULL DEFAULT now(),
            expires    timestamptz NOT NULL,
            used       timestamptz,
            revoked    timestamptz
        );
        CREATE INDEX invites_pending ON invites (home, handle)
            WHERE used IS NULL AND revoked IS NULL;

        DROP TABLE challenges;
        CREATE TABLE challenges (
            nonce   text PRIMARY KEY,
            handle  text NOT NULL,
            home    text,
            expires timestamptz NOT NULL
        );

        -- dropping role drops the checks written on it; the kind/label/ed25519_kid checks stay
        ALTER TABLE api_keys DROP COLUMN role;
        ALTER TABLE api_keys DROP COLUMN revoked;
        ALTER TABLE api_keys DROP COLUMN revoked_by;
        ALTER TABLE api_keys ADD CHECK (kind = 'session' OR community IS NOT NULL);
        ALTER TABLE api_keys ADD CHECK (kind = 'issued' OR user_id IS NOT NULL);
        DROP INDEX IF EXISTS api_keys_label;
        CREATE UNIQUE INDEX api_keys_label ON api_keys (community, created_by, label)
            WHERE kind = 'issued';
        CREATE INDEX api_keys_user ON api_keys (user_id);

        DROP TABLE grants;
        DROP TABLE roster;
        DROP TABLE owner_keys;
        DROP TABLE owners;
        DROP TABLE admin_keys;
        DELETE FROM server_config WHERE k = 'admin';
    """)


def _role_for(grants: set) -> tuple:
    """The assignment that expresses one member's grants: `community-member` on every
    collection for the default grants, else `community-observer` on what it could read, which
    never widens what it held."""
    if DEFAULTS <= grants:
        return "community-member", ["*"]
    reads = sorted({c for c, p in grants if p == "read" and c != "inbox"})
    return "community-observer", reads


def _literal(value) -> str:
    if value is None:
        return "NULL"
    return "'" + str(value).replace("'", "''") + "'"


def downgrade():
    raise RuntimeError(
        "0010 converts identities to users and roles and cannot be reversed"
    )
