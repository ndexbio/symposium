"""Identity: rosters, default grants, invites, challenges, key retirement and suspicion.

Revision ID: 0002
Revises: 0001
"""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        ALTER TABLE owners ADD COLUMN suspect_after timestamptz;
        ALTER TABLE owner_keys ADD COLUMN retired timestamptz;

        CREATE TABLE roster (
            community text NOT NULL,
            handle    text NOT NULL,
            PRIMARY KEY (community, handle)
        );
        -- Grants name collections by community and name; the collections themselves arrive
        -- with the file model, so there is deliberately no foreign key here.
        CREATE TABLE grants (
            community  text NOT NULL,
            collection text NOT NULL,
            handle     text NOT NULL,
            perm       text NOT NULL CHECK (perm IN ('read', 'write')),
            PRIMARY KEY (community, collection, handle, perm)
        );
        CREATE TABLE invites (
            hash      text PRIMARY KEY,
            community text NOT NULL,
            handle    text NOT NULL,
            expires   timestamptz NOT NULL,
            used      timestamptz
        );
        CREATE TABLE challenges (
            nonce   text PRIMARY KEY,
            handle  text NOT NULL,
            expires timestamptz NOT NULL
        );
    """)


def downgrade():
    op.execute("""
        DROP TABLE challenges; DROP TABLE invites; DROP TABLE grants; DROP TABLE roster;
        ALTER TABLE owner_keys DROP COLUMN retired;
        ALTER TABLE owners DROP COLUMN suspect_after;
    """)
