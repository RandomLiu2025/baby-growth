import argparse
import json
import sys

from . import backup, migrations
from .config import settings


def _database_path():
    path = migrations.sqlite_path(settings.DATABASE_URL)
    if not path:
        raise SystemExit("完整备份与恢复 CLI 仅支持 SQLite")
    return path


def main(argv=None):
    parser = argparse.ArgumentParser(description="宝贝成长记完整备份工具")
    subparsers = parser.add_subparsers(dest="command", required=True)
    create_parser = subparsers.add_parser("create")
    create_parser.add_argument("--reason", default="manual-cli")
    subparsers.add_parser("list")
    verify_parser = subparsers.add_parser("verify")
    verify_parser.add_argument("archive")
    drill_parser = subparsers.add_parser("drill")
    drill_parser.add_argument("archive")
    restore_parser = subparsers.add_parser("restore")
    restore_parser.add_argument("archive")
    args = parser.parse_args(argv)

    if args.command == "create":
        result = backup.create_backup(
            args.reason, _database_path(), settings.UPLOAD_DIR,
            settings.BACKUP_DIR, settings.BACKUP_RETENTION,
        )
    elif args.command == "list":
        result = backup.list_backups(settings.BACKUP_DIR)
    elif args.command == "verify":
        result = backup.verify_backup(args.archive)
    elif args.command == "drill":
        result = backup.restore_drill(args.archive)
    else:
        result = backup.restore_backup(
            args.archive, _database_path(), settings.UPLOAD_DIR,
            settings.BACKUP_DIR, settings.BACKUP_RETENTION,
        )
    sys.stdout.write(json.dumps(result, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
