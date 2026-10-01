from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app import models  # noqa: F401  (registers tables)
from app.db import Base

config = context.config
if config.config_file_name and config.attributes.get("configure_logger", True):
    fileConfig(config.config_file_name, disable_existing_loggers=False)
target_metadata = Base.metadata


def include_object(obj, name, type_, reflected, compare_to):  # FTS5 shadow tables are managed by raw SQL
    return not (type_ == "table" and name and name.startswith("messages_fts"))


def run_migrations_online() -> None:
    connectable = engine_from_config(config.get_section(config.config_ini_section, {}), prefix="sqlalchemy.", poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, render_as_batch=True, include_object=include_object)
        with context.begin_transaction():
            context.run_migrations()


run_migrations_online()
