from functools import wraps
import hashlib
import json
import os
import shutil
import sqlite3
import stat
import tempfile
import threading
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath


BACKUP_FORMAT_VERSION = 1
_BACKUP_LOCK = threading.RLock()


class BackupValidationError(Exception):
    pass


def _serialized(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        with _BACKUP_LOCK:
            return function(*args, **kwargs)
    return wrapped


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_member(archive: zipfile.ZipFile, name: str) -> str:
    digest = hashlib.sha256()
    with archive.open(name) as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_member(info: zipfile.ZipInfo) -> None:
    path = PurePosixPath(info.filename)
    mode = info.external_attr >> 16
    if path.is_absolute() or ".." in path.parts or stat.S_ISLNK(mode):
        raise BackupValidationError(f"备份包含不安全路径：{info.filename}")


def _snapshot_sqlite(source_path: Path, destination_path: Path) -> None:
    if not source_path.is_file():
        raise BackupValidationError(f"数据库文件不存在：{source_path}")
    source = sqlite3.connect(f"file:{source_path}?mode=ro", uri=True)
    destination = sqlite3.connect(destination_path)
    try:
        source.backup(destination)
    finally:
        destination.close()
        source.close()


def _upload_files(upload_dir: Path):
    if not upload_dir.exists():
        return []
    files = []
    for root, directories, names in os.walk(upload_dir):
        directories[:] = [name for name in directories if name != ".chunks"]
        root_path = Path(root)
        for name in names:
            path = root_path / name
            if path.is_file() and not path.is_symlink() and not name.endswith((".uploading", ".tmp")):
                files.append(path)
    return sorted(files)


@_serialized
def create_backup(
    reason: str,
    database_path,
    upload_dir,
    backup_dir,
    retention: int = 2,
):
    database_path = Path(database_path)
    upload_dir = Path(upload_dir)
    backup_dir = Path(backup_dir)
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_id = f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"
    final_path = backup_dir / f"backup-{backup_id}.zip"
    temp_archive = backup_dir / f".{backup_id}.tmp"

    with tempfile.TemporaryDirectory(prefix="backup-work-", dir=backup_dir) as work:
        snapshot_path = Path(work) / "baby.db"
        _snapshot_sqlite(database_path, snapshot_path)
        upload_hashes = {}
        upload_bytes = 0
        files = _upload_files(upload_dir)
        with zipfile.ZipFile(temp_archive, "w", compression=zipfile.ZIP_STORED, allowZip64=True) as archive:
            archive.write(snapshot_path, "database/baby.db")
            for path in files:
                relative = path.relative_to(upload_dir).as_posix()
                archive_name = f"uploads/{relative}"
                archive.write(path, archive_name)
                upload_hashes[archive_name] = _sha256_file(path)
                upload_bytes += path.stat().st_size
            manifest = {
                "formatVersion": BACKUP_FORMAT_VERSION,
                "backupId": backup_id,
                "createdAt": datetime.now(timezone.utc).isoformat(),
                "reason": str(reason or "manual")[:80],
                "database": {
                    "path": "database/baby.db",
                    "sha256": _sha256_file(snapshot_path),
                    "bytes": snapshot_path.stat().st_size,
                },
                "uploads": {
                    "files": len(files),
                    "bytes": upload_bytes,
                    "sha256": upload_hashes,
                },
            }
            archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))

    verify_backup(temp_archive)
    os.chmod(temp_archive, 0o600)
    os.replace(temp_archive, final_path)
    _apply_retention(backup_dir, retention)
    return {**manifest, "path": str(final_path), "bytes": final_path.stat().st_size}


def verify_backup(archive_path):
    archive_path = Path(archive_path)
    try:
        with zipfile.ZipFile(archive_path) as archive:
            infos = archive.infolist()
            for info in infos:
                _safe_member(info)
            if len({info.filename for info in infos}) != len(infos):
                raise BackupValidationError("备份包含重复文件名")
            names = {info.filename for info in infos}
            if "manifest.json" not in names:
                raise BackupValidationError("备份缺少 manifest.json")
            try:
                manifest = json.loads(archive.read("manifest.json"))
            except (ValueError, KeyError, UnicodeDecodeError) as exc:
                raise BackupValidationError("备份 manifest 无法解析") from exc
            if manifest.get("formatVersion") != BACKUP_FORMAT_VERSION:
                raise BackupValidationError("不支持的备份格式版本")
            database = manifest.get("database") or {}
            database_name = database.get("path")
            if database_name not in names:
                raise BackupValidationError("备份缺少数据库快照")
            if _sha256_member(archive, database_name) != database.get("sha256"):
                raise BackupValidationError("数据库快照摘要不一致")
            upload_hashes = ((manifest.get("uploads") or {}).get("sha256") or {})
            payload_names = {info.filename for info in infos if not info.is_dir()}
            expected_names = {"manifest.json", database_name, *upload_hashes.keys()}
            if payload_names != expected_names:
                raise BackupValidationError("备份包含 manifest 未声明的文件")
            for name, expected in upload_hashes.items():
                if name not in names or _sha256_member(archive, name) != expected:
                    raise BackupValidationError(f"上传文件摘要不一致：{name}")
            return manifest
    except zipfile.BadZipFile as exc:
        raise BackupValidationError("备份 ZIP 已损坏") from exc


