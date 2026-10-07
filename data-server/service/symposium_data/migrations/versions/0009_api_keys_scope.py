"""API keys belong to one community each and are `non-member` or `member` (api/DESIGN.md §4).
The Control API issues them at `/v1/{community}/api-keys`; the Data API only authenticates
with them, so a key bound to the server's admin key, or scoped to the whole server, is gone.

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
        DELETE FROM api_keys WHERE role = 'admin' OR community IS NULL;
        DO $$
        DECLARE c record;
        BEGIN
            FOR c IN SELECT conname FROM pg_constraint
                     WHERE conrelid = 'api_keys'::regclass AND contype = 'c'
            LOOP
                EXECUTE format('ALTER TABLE api_keys DROP CONSTRAINT %I', c.conname);
            END LOOP;
        END $$;
        ALTER TABLE api_keys DROP COLUMN admin_kid;
        ALTER TABLE api_keys ALTER COLUMN community SET NOT NULL;
        ALTER TABLE api_keys ADD CONSTRAINT api_keys_role
            CHECK (role IN ('non-member', 'member'));
    """)


def downgrade():
    op.execute("""
        ALTER TABLE api_keys DROP CONSTRAINT api_keys_role;
        ALTER TABLE api_keys ALTER COLUMN community DROP NOT NULL;
        ALTER TABLE api_keys ADD COLUMN admin_kid text;
        ALTER TABLE api_keys ADD CONSTRAINT api_keys_role
            CHECK (role IN ('non-member', 'member', 'admin'));
        ALTER TABLE api_keys ADD CONSTRAINT api_keys_scope_check
            CHECK (community IS NOT NULL OR role = 'admin');
        ALTER TABLE api_keys ADD CONSTRAINT api_keys_admin_check
            CHECK ((role = 'admin') = (admin_kid IS NOT NULL));
    """)
