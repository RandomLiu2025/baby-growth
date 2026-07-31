from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text

from . import backup


BASELINE_REVISION = "20260730_0001"
SERVER_ROOT = Path(__file__).resolve().parents[1]
BUSINESS_TABLES = {"users", "baby", "settings"}


def _config(database_url: str) -> Config:
    config = Config(str(SERVER_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(SERVER_ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    return config


def sqlite_path(database_url: str) -> Path | None:
    prefix = "sqlite:///"
    if not database_url.startswith(prefix) or database_url.endswith(":memory:"):
        return None
    return Path(database_url[len(prefix):])


def _revision(engine):
    with engine.connect() as connection:
        return MigrationContext.configure(connection).get_current_revision()


def _head(config: Config):
    return ScriptDirectory.from_config(config).get_current_head()


def _legacy_normalize(engine) -> None:
    additions = {
        "photos": [("desc", "TEXT DEFAULT ''")],
        "users": [("role", "TEXT DEFAULT 'member'"), ("disabled", "INTEGER DEFAULT 0")],
    }
    with engine.begin() as connection:
        for table, columns in additions.items():
            existing = {row[1] for row in connection.execute(text(f"PRAGMA table_info({table})"))}
            for column, declaration in columns:
                if column not in existing:
                    connection.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {declaration}"))


def _backup_if_possible(database_url, upload_dir, backup_dir, retention, reason):
    database_path = sqlite_path(database_url)
    if not database_path or not database_path.is_file() or database_path.stat().st_size == 0:
        return None
    return backup.create_backup(reason, database_path, upload_dir, backup_dir, retention)


def upgrade_database(
    database_url: str,
    upload_dir,
    backup_dir,
    retention: int = 2,
    auto_backup: bool = True,
):
    config = _config(database_url)
    engine = create_engine(database_url, future=True)
    try:
        tables = set(inspect(engine).get_table_names())
        current = _revision(engine) if "alembic_version" in tables else None
        head = _head(config)
        backup_info = None
        if not tables or not (tables & BUSINESS_TABLES):
            command.upgrade(config, "head")
            return {"mode": "upgrade", "from": current, "to": head, "backupId": None}
        if "alembic_version" not in tables:
            if auto_backup:
                backup_info = _backup_if_possible(
                    database_url, upload_dir, backup_dir, retention, "pre-migration"
                )
            if database_url.startswith("sqlite"):
                _legacy_normalize(engine)
            command.stamp(config, BASELINE_REVISION)
            if BASELINE_REVISION != head:
                command.upgrade(config, "head")
            return {"mode": "stamp", "from": None, "to": head,
                    "backupId": backup_info.get("backupId") if backup_info else None}
        if current == head:
            return {"mode": "current", "from": current, "to": head, "backupId": None}
        if auto_backup:
            backup_info = _backup_if_possible(database_url, upload_dir, backup_dir, retention, "pre-migration")
        command.upgrade(config, "head")
        return {"mode": "upgrade", "from": current, "to": head,
                "backupId": backup_info.get("backupId") if backup_info else None}
    finally:
        engine.dispose()
