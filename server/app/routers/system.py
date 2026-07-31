import logging
import os

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from .. import models
from ..config import settings
from ..db import get_db
from ..defaults import DEFAULT_BABY, DEFAULT_SETTINGS


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["system"])


@router.get("/health")
def health():
    return {"ok": True, "name": "宝贝成长记 API"}


def _writable_directory(path) -> bool:
    return os.path.isdir(path) and os.access(path, os.R_OK | os.W_OK)


@router.get("/ready")
def ready(db: Session = Depends(get_db)):
    try:
        db.execute(text("SELECT 1"))
        if not _writable_directory(settings.UPLOAD_DIR):
            raise RuntimeError("上传目录不可读写")
        if not _writable_directory(settings.BACKUP_DIR):
            raise RuntimeError("备份目录不可读写")
    except Exception as exc:
        logger.warning("应用就绪检查失败：%s", exc)
        raise HTTPException(503, "服务尚未就绪")
    return {"ok": True, "database": "ok", "uploads": "ok", "backups": "ok"}


@router.get("/branding")
def branding(db: Session = Depends(get_db)):
    setting = db.get(models.Setting, 1)
    baby = db.get(models.Baby, 1)
    data = setting.data if setting else DEFAULT_SETTINGS
    return {
        "faviconUrl": (data or {}).get("faviconUrl", ""),
        "babyName": (baby.name if baby else DEFAULT_BABY.get("name", "")) or "",
    }
