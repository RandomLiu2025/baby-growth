import os
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

import jwt
from jwt import InvalidTokenError
from sqlalchemy.orm import selectinload

from . import media, models
from .config import settings


_CLEANUP_LOCK = threading.RLock()
_TOKEN_PURPOSE = "media-cleanup"
_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".avif", ".heic"}


class MediaCleanupError(Exception):
    pass


def _add_url_name(target: set[str], url) -> None:
    name = media.local_upload_name(url)
    if name:
        target.add(name)


def _thumbnail_name(name: str) -> str | None:
    stem, ext = os.path.splitext(name)
    if ext.lower() not in _IMAGE_EXTENSIONS or stem.endswith("_thumb"):
        return None
    return f"{stem}_thumb{ext}"


def referenced_media_names(db) -> tuple[set[str], set[str]]:
    required: set[str] = set()
    baby = db.get(models.Baby, 1)
    if baby:
        _add_url_name(required, baby.avatar)

    for milestone in db.query(models.Milestone).all():
        _add_url_name(required, milestone.image)
    for album in db.query(models.Album).options(selectinload(models.Album.photos)).all():
        _add_url_name(required, album.cover)
        for photo in album.photos:
            _add_url_name(required, photo.url)
    for diary in db.query(models.Diary).all():
        for url in diary.images or []:
            _add_url_name(required, url)
    for video in db.query(models.Video).all():
        _add_url_name(required, video.url)
        _add_url_name(required, video.cover)

    setting = db.get(models.Setting, 1)
    if setting and isinstance(setting.data, dict):
        _add_url_name(required, setting.data.get("faviconUrl"))

    protected = set(required)
    for name in required:
        thumbnail = _thumbnail_name(name)
        if thumbnail:
            protected.add(thumbnail)
    return required, protected


def scan_media(db, upload_dir, older_than_hours: int, now: datetime | None = None) -> dict:
    root = Path(upload_dir)
    root.mkdir(parents=True, exist_ok=True)
    required, protected = referenced_media_names(db)
    cutoff = (now or datetime.now(timezone.utc)) - timedelta(hours=older_than_hours)
    disk_names: set[str] = set()
    orphans = []
    temporary = []

    for path in root.iterdir():
        if not path.is_file() or path.is_symlink():
            continue
        disk_names.add(path.name)
        modified = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
        if path.name in protected or modified >= cutoff:
            continue
        item = {"name": path.name, "bytes": path.stat().st_size, "path": path}
        if path.name.endswith((".uploading", ".tmp")):
            temporary.append(item)
        else:
            orphans.append(item)

    return {
        "orphan": orphans,
        "temporary": temporary,
        "missing": sorted(required - disk_names),
    }


def public_summary(report: dict) -> dict:
    orphan = report["orphan"]
    temporary = report["temporary"]
    return {
        "orphanFiles": len(orphan),
        "orphanBytes": sum(item["bytes"] for item in orphan),
        "temporaryFiles": len(temporary),
        "temporaryBytes": sum(item["bytes"] for item in temporary),
        "missingReferences": len(report["missing"]),
        "orphanNames": [item["name"] for item in orphan[:100]],
        "temporaryNames": [item["name"] for item in temporary[:100]],
        "missingNames": report["missing"][:100],
    }


def create_cleanup_token(user_id: int, older_than_hours: int) -> str:
    expires = datetime.now(timezone.utc) + timedelta(minutes=10)
    return jwt.encode(
        {
            "sub": str(user_id),
            "purpose": _TOKEN_PURPOSE,
            "olderThanHours": older_than_hours,
            "exp": expires,
        },
        settings.SECRET_KEY,
        algorithm=settings.ALGORITHM,
    )


def verify_cleanup_token(token: str, user_id: int, older_than_hours: int) -> None:
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    except (InvalidTokenError, TypeError, ValueError) as exc:
        raise MediaCleanupError("清理确认已失效，请重新预览") from exc
    if (
        payload.get("purpose") != _TOKEN_PURPOSE
        or payload.get("sub") != str(user_id)
        or payload.get("olderThanHours") != older_than_hours
    ):
        raise MediaCleanupError("清理确认参数不匹配，请重新预览")


def delete_candidates(report: dict, upload_dir) -> dict:
    root = Path(upload_dir).resolve()
    deleted_files = 0
    released_bytes = 0
    with _CLEANUP_LOCK:
        for item in [*report["orphan"], *report["temporary"]]:
            path = item["path"]
            try:
                resolved = path.resolve(strict=True)
            except OSError:
                continue
            if resolved.parent != root or resolved.is_symlink() or not resolved.is_file():
                continue
            size = resolved.stat().st_size
            resolved.unlink()
            deleted_files += 1
            released_bytes += size
    return {"deletedFiles": deleted_files, "releasedBytes": released_bytes}
