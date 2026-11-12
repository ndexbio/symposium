"""Retrievable pending invites (R-D6): an invite keeps its secret while it is pending, so the
admin can fetch it again, and loses it the moment it is used, expires or is revoked. Issuing a
new invite for a handle revokes the earlier unused one. Registration still checks the hash.

Revision ID: 0006
Revises: 0005
"""

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        ALTER TABLE invites ADD COLUMN secret text;
        ALTER TABLE invites ADD COLUMN revoked timestamptz;
        CREATE INDEX invites_pending ON invites (community, handle)
            WHERE used IS NULL AND revoked IS NULL;
    """)


def downgrade():
    op.execute("""
        DROP INDEX invites_pending;
        ALTER TABLE invites DROP COLUMN revoked;
        ALTER TABLE invites DROP COLUMN secret;
    """)