def list_backups(backup_dir):
    backup_dir = Path(backup_dir)
    if not backup_dir.exists():
        return []
    results = []
    for path in sorted(backup_dir.glob("backup-*.zip"), key=lambda item: item.stat().st_mtime, reverse=True):
        try:
            with zipfile.ZipFile(path) as archive:
                manifest = json.loads(archive.read("manifest.json"))
            results.append({**manifest, "path": str(path), "bytes": path.stat().st_size, "valid": True})
        except (OSError, ValueError, KeyError, zipfile.BadZipFile):
            results.append({"backupId": path.stem.removeprefix("backup-"), "path": str(path),
                            "bytes": path.stat().st_size, "valid": False})
    return results


def _apply_retention(backup_dir: Path, retention: int) -> None:
    keep = max(1, int(retention))
    paths = sorted(backup_dir.glob("backup-*.zip"), key=lambda item: item.stat().st_mtime, reverse=True)
    for path in paths[keep:]:
        path.unlink(missing_ok=True)


def backup_path(backup_dir, backup_id: str) -> Path:
    if not backup_id or any(char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for char in backup_id):
        raise BackupValidationError("无效的备份 ID")
    path = Path(backup_dir) / f"backup-{backup_id}.zip"
    if not path.is_file():
        raise BackupValidationError("备份不存在")
    return path


def delete_backup(backup_dir, backup_id: str) -> None:
    backups = list_backups(backup_dir)
    if len(backups) <= 1:
        raise BackupValidationError("至少保留一份完整备份")
    backup_path(backup_dir, backup_id).unlink()


def _extract_verified(archive_path: Path, destination: Path) -> None:
    with zipfile.ZipFile(archive_path) as archive:
        for info in archive.infolist():
            _safe_member(info)
            if info.filename == "manifest.json" or info.is_dir():
                continue
            target = destination.joinpath(*PurePosixPath(info.filename).parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info) as source, target.open("wb") as output:
                shutil.copyfileobj(source, output)


def restore_drill(archive_path):
    archive_path = Path(archive_path)
    manifest = verify_backup(archive_path)
    with tempfile.TemporaryDirectory(prefix="backup-drill-") as work:
        root = Path(work)
        _extract_verified(archive_path, root)
        database_path = root / "database" / "baby.db"
        if not database_path.is_file():
            raise BackupValidationError("备份缺少可恢复的 SQLite 数据库")
        connection = sqlite3.connect(f"file:{database_path}?mode=ro", uri=True)
        try:
            quick_check = connection.execute("PRAGMA quick_check").fetchone()[0]
        finally:
            connection.close()
        if quick_check != "ok":
            raise BackupValidationError(f"SQLite 恢复演练失败：{quick_check}")
        upload_files = sum(1 for path in (root / "uploads").rglob("*") if path.is_file())
    return {
        "backupId": manifest.get("backupId"),
        "quickCheck": quick_check,
        "uploadFiles": upload_files,
    }


@_serialized
def restore_backup(
    archive_path,
    database_path,
    upload_dir,
    backup_dir,
    retention: int = 2,
    create_rescue: bool = True,
):
    archive_path = Path(archive_path)
    database_path = Path(database_path)
    upload_dir = Path(upload_dir)
    backup_dir = Path(backup_dir)
    manifest = verify_backup(archive_path)
    data_dir = database_path.parent
    data_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix=".restore-", dir=data_dir) as work:
        restore_root = Path(work)
        _extract_verified(archive_path, restore_root)
        restored_database = restore_root / "database" / "baby.db"
        restored_uploads = restore_root / "uploads"
        restored_uploads.mkdir(parents=True, exist_ok=True)
        if create_rescue and database_path.exists():
            create_backup("pre-restore", database_path, upload_dir, backup_dir, retention)

        old_database = data_dir / f".{database_path.name}.restore-old"
        old_uploads = data_dir / f".{upload_dir.name}.restore-old"
        old_database.unlink(missing_ok=True)
        if old_uploads.exists():
            shutil.rmtree(old_uploads)
        database_replaced = False
        uploads_replaced = False
        try:
            if database_path.exists():
                os.replace(database_path, old_database)
            os.replace(restored_database, database_path)
            database_replaced = True
            if upload_dir.exists():
                os.replace(upload_dir, old_uploads)
            os.replace(restored_uploads, upload_dir)
            uploads_replaced = True
        except Exception:
            if uploads_replaced and upload_dir.exists():
                shutil.rmtree(upload_dir)
            if old_uploads.exists():
                os.replace(old_uploads, upload_dir)
            if database_replaced and database_path.exists():
                database_path.unlink()
            if old_database.exists():
                os.replace(old_database, database_path)
            raise
        finally:
            old_database.unlink(missing_ok=True)
            if old_uploads.exists():
                shutil.rmtree(old_uploads)
    return manifest
