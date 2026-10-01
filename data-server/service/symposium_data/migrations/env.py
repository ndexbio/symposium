"""Alembic environment. Migrations always run on the connection Database.migrate() provides,
inside its advisory lock; there is no standalone alembic.ini."""

from alembic import context

connection = context.config.attributes["connection"]
context.configure(connection=connection)
with context.begin_transaction():
    context.run_migrations()
