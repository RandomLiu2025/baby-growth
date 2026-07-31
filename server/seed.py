"""初始化数据库并填充示例数据。用法：在 server/ 目录下执行 python seed.py"""
import sys

from app import backup, migrations
from app.config import settings
from app.db import SessionLocal
from app.main import ensure_init
from app.sampledata import seed_sample


def main():
    database_path = migrations.sqlite_path(settings.DATABASE_URL)
    migrations.upgrade_database(
        settings.DATABASE_URL,
        settings.UPLOAD_DIR,
        settings.BACKUP_DIR,
        settings.BACKUP_RETENTION,
        settings.AUTO_BACKUP_BEFORE_MIGRATION,
    )
    db = SessionLocal()
    try:
        ensure_init(db)
        if database_path and database_path.exists():
            created = backup.create_backup(
                "pre-seed", database_path, settings.UPLOAD_DIR,
                settings.BACKUP_DIR, settings.BACKUP_RETENTION,
            )
            sys.stdout.write(f"已创建重置前备份：{created['backupId']}\n")
        seed_sample(db, reset=True)
        sys.stdout.write("已填充示例数据。\n")
        sys.stdout.write("管理员账号见 .env。\n")
    finally:
        db.close()


if __name__ == "__main__":
    main()
