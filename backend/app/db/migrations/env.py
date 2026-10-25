from alembic import context

from app.config import Settings
from app.db.engine import open_database
from app.db.tables import metadata


def run(connection) -> None:
    context.configure(
        connection=connection, target_metadata=metadata, render_as_batch=True
    )
    with context.begin_transaction():
        context.run_migrations()


connection = context.config.attributes.get("connection")
if connection is not None:
    run(connection)
else:
    with open_database(Settings.from_env().database_path).begin() as connection:
        run(connection)
