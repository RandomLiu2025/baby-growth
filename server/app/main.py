import os
import re
import copy
import uuid
import shutil
import subprocess
import mimetypes
import secrets
import random
import logging
from contextlib import asynccontextmanager
from datetime import date, datetime, timezone, timedelta

from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, Form, Body, Query, Request, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload
from sqlalchemy.orm.attributes import flag_modified

from .body_limit import RequestBodyLimitMiddleware
from .config import settings, INSECURE_SIGNING_SENTINEL, DEFAULT_ADMIN_PASSWORD
from .db import Base, engine, get_db, SessionLocal
from . import backup, clock, imports, migrations, models, auth, ai, media, media_storage, outbound, schemas, secret_store, uploads
from .defaults import DEFAULT_SETTINGS, DEFAULT_BABY
from .routers import auth as auth_routes
from .routers import system as system_routes


logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    clock.validate_timezone()
    validate_production_security()
    _warn_insecure_defaults()
    _ensure_dirs()
    uploads.cleanup_stale_chunks(settings.UPLOAD_DIR)
    uploads.cleanup_stale_temporary_files(settings.UPLOAD_DIR)
    if settings.APP_ENV.lower() == "test":
        Base.metadata.create_all(engine)
    else:
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
        validate_admin_security(db)
    finally:
        db.close()
    yield


app = FastAPI(title="宝贝成长记 API", version="1.0.0", lifespan=lifespan)
app.include_router(auth_routes.router)
app.include_router(system_routes.router)
_cors_origins = settings.cors_list
if _cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins,
        allow_credentials="*" not in _cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    response.headers.setdefault("Permissions-Policy", "camera=(), geolocation=()")
    response.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; script-src 'self' 'unsafe-eval'; "
        "style-src 'self' 'unsafe-inline'; img-src 'self' data: blob: https:; "
        "media-src 'self' blob: https:; connect-src 'self'; font-src 'self' data:; "
        "object-src 'none'; base-uri 'self'; frame-ancestors 'none'",
    )
    return response


app.add_middleware(
    RequestBodyLimitMiddleware,
    paths={"/api/import", "/api/import/validate"},
    max_bytes=settings.MAX_IMPORT_MB * 1024 * 1024,
)
# 直连部署（未经 Caddy/nginx）时压缩 JSON 与静态资源；有反向代理时其 encode 会跳过已压缩响应
app.add_middleware(GZipMiddleware, minimum_size=2048)
app.add_middleware(
    RequestBodyLimitMiddleware,
    paths={"/api/upload"},
    max_bytes=(max(settings.MAX_VIDEO_MB, settings.MAX_IMAGE_MB * settings.MAX_UPLOAD_FILES) + 8) * 1024 * 1024,
    detail="上传请求超过大小限制",
)
app.add_middleware(
    RequestBodyLimitMiddleware,
    paths={"/api/upload/chunk"},
    max_bytes=uploads.MAX_CHUNK_BYTES + 2 * 1024 * 1024,
    detail="上传分片超过大小限制",
)

# 通用资源（简单 CRUD）
RES = {
    "milestones": models.Milestone,
    "growth": models.Growth,
    "daily": models.Daily,
    "diary": models.Diary,
    "videos": models.Video,
    "vaccines": models.Vaccine,
}

COMPACT_DAILY_LIMIT = 200


# ---------------- 初始化 ----------------
def validate_production_security():
    if settings.APP_ENV.lower() != "production":
        return
    if settings.SECRET_KEY == INSECURE_SIGNING_SENTINEL or len(settings.SECRET_KEY) < 32:
        raise RuntimeError("生产环境 SECRET_KEY 必须使用至少 32 字符的随机值")
    if settings.ADMIN_PASSWORD == DEFAULT_ADMIN_PASSWORD or len(settings.ADMIN_PASSWORD) < settings.MIN_PASSWORD_LENGTH:
        raise RuntimeError("生产环境 ADMIN_PASSWORD 不能使用默认值且必须满足最小长度")
    if settings.DATA_ENCRYPTION_KEY and len(settings.DATA_ENCRYPTION_KEY) < 32:
        raise RuntimeError("生产环境 DATA_ENCRYPTION_KEY 必须至少 32 字符")


def validate_admin_security(db: Session):
    if settings.APP_ENV.lower() != "production":
        return
    admin = db.query(models.User).filter_by(username=settings.ADMIN_USERNAME).first()
    if admin and auth.verify_pw(DEFAULT_ADMIN_PASSWORD, admin.password_hash):
        raise RuntimeError("生产环境管理员仍在使用默认密码 admin123，请先修改数据库中的管理员密码")


def _warn_insecure_defaults():
    """启动时检查是否仍在使用默认密钥/密码，打印醒目警告（不阻断启动，方便首次体验）。"""
    warns = []
    if settings.SECRET_KEY == INSECURE_SIGNING_SENTINEL:
        warns.append("SECRET_KEY 仍为默认值——任何人都可伪造登录 token！请在 .env 中改为长随机字符串。")
    if settings.ADMIN_PASSWORD == DEFAULT_ADMIN_PASSWORD:
        warns.append("ADMIN_PASSWORD 仍为默认值 admin123，请尽快在 .env 中修改。")
    for w in warns:
        logger.warning("[安全警告] %s", w)


def _ensure_dirs():
    if settings.DATABASE_URL.startswith("sqlite"):
        p = settings.DATABASE_URL.split("sqlite:///")[-1]
        d = os.path.dirname(p)
        if d:
            os.makedirs(d, exist_ok=True)
    os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
    os.makedirs(settings.BACKUP_DIR, exist_ok=True)


def ensure_init(db: Session):
    admin = db.query(models.User).filter_by(username=settings.ADMIN_USERNAME).first()
    if not admin:
        db.add(models.User(username=settings.ADMIN_USERNAME,
                           password_hash=auth.hash_pw(settings.ADMIN_PASSWORD), role="admin"))
    elif admin.role != "admin":
        admin.role = "admin"
    if not db.get(models.Baby, 1):
        db.add(models.Baby(id=1, **DEFAULT_BABY))
    setting = db.get(models.Setting, 1)
    if not setting:
        db.add(models.Setting(id=1, data=copy.deepcopy(DEFAULT_SETTINGS)))
    else:
        protected_settings = secret_store.protect_settings_data(setting.data)
        if protected_settings != (setting.data or {}):
            setting.data = protected_settings
            flag_modified(setting, "data")
    db.commit()


def sanitize(data, is_admin):
    d = copy.deepcopy(data or {})
    if isinstance(d.get("ai"), dict):
        configured = bool(d["ai"].get("apiKey"))
        d["ai"] = {
            **d["ai"],
            "apiKey": "",
            "apiKeyConfigured": configured,
            "clearApiKey": False,
        }
    return d


# ---------------- 汇总 ----------------
def _album_summary(album, photo_count):
    item = {k: getattr(album, k) for k in ["id", *models.Album.FIELDS, "createdAt"]}
    item.update({"photos": [], "photoCount": int(photo_count or 0), "photosLoaded": False})
    return item


def _album_summaries(db: Session):
    rows = (
        db.query(models.Album, func.count(models.Photo.id))
        .outerjoin(models.Photo, models.Photo.albumId == models.Album.id)
        .group_by(models.Album.id)
        .all()
    )
    return [_album_summary(album, photo_count) for album, photo_count in rows]


def _on_this_day_photos(db: Session, today: date | None = None):
    month_day = (today or clock.local_today()).strftime("%m-%d")
    rows = (
        db.query(
            models.Photo.takenAt,
            models.Photo.caption,
            models.Photo.url,
            models.Album.name,
        )
        .join(models.Album, models.Album.id == models.Photo.albumId)
        .filter(models.Photo.takenAt.like(f"%-{month_day}"))
        .order_by(models.Photo.takenAt.desc(), models.Photo.sort.asc())
        .limit(24)
        .all()
    )
    return [
        {"date": taken_at, "title": caption or album_name, "image": url}
        for taken_at, caption, url, album_name in rows
    ]


def _compact_daily(db: Session):
    total_query = (
        select(func.count(models.Daily.id))
        .select_from(models.Daily)
        .correlate(None)
        .scalar_subquery()
    )
    rows = (
        db.query(models.Daily, total_query.label("total"))
        .order_by(models.Daily.time.desc(), models.Daily.id.desc())
        .limit(COMPACT_DAILY_LIMIT)
        .all()
    )
    items = [item.as_dict() for item, _ in rows]
    total = int(rows[0][1]) if rows else 0
    return items, total


def _diary_summaries(db: Session):
    rows = (
        db.query(
            models.Diary.id,
            models.Diary.date,
            models.Diary.title,
            func.substr(models.Diary.content, 1, 120),
            func.json_extract(models.Diary.images, "$[0]"),
            func.coalesce(func.json_array_length(models.Diary.images), 0),
        )
        .order_by(models.Diary.date.desc(), models.Diary.id.desc())
        .all()
    )
    result = []
    for diary_id, date, title, content, first_image, image_count in rows:
        media = [] if first_image is None else [first_image]
        result.append({
            "id": diary_id,
            "date": date,
            "title": title,
            "content": content or "",
            "images": media,
            "imageCount": int(image_count or 0),
            "detailLoaded": False,
        })
    return result


@app.get("/api/bootstrap")
def bootstrap(compact: bool = Query(False), db: Session = Depends(get_db), user=Depends(auth.require_user)):
    is_admin = user.role == "admin"
    current_time = clock.utc_now()
    business_today = clock.local_today(current_time)
    baby = db.get(models.Baby, 1)
    setting = db.get(models.Setting, 1)
    mq = db.query(models.Message)
    if not is_admin:
        mq = mq.filter_by(status="approved")
    compact_daily, daily_total = _compact_daily(db) if compact else (None, None)
    result = {
        "baby": baby.as_dict() if baby else DEFAULT_BABY,
        "settings": sanitize(setting.data if setting else DEFAULT_SETTINGS, is_admin),
        "milestones": [x.as_dict() for x in db.query(models.Milestone).all()],
        "albums": _album_summaries(db) if compact else [x.as_dict() for x in db.query(models.Album).options(selectinload(models.Album.photos)).all()],
        "growth": [x.as_dict() for x in db.query(models.Growth).all()],
        "daily": compact_daily if compact else [x.as_dict() for x in db.query(models.Daily).all()],
        "diary": _diary_summaries(db) if compact else [x.as_dict() for x in db.query(models.Diary).all()],
        "videos": [x.as_dict() for x in db.query(models.Video).all()],
        "messages": [x.as_dict() for x in mq.all()],
        "recaps": [r.as_dict() for r in db.query(models.Recap).order_by(models.Recap.id.desc()).all()],
        "vaccines": [v.as_dict() for v in db.query(models.Vaccine).all()],
        "limits": {"imageMB": settings.MAX_IMAGE_MB, "videoMB": settings.MAX_VIDEO_MB},
        "businessTime": clock.business_time_context(current_time),
        "isAdmin": is_admin,
        "user": {"username": user.username, "role": user.role},
    }
    if compact:
        result["albumsCompact"] = True
        result["onThisDayPhotos"] = _on_this_day_photos(db, business_today)
        result["dailyCompact"] = True
        result["dailyTotal"] = daily_total
        result["diaryCompact"] = True
    return result


# ---------------- 上传 ----------------
IMAGE_EXT = uploads.IMAGE_EXT
VIDEO_EXT = uploads.VIDEO_EXT


def classify_upload(filename, content_type):
    """按扩展名 + MIME 判断类型，返回 (kind, ext, 大小上限MB)。不支持则 kind 为 None。"""
    return uploads.classify_upload(filename, content_type)


def _publish_validated_upload(temp_path: str, final_path: str, kind: str, defer_video_processing: bool = False):
    try:
        uploads.validate_file_content(temp_path, kind)
        uploads.validate_media_constraints(temp_path, kind)
        if kind != "video" or not defer_video_processing:
            uploads.sanitize_media_metadata(temp_path, kind)
        uploads.validate_file_content(temp_path, kind)
        os.replace(temp_path, final_path)
    except uploads.UploadValidationError as exc:
        try:
            os.remove(temp_path)
        except OSError:
            pass
        raise HTTPException(exc.status_code, exc.detail)


def generate_poster(video_path):
    """用 ffmpeg 抽取一帧作为视频封面。无 ffmpeg 或失败时返回 None。"""
    if not shutil.which("ffmpeg"):
        return None
    poster_path = f"{os.path.splitext(video_path)[0]}_poster.jpg"
    poster_name = os.path.basename(poster_path)
    if os.path.isfile(poster_path) and os.path.getsize(poster_path) > 0:
        return f"/uploads/{poster_name}"
    last_error = ""
    for seek in ("00:00:01", "0"):
        try:
            result = subprocess.run(
                ["ffmpeg", "-y", "-ss", seek, "-i", video_path, "-frames:v", "1",
                 "-vf", "scale='min(800,iw)':-2", poster_path],
                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=15, check=True,
            )
            if os.path.isfile(poster_path) and os.path.getsize(poster_path) > 0:
                return f"/uploads/{poster_name}"
            last_error = (result.stderr or b"")[-500:].decode("utf-8", errors="replace")
        except Exception as exc:
            last_error = str(exc)
            continue
    if os.path.isfile(poster_path):
        try:
            os.remove(poster_path)
        except OSError:
            pass
    logger.warning("视频封面生成失败：%s (%s)", os.path.basename(video_path), last_error or "unknown")
    return None


THUMB_EXT = {".jpg", ".jpeg", ".png", ".webp"}


def generate_thumb(image_path):
    """为图片生成小缩略图（宽 ≤480），文件名加 _thumb 后缀。无 ffmpeg 或不支持的格式返回 None（前端回退原图）。"""
    if not shutil.which("ffmpeg"):
        return None
    stem, ext = os.path.splitext(image_path)
    if ext.lower() not in THUMB_EXT:
        return None
    thumb_path = f"{stem}_thumb{ext}"
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-i", image_path, "-vf", "scale='min(480,iw)':-1", thumb_path],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15, check=True,
        )
        if os.path.isfile(thumb_path) and os.path.getsize(thumb_path) > 0:
            return f"/uploads/{os.path.basename(thumb_path)}"
    except Exception as exc:
        logger.warning("缩略图生成失败：%s (%s)", os.path.basename(image_path), exc)
    if os.path.isfile(thumb_path) and os.path.getsize(thumb_path) == 0:
        try:
            os.remove(thumb_path)
        except OSError:
            pass
    return None


def _bg_poster_and_thumb(video_path: str):
    """后台生成视频封面 + 封面缩略图。"""
    try:
        poster = generate_poster(video_path)
        if poster:
            generate_thumb(os.path.join(settings.UPLOAD_DIR, os.path.basename(poster)))
    except Exception:
        logger.exception("后台视频封面任务失败：%s", os.path.basename(video_path))


def _bg_thumb(image_path: str):
    """后台生成图片缩略图。"""
    try:
        generate_thumb(image_path)
    except Exception:
        logger.exception("后台缩略图任务失败：%s", os.path.basename(image_path))


def _video_processing_due(result: dict | None) -> bool:
    item = ((result or {}).get("items") or [{}])[0]
    state = item.get("processingState")
    if state == "pending":
        return True
    if state != "processing":
        return False
    try:
        started = datetime.fromisoformat(item.get("processingStartedAt") or "")
        if started.tzinfo is None:
            started = started.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return True
    return datetime.now(timezone.utc) - started > timedelta(seconds=settings.MEDIA_PROCESS_TIMEOUT_SECONDS)


def _schedule_video_processing(background_tasks: BackgroundTasks, manifest: dict) -> None:
    result = manifest.get("result")
    if not _video_processing_due(result):
        return
    background_tasks.add_task(
        _process_completed_video,
        manifest["uploadId"],
        manifest["userId"],
        manifest["filename"],
        manifest["fileSize"],
        manifest["total"],
    )


def _processing_manifest(upload_id: str, user_id: int, filename: str, file_size: int, total: int) -> dict:
    return uploads.require_manifest(
        settings.UPLOAD_DIR,
        upload_id,
        user_id,
        filename,
        file_size,
        total,
    )


def _process_completed_video(upload_id: str, user_id: int, filename: str, file_size: int, total: int) -> None:
    with uploads.upload_lock(upload_id):
        manifest = _processing_manifest(upload_id, user_id, filename, file_size, total)
        result = copy.deepcopy(manifest.get("result") or {})
        item = ((result.get("items") or [{}]))[0]
        state = item.get("processingState")
        if state in {"ready", "failed"}:
            return
        if state == "processing" and not _video_processing_due(result):
            return
        item["processingState"] = "processing"
        item["processingStartedAt"] = datetime.now(timezone.utc).isoformat()
        item["processingWarning"] = ""
        uploads.mark_completed(settings.UPLOAD_DIR, manifest, result)
        source_name = media.local_upload_name(item.get("url"))
        if not source_name:
            item["processingState"] = "failed"
            item["processingWarning"] = "视频地址无效，无法执行兼容处理"
            uploads.mark_completed(settings.UPLOAD_DIR, manifest, result)
            return
        source_path = os.path.join(settings.UPLOAD_DIR, source_name)

    processed_path = source_path
    try:
        with uploads.media_job_slot():
            processed_path, action, warning = uploads.normalize_video_for_browser(source_path)
            poster = generate_poster(processed_path)
            if poster:
                generate_thumb(os.path.join(settings.UPLOAD_DIR, os.path.basename(poster)))
        warnings = [value for value in [warning, None if poster else "视频封面生成失败，已保留视频文件"] if value]
        processed_url = f"/uploads/{os.path.basename(processed_path)}"
        with uploads.upload_lock(upload_id):
            manifest = _processing_manifest(upload_id, user_id, filename, file_size, total)
            result = copy.deepcopy(manifest.get("result") or {})
            item = (result.get("items") or [{}])[0]
            item.update({
                "url": processed_url,
                "poster": poster,
                "thumb": poster or processed_url,
                "processingState": "ready",
                "processingAction": action,
                "processingWarning": "；".join(warnings),
                "processedAt": datetime.now(timezone.utc).isoformat(),
            })
            result["url"] = processed_url
            result["urls"] = [processed_url]
            uploads.mark_completed(settings.UPLOAD_DIR, manifest, result)
    except Exception as exc:
        logger.exception("视频后台处理失败：%s", os.path.basename(source_path))
        warning = exc.detail if isinstance(exc, uploads.UploadValidationError) else "视频处理失败，已保留原文件"
        with uploads.upload_lock(upload_id):
            manifest = _processing_manifest(upload_id, user_id, filename, file_size, total)
            result = copy.deepcopy(manifest.get("result") or {})
            item = (result.get("items") or [{}])[0]
            item.update({
                "processingState": "failed",
                "processingWarning": warning,
                "processedAt": datetime.now(timezone.utc).isoformat(),
            })
            uploads.mark_completed(settings.UPLOAD_DIR, manifest, result)


def _save_uploaded_files(background_tasks: BackgroundTasks, files: list[UploadFile]):
    if len(files) > settings.MAX_UPLOAD_FILES:
        raise HTTPException(400, f"单次最多上传 {settings.MAX_UPLOAD_FILES} 个文件")
    specs = []
    for file in files:
        kind, ext, limit_mb = classify_upload(file.filename, file.content_type)
        if not kind:
            raise HTTPException(400, f"不支持的文件类型：{file.filename or '未命名'}（仅支持图片和视频）")
        specs.append((file, kind, ext, limit_mb))

    urls, items, published, temporary = [], [], [], []
    try:
        for file, kind, ext, limit_mb in specs:
            limit = limit_mb * 1024 * 1024
            name = f"{uuid.uuid4().hex}{ext}"
            dest = os.path.join(settings.UPLOAD_DIR, name)
            temp_dest = f"{dest}.uploading"
            temporary.append(temp_dest)
            size, exceeded = 0, False
            with open(temp_dest, "wb") as out:
                while True:
                    chunk = file.file.read(1024 * 1024)
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > limit:
                        exceeded = True
                        break
                    out.write(chunk)
            if exceeded:
                zh = "图片" if kind == "image" else "视频"
                raise HTTPException(413, f"文件过大：{file.filename or '未命名'}（{zh}上限 {limit_mb}MB）")
            if kind == "image" and ext == ".heic":
                converted_dest = f"{os.path.splitext(dest)[0]}.jpg"
                converted_temp = f"{os.path.splitext(dest)[0]}.uploading.jpg"
                temporary.append(converted_temp)
                uploads.convert_heic_to_jpeg(temp_dest, converted_temp)
                os.remove(temp_dest)
                temporary.remove(temp_dest)
                dest = converted_dest
                temp_dest = converted_temp
                name = os.path.basename(dest)
            _publish_validated_upload(temp_dest, dest, kind)
            temporary.remove(temp_dest)
            published.append(dest)
            url = f"/uploads/{name}"
            if kind == "image":
                background_tasks.add_task(_bg_thumb, dest)
            urls.append(url)
            items.append({"url": url, "kind": kind, "poster": None, "thumb": url})
    except Exception:
        for path in [*temporary, *published]:
            try:
                os.remove(path)
            except OSError:
                pass
        raise
    return {"urls": urls, "url": urls[0] if urls else None, "items": items}


@app.post("/api/upload")
def upload(background_tasks: BackgroundTasks,
           files: list[UploadFile] = File(...),
           user=Depends(auth.require_admin)):
    try:
        required = sum(
            max(0, int(file.size or 0))
            * (
                2
                if classify_upload(file.filename, file.content_type)[0] == "video"
                or classify_upload(file.filename, file.content_type)[1] == ".heic"
                else 1
            )
            for file in files
        )
        uploads.ensure_storage_capacity(settings.UPLOAD_DIR, required)
        with uploads.upload_slot():
            return _save_uploaded_files(background_tasks, files)
    except uploads.UploadValidationError as exc:
        raise HTTPException(exc.status_code, exc.detail)


# ---------------- 分片上传（用于大视频，避开 Cloudflare 100s 单请求上限） ----------------
CHUNKS_DIRNAME = ".chunks"
_UPLOAD_ID_RE = re.compile(r"^[a-f0-9]{32}$")


def _chunks_dir():
    return uploads.chunks_dir(settings.UPLOAD_DIR)


@app.post("/api/upload/chunk")
def upload_chunk(
    file: UploadFile = File(...),
    uploadId: str = Form(...),
    index: int = Form(...),
    total: int = Form(...),
    filename: str = Form(...),
    fileSize: int = Form(...),
    user=Depends(auth.require_admin),
):
    if not _UPLOAD_ID_RE.match(uploadId):
        raise HTTPException(400, "无效的 uploadId")
    if index < 0 or index >= total:
        raise HTTPException(400, "无效的分片编号")
    uploads.cleanup_stale_chunks_throttled(settings.UPLOAD_DIR)
    try:
        with uploads.upload_slot():
            manifest = uploads.bind_manifest(settings.UPLOAD_DIR, uploadId, user.id, filename, fileSize, total)
            if (manifest.get("state") or "uploading") == "completed":
                return {"ok": True, "completed": True, "result": manifest.get("result")}

            d = _chunks_dir()
            dest = uploads.part_path(d, uploadId, index)
            temp_dest = f"{dest}.{uuid.uuid4().hex}.tmp"
            size = 0
            limit = uploads.MAX_CHUNK_BYTES
            try:
                with open(temp_dest, "wb") as out:
                    while True:
                        buf = file.file.read(1024 * 1024)
                        if not buf:
                            break
                        size += len(buf)
                        if size > limit:
                            raise HTTPException(413, "单个分片超过 10MB")
                        out.write(buf)
                expected_size = uploads.expected_part_size(fileSize, index)
                if size != expected_size:
                    raise HTTPException(400, "分片大小与上传声明不一致")
                manifest = uploads.publish_part(
                    settings.UPLOAD_DIR,
                    uploadId,
                    user.id,
                    filename,
                    fileSize,
                    total,
                    index,
                    temp_dest,
                )
            finally:
                try:
                    os.remove(temp_dest)
                except OSError:
                    pass
    except uploads.UploadValidationError as exc:
        raise HTTPException(exc.status_code, exc.detail)
    return {"ok": True, "received": index + 1, "total": total}


@app.get("/api/upload/status/{upload_id}")
def get_upload_status(
    background_tasks: BackgroundTasks,
    upload_id: str,
    filename: str = Query(..., min_length=1, max_length=500),
    fileSize: int = Query(..., ge=1),
    total: int = Query(..., ge=1, le=10000),
    user=Depends(auth.require_admin),
):
    if not _UPLOAD_ID_RE.match(upload_id):
        raise HTTPException(400, "无效的 uploadId")
    try:
        status = uploads.upload_status(
            settings.UPLOAD_DIR,
            upload_id,
            user.id,
            filename,
            fileSize,
            total,
        )
        manifest = _processing_manifest(upload_id, user.id, filename, fileSize, total)
        _schedule_video_processing(background_tasks, manifest)
        return status
    except uploads.UploadValidationError as exc:
        status_code = 404 if "不存在或已过期" in exc.detail else exc.status_code
        raise HTTPException(status_code, exc.detail)


@app.delete("/api/upload/{upload_id}", status_code=204)
def cancel_chunk_upload(upload_id: str, user=Depends(auth.require_admin)):
    if not _UPLOAD_ID_RE.match(upload_id):
        raise HTTPException(400, "无效的 uploadId")
    try:
        if not uploads.cancel_upload(settings.UPLOAD_DIR, upload_id, user.id):
            raise HTTPException(404, "上传任务不存在或已过期")
    except uploads.UploadValidationError as exc:
        raise HTTPException(exc.status_code, exc.detail)


@app.post("/api/upload/complete")
def upload_complete(
    background_tasks: BackgroundTasks,
    payload: schemas.UploadCompleteRequest,
    user=Depends(auth.require_admin),
):
    uploadId = payload.uploadId
    total = payload.total
    filename = payload.filename
    file_size = payload.fileSize
    try:
        with uploads.upload_slot(), uploads.upload_lock(uploadId):
            manifest = uploads.require_manifest(
                settings.UPLOAD_DIR,
                uploadId,
                user.id,
                filename,
                file_size,
                total,
            )
            if (manifest.get("state") or "uploading") == "completed":
                result = manifest.get("result")
                if not isinstance(result, dict):
                    raise HTTPException(409, "上传完成状态损坏，请重新上传")
                _schedule_video_processing(background_tasks, manifest)
                return result

            d = _chunks_dir()
            chunks = []
            for index in range(total):
                path = uploads.part_path(d, uploadId, index)
                expected = uploads.expected_part_size(file_size, index)
                if not os.path.isfile(path) or os.path.getsize(path) != expected:
                    raise HTTPException(409, f"缺少分片 {index + 1}/{total}，请继续上传")
                chunks.append(path)

            kind, ext, limit_mb = classify_upload(filename, "")
            if not kind:
                raise HTTPException(400, f"不支持的文件类型：{filename or '未命名'}（仅支持图片和视频）")
            limit = limit_mb * 1024 * 1024
            workspace_multiplier = 2 if kind == "video" or ext == ".heic" else 1
            uploads.ensure_storage_capacity(settings.UPLOAD_DIR, file_size * workspace_multiplier)

            published_ext = ".jpg" if kind == "image" and ext == ".heic" else ext
            manifest = uploads.begin_completion(
                settings.UPLOAD_DIR,
                manifest,
                f"{uuid.uuid4().hex}{published_ext}",
            )
            name = manifest["targetName"]
            final_path = os.path.join(settings.UPLOAD_DIR, name)
            temp_path = f"{final_path}.uploading"
            try:
                needs_publish = not os.path.isfile(final_path) or (ext != ".heic" and os.path.getsize(final_path) != file_size)
                if needs_publish:
                    total_size, exceeded = 0, False
                    with open(temp_path, "wb") as out:
                        for chunk_path in chunks:
                            with open(chunk_path, "rb") as inp:
                                while True:
                                    buf = inp.read(1024 * 1024)
                                    if not buf:
                                        break
                                    total_size += len(buf)
                                    if total_size > limit:
                                        exceeded = True
                                        break
                                    out.write(buf)
                            if exceeded:
                                break
                    if exceeded or total_size != file_size:
                        zh = "图片" if kind == "image" else "视频"
                        if exceeded:
                            raise HTTPException(
                                413,
                                f"文件过大：{filename or '未命名'}（{zh}上限 {limit_mb}MB，当前 {total_size // 1024 // 1024}MB）",
                            )
                        raise HTTPException(400, "合并后的文件大小与上传声明不一致")
                    publish_temp = temp_path
                    if kind == "image" and ext == ".heic":
                        publish_temp = f"{final_path}.converted.jpg"
                        uploads.convert_heic_to_jpeg(temp_path, publish_temp)
                        os.remove(temp_path)
                    _publish_validated_upload(publish_temp, final_path, kind, defer_video_processing=kind == "video")
                else:
                    uploads.validate_file_content(final_path, kind)
                    uploads.validate_media_constraints(final_path, kind)

                url = f"/uploads/{name}"
                if kind == "video":
                    item = {
                        "url": url,
                        "kind": kind,
                        "poster": None,
                        "thumb": url,
                        "processingState": "pending",
                        "processingAction": "pending",
                        "processingWarning": "",
                    }
                else:
                    background_tasks.add_task(_bg_thumb, final_path)
                    item = {"url": url, "kind": kind, "poster": None, "thumb": url}
                result = {
                    "urls": [url],
                    "url": url,
                    "items": [item],
                }
                manifest = uploads.mark_completed(settings.UPLOAD_DIR, manifest, result)
                uploads.remove_upload_parts(settings.UPLOAD_DIR, uploadId, total, keep_manifest=True)
                if kind == "video":
                    _schedule_video_processing(background_tasks, manifest)
                return result
            except Exception:
                if not os.path.isfile(final_path):
                    uploads.reset_completion(settings.UPLOAD_DIR, manifest)
                try:
                    os.remove(temp_path)
                except OSError:
                    pass
                try:
                    os.remove(f"{final_path}.converted.jpg")
                except OSError:
                    pass
                raise
    except uploads.UploadValidationError as exc:
        raise HTTPException(exc.status_code, exc.detail)


# ---------------- 上传文件访问（支持 HTTP Range，用于视频拖动/流式播放） ----------------
@app.get("/uploads/{name}")
def serve_upload(
    name: str,
    request: Request,
    share: str | None = None,
    db: Session = Depends(get_db),
    user=Depends(auth.current_user_optional),
):
    safe_name = os.path.basename(name)  # 防目录穿越
    access = media.authorize_media(db, user, share, safe_name)
    path = os.path.join(settings.UPLOAD_DIR, safe_name)
    fallback = False
    if not os.path.isfile(path):
        # _thumb 未就绪时（后台任务尚未生成），fallback 到原图 —— 保证前端图片一定能显示
        if "_thumb" in safe_name:
            orig = safe_name.replace("_thumb", "", 1)
            orig_path = os.path.join(settings.UPLOAD_DIR, orig)
            if os.path.isfile(orig_path):
                path = orig_path
                fallback = True
            else:
                raise HTTPException(404, "文件不存在")
        else:
            raise HTTPException(404, "文件不存在")
    size = os.path.getsize(path)
    ctype = mimetypes.guess_type(path)[0] or "application/octet-stream"
    # fallback 时用较短缓存，让浏览器很快能取到真正生成好的 _thumb
    if access == "shared":
        cache = "private, max-age=60" if fallback else "private, max-age=300"
    else:
        cache = "private, max-age=60" if fallback else "private, max-age=86400"
    base_headers = {"Accept-Ranges": "bytes", "Cache-Control": cache}
    rng = request.headers.get("range")

    if rng and rng.startswith("bytes="):
        try:
            s, _, e = rng.split("=", 1)[1].split(",")[0].partition("-")
            start = int(s) if s else 0
            end = int(e) if e else size - 1
        except Exception:
            start, end = 0, size - 1
        start = max(0, start)
        end = min(end, size - 1)
        if start > end:
            start, end = 0, size - 1
        length = end - start + 1

        def ranged():
            with open(path, "rb") as f:
                f.seek(start)
                left = length
                while left > 0:
                    chunk = f.read(min(1048576, left))
                    if not chunk:
                        break
                    left -= len(chunk)
                    yield chunk

        headers = {**base_headers, "Content-Range": f"bytes {start}-{end}/{size}",
                   "Content-Length": str(length)}
        return StreamingResponse(ranged(), status_code=206, media_type=ctype, headers=headers)

    def whole():
        with open(path, "rb") as f:
            while True:
                chunk = f.read(1048576)
                if not chunk:
                    break
                yield chunk

    return StreamingResponse(whole(), media_type=ctype,
                             headers={**base_headers, "Content-Length": str(size)})


# ---------------- AI ----------------
@app.post("/api/ai/chat")
def ai_chat(payload: schemas.AIChatRequest, db: Session = Depends(get_db),
            user=Depends(auth.require_user)):
    messages = [message.model_dump() for message in payload.messages]
    return ai.chat(messages, db, is_admin=user.role == "admin")


# ---------------- 宝贝信息 ----------------
@app.get("/api/baby")
def get_baby(db: Session = Depends(get_db), user=Depends(auth.require_user)):
    b = db.get(models.Baby, 1)
    return b.as_dict() if b else DEFAULT_BABY


@app.put("/api/baby")
def put_baby(payload: schemas.BabyRequest, db: Session = Depends(get_db), user=Depends(auth.require_admin)):
    values = payload.model_dump()
    b = db.get(models.Baby, 1) or models.Baby(id=1)
    for k in models.Baby.FIELDS:
        if k in values:
            setattr(b, k, values[k])
    db.add(b); db.commit(); db.refresh(b)
    return b.as_dict()


# ---------------- 显示设置 ----------------
@app.get("/api/settings")
def get_settings(db: Session = Depends(get_db), user=Depends(auth.require_user)):
    s = db.get(models.Setting, 1)
    return sanitize(s.data if s else DEFAULT_SETTINGS, user.role == "admin")


@app.put("/api/settings")
def put_settings(payload: schemas.SettingsRequest, db: Session = Depends(get_db), user=Depends(auth.require_admin)):
    s = db.get(models.Setting, 1) or models.Setting(id=1, data={})
    existing = copy.deepcopy(s.data or {})
    data = payload.model_dump()
    incoming_ai = data.get("ai") or {}
    existing_ai = existing.get("ai") or {}
    clear_key = bool(incoming_ai.pop("clearApiKey", False))
    incoming_ai.pop("apiKeyConfigured", None)
    new_key = str(incoming_ai.get("apiKey") or "").strip()
    if clear_key:
        incoming_ai["apiKey"] = ""
        incoming_ai["enabled"] = False
    elif new_key:
        incoming_ai["apiKey"] = secret_store.encrypt_secret(new_key)
    else:
        incoming_ai["apiKey"] = secret_store.protect_secret(existing_ai.get("apiKey") or "")
    try:
        incoming_ai["baseUrl"] = outbound.validate_ai_base_url(
            incoming_ai.get("baseUrl") or "https://api.openai.com/v1",
            settings.AI_ALLOW_PRIVATE_BASE_URLS,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    data["ai"] = incoming_ai
    s.data = data
    db.add(s)
    flag_modified(s, "data")
    db.commit()
    return sanitize(s.data, True)


# ---------------- 相册（含照片） ----------------
def _sync_photos(album, photos):
    album.photos.clear()
    for i, p in enumerate(photos or []):
        album.photos.append(models.Photo(
            url=p.get("url", ""), caption=p.get("caption", ""), desc=p.get("desc", ""),
            takenAt=p.get("takenAt", ""), sort=i))


@app.get("/api/albums")
def list_albums(db: Session = Depends(get_db), user=Depends(auth.require_user)):
    return [a.as_dict() for a in db.query(models.Album).options(selectinload(models.Album.photos)).all()]


@app.get("/api/albums/{album_id}")
def get_album(album_id: int, db: Session = Depends(get_db), user=Depends(auth.require_user)):
    album = (
        db.query(models.Album)
        .options(selectinload(models.Album.photos))
        .filter(models.Album.id == album_id)
        .first()
    )
    if not album:
        raise HTTPException(404, "相册不存在")
    return album.as_dict()


@app.post("/api/albums")
def create_album(payload: schemas.AlbumRequest, db: Session = Depends(get_db), user=Depends(auth.require_admin)):
    values = payload.model_dump()
    a = models.Album(**{k: values.get(k, "") for k in models.Album.FIELDS})
    _sync_photos(a, values.get("photos"))
    if not a.cover and a.photos:
        a.cover = a.photos[0].url
    db.add(a); db.commit(); db.refresh(a)
    return a.as_dict()


@app.put("/api/albums/{album_id}")
def update_album(album_id: int, payload: schemas.AlbumRequest, db: Session = Depends(get_db), user=Depends(auth.require_admin)):
    values = payload.model_dump()
    a = db.get(models.Album, album_id)
    if not a:
        raise HTTPException(404, "相册不存在")
    for k in models.Album.FIELDS:
        if k in values:
            setattr(a, k, values[k])
    if "photos" in values:
        _sync_photos(a, values["photos"])
    if not a.cover and a.photos:
        a.cover = a.photos[0].url
    db.commit(); db.refresh(a)
    return a.as_dict()


@app.delete("/api/albums/{album_id}")
def delete_album(album_id: int, db: Session = Depends(get_db), user=Depends(auth.require_admin)):
    a = db.get(models.Album, album_id)
    if a:
        db.delete(a); db.commit()
    return {"ok": True}


@app.put("/api/photos/{photo_id}")
def update_photo(photo_id: int, payload: schemas.PhotoUpdateRequest, db: Session = Depends(get_db), user=Depends(auth.require_admin)):
    """直接编辑单张照片/视频项的标题与描述。"""
    p = db.get(models.Photo, photo_id)
    if not p:
        raise HTTPException(404, "媒体不存在")
    for k, value in payload.model_dump(exclude_unset=True).items():
        setattr(p, k, value)
    db.commit(); db.refresh(p)
    return p.as_dict()


# ---------------- 留言 ----------------
@app.get("/api/messages")
def list_messages(db: Session = Depends(get_db), user=Depends(auth.require_user)):
    return [m.as_dict() for m in db.query(models.Message).filter_by(status="approved").all()]


@app.post("/api/messages")
def create_message(payload: schemas.MessageCreateRequest, db: Session = Depends(get_db), user=Depends(auth.require_user)):
    colors = ["#ef8fa4", "#7fc8d4", "#ffca7a", "#9b8cff", "#6dc38f"]
    m = models.Message(
        name=payload.name or "访客",
        content=payload.content,
        color=payload.color or random.choice(colors),
        status="pending",
    )
    if not m.content.strip():
        raise HTTPException(400, "留言内容不能为空")
    db.add(m); db.commit(); db.refresh(m)
    return {"ok": True, "id": m.id, "status": m.status}


@app.post("/api/messages/{msg_id}/approve")
def approve_message(msg_id: int, db: Session = Depends(get_db), user=Depends(auth.require_admin)):
    m = db.get(models.Message, msg_id)
    if not m:
        raise HTTPException(404, "留言不存在")
    m.status = "approved"; db.commit()
    return m.as_dict()


@app.delete("/api/messages/{msg_id}")
def delete_message(msg_id: int, db: Session = Depends(get_db), user=Depends(auth.require_admin)):
    m = db.get(models.Message, msg_id)
    if m:
        db.delete(m); db.commit()
    return {"ok": True}


# ---------------- 管理：重置示例数据 ----------------
@app.post("/api/admin/seed")
def admin_seed(db: Session = Depends(get_db), user=Depends(auth.require_admin)):
    from .sampledata import seed_sample
    database_path = migrations.sqlite_path(settings.DATABASE_URL)
    if not database_path:
        raise HTTPException(501, "自动完整备份目前仅支持 SQLite")
    try:
        created = backup.create_backup(
            "pre-seed", database_path, settings.UPLOAD_DIR,
            settings.BACKUP_DIR, settings.BACKUP_RETENTION,
        )
    except backup.BackupValidationError as exc:
        raise HTTPException(500, f"重置前备份失败：{exc}")
    seed_sample(db, reset=True)
    return {"ok": True, "backupId": created["backupId"]}


# ---------------- 邀请码（仅管理员） ----------------
@app.get("/api/invites")
def list_invites(db: Session = Depends(get_db), user=Depends(auth.require_admin)):
    return [i.as_dict() for i in db.query(models.InviteCode).order_by(models.InviteCode.id.desc()).all()]


@app.post("/api/invites")
def create_invite(payload: schemas.InviteCreateRequest, db: Session = Depends(get_db), user=Depends(auth.require_admin)):
    code = secrets.token_hex(4).upper()
    while db.query(models.InviteCode).filter_by(code=code).first():
        code = secrets.token_hex(4).upper()
    inv = models.InviteCode(code=code, note=payload.note)
    db.add(inv); db.commit(); db.refresh(inv)
    return inv.as_dict()


@app.delete("/api/invites/{invite_id}")
def delete_invite(invite_id: int, db: Session = Depends(get_db), user=Depends(auth.require_admin)):
    inv = db.get(models.InviteCode, invite_id)
    if inv and not inv.usedBy:
        db.delete(inv); db.commit()
    return {"ok": True}


# ---------------- 成员管理（仅管理员） ----------------
@app.get("/api/users")
def list_users(db: Session = Depends(get_db), user=Depends(auth.require_admin)):
    return [u.as_dict() for u in db.query(models.User).order_by(models.User.id).all()]


@app.post("/api/users/{user_id}/status")
def set_user_status(user_id: int, payload: schemas.UserStatusRequest, db: Session = Depends(get_db), user=Depends(auth.require_admin)):
    u = db.get(models.User, user_id)
    if not u:
        raise HTTPException(404, "用户不存在")
    if u.role == "admin":
        raise HTTPException(400, "不能禁用管理员账号")
    u.disabled = payload.disabled
    db.commit(); db.refresh(u)
    return u.as_dict()


@app.post("/api/users/{user_id}/reset-password")
def reset_user_password(
    user_id: int,
    payload: schemas.UserPasswordResetRequest,
    db: Session = Depends(get_db),
    user=Depends(auth.require_admin),
):
    target = db.get(models.User, user_id)
    if not target:
        raise HTTPException(404, "用户不存在")
    if target.role == "admin":
        raise HTTPException(400, "不能通过成员管理重置管理员密码")
    if len(payload.newPassword) < settings.MIN_PASSWORD_LENGTH:
        raise HTTPException(400, f"新密码至少 {settings.MIN_PASSWORD_LENGTH} 位")
    password_hash = auth.hash_pw(payload.newPassword)
    target.password_hash = password_hash
    target.sessionVersion = int(target.sessionVersion or 0) + 1
    db.commit()
    return {"ok": True}


@app.delete("/api/users/{user_id}")
def delete_user(user_id: int, db: Session = Depends(get_db), user=Depends(auth.require_admin)):
    u = db.get(models.User, user_id)
    if u and u.role == "admin":
        raise HTTPException(400, "不能删除管理员账号")
    if u:
        db.delete(u); db.commit()
    return {"ok": True}


# ---------------- 相册分享链接（生成/撤销需管理员，查看免登录） ----------------
@app.get("/api/albums/{album_id}/share")
def get_album_share(album_id: int, db: Session = Depends(get_db), user=Depends(auth.require_admin)):
    sh = db.query(models.Share).filter_by(albumId=album_id).first()
    return sh.as_dict() if sh else {}


@app.post("/api/albums/{album_id}/share")
def make_album_share(album_id: int, payload: schemas.AlbumShareRequest, db: Session = Depends(get_db), user=Depends(auth.require_admin)):
    if not db.get(models.Album, album_id):
        raise HTTPException(404, "相册不存在")
    db.query(models.Share).filter_by(albumId=album_id).delete()
    days = payload.days
    exp = (datetime.now(timezone.utc) + timedelta(days=days)).isoformat() if days else None
    sh = models.Share(token=secrets.token_urlsafe(24),
                      albumId=album_id, expiresAt=exp)
    db.add(sh); db.commit(); db.refresh(sh)
    return sh.as_dict()


@app.delete("/api/albums/{album_id}/share")
def revoke_album_share(album_id: int, db: Session = Depends(get_db), user=Depends(auth.require_admin)):
    db.query(models.Share).filter_by(albumId=album_id).delete(); db.commit()
    return {"ok": True}


@app.get("/api/share/{token}")
def view_share(token: str, db: Session = Depends(get_db)):
    sh = media.valid_share(db, token)
    a = db.query(models.Album).options(selectinload(models.Album.photos)).filter_by(id=sh.albumId).first()
    if not a:
        raise HTTPException(404, "相册不存在")
    b = db.get(models.Baby, 1)
    return {"album": media.scoped_album_dict(a, token), "babyName": (b.name if b else "宝贝"), "expiresAt": sh.expiresAt}


# ---------------- 成长小结（生成需管理员，查看需登录） ----------------
@app.get("/api/recaps")
def list_recaps(db: Session = Depends(get_db), user=Depends(auth.require_user)):
    return [r.as_dict() for r in db.query(models.Recap).order_by(models.Recap.id.desc()).all()]


@app.post("/api/recaps/generate")
def gen_recap(payload: schemas.RecapGenerateRequest, db: Session = Depends(get_db), user=Depends(auth.require_admin)):
    period = payload.period
    content = ai.generate_recap(db, period)
    title = "本月成长小结" if period == "month" else "本周成长小结"
    r = models.Recap(period=period, title=title, content=content)
    db.add(r); db.commit(); db.refresh(r)
    return r.as_dict()


@app.delete("/api/recaps/{recap_id}")
def del_recap(recap_id: int, db: Session = Depends(get_db), user=Depends(auth.require_admin)):
    r = db.get(models.Recap, recap_id)
    if r:
        db.delete(r); db.commit()
    return {"ok": True}


# ---------------- 疫苗：载入标准免疫程序（仅管理员，库为空时填充） ----------------
@app.post("/api/vaccines/load-standard")
def load_standard_vaccines(db: Session = Depends(get_db), user=Depends(auth.require_admin)):
    from .defaults import VACCINE_SCHEDULE
    if db.query(models.Vaccine).count() == 0:
        for name, dose, mon in VACCINE_SCHEDULE:
            db.add(models.Vaccine(name=name, dose=dose, plannedMonth=mon))
        db.commit()
    return [v.as_dict() for v in db.query(models.Vaccine).all()]


# ---------------- 数据备份：导出 / 导入（仅管理员） ----------------
def _sqlite_database_path():
    path = migrations.sqlite_path(settings.DATABASE_URL)
    if not path:
        raise HTTPException(501, "完整备份与安全导入目前仅支持 SQLite")
    return path


def _backup_response(item):
    database = item.get("database") or {}
    uploads_data = item.get("uploads") or {}
    return {
        "backupId": item.get("backupId"),
        "createdAt": item.get("createdAt"),
        "reason": item.get("reason"),
        "bytes": item.get("bytes", 0),
        "databaseBytes": database.get("bytes", 0),
        "uploadFiles": uploads_data.get("files", 0),
        "uploadBytes": uploads_data.get("bytes", 0),
        "valid": item.get("valid", True),
    }


@app.get("/api/backups")
def list_full_backups(user=Depends(auth.require_admin)):
    return [_backup_response(item) for item in backup.list_backups(settings.BACKUP_DIR)]


@app.post("/api/backups")
def create_full_backup(payload: schemas.BackupCreateRequest, user=Depends(auth.require_admin)):
    reason = payload.reason or "manual"
    try:
        created = backup.create_backup(
            reason, _sqlite_database_path(), settings.UPLOAD_DIR,
            settings.BACKUP_DIR, settings.BACKUP_RETENTION,
        )
    except backup.BackupValidationError as exc:
        raise HTTPException(500, str(exc))
    return _backup_response(created)


@app.get("/api/backups/{backup_id}/download")
def download_full_backup(backup_id: str, user=Depends(auth.require_admin)):
    try:
        path = backup.backup_path(settings.BACKUP_DIR, backup_id)
        backup.verify_backup(path)
    except backup.BackupValidationError as exc:
        raise HTTPException(404, str(exc))
    return FileResponse(path, media_type="application/zip", filename=path.name,
                        headers={"Cache-Control": "private, no-store"})


@app.delete("/api/backups/{backup_id}")
def delete_full_backup(backup_id: str, user=Depends(auth.require_admin)):
    try:
        backup.delete_backup(settings.BACKUP_DIR, backup_id)
    except backup.BackupValidationError as exc:
        raise HTTPException(400, str(exc))
    return {"ok": True}


@app.post("/api/media/cleanup/preview")
def preview_media_cleanup(
    payload: schemas.CleanupPreviewRequest,
    db: Session = Depends(get_db),
    user=Depends(auth.require_admin),
):
    hours = payload.olderThanHours
    report = media_storage.scan_media(db, settings.UPLOAD_DIR, hours)
    return {
        **media_storage.public_summary(report),
        "confirmToken": media_storage.create_cleanup_token(user.id, hours),
    }


@app.post("/api/media/cleanup")
def cleanup_media(
    payload: schemas.CleanupExecuteRequest,
    db: Session = Depends(get_db),
    user=Depends(auth.require_admin),
):
    hours = payload.olderThanHours
    try:
        media_storage.verify_cleanup_token(payload.confirmToken, user.id, hours)
    except media_storage.MediaCleanupError as exc:
        raise HTTPException(400, str(exc))
    report = media_storage.scan_media(db, settings.UPLOAD_DIR, hours)
    candidates = len(report["orphan"]) + len(report["temporary"])
    backup_id = None
    if candidates:
        try:
            created = backup.create_backup(
                "pre-media-cleanup", _sqlite_database_path(), settings.UPLOAD_DIR,
                settings.BACKUP_DIR, settings.BACKUP_RETENTION,
            )
            backup_id = created["backupId"]
        except backup.BackupValidationError as exc:
            raise HTTPException(500, f"清理前备份失败：{exc}")
    result = media_storage.delete_candidates(report, settings.UPLOAD_DIR)
    return {**result, "backupId": backup_id}


@app.get("/api/export")
def export_data(db: Session = Depends(get_db), user=Depends(auth.require_admin)):
    baby = db.get(models.Baby, 1)
    setting = db.get(models.Setting, 1)
    return {
        "version": 1, "exportedAt": models.now_iso(),
        "baby": baby.as_dict() if baby else {},
        "settings": setting.data if setting else {},
        "milestones": [x.as_dict() for x in db.query(models.Milestone).all()],
        "albums": [x.as_dict() for x in db.query(models.Album).options(selectinload(models.Album.photos)).all()],
        "growth": [x.as_dict() for x in db.query(models.Growth).all()],
        "daily": [x.as_dict() for x in db.query(models.Daily).all()],
        "diary": [x.as_dict() for x in db.query(models.Diary).all()],
        "videos": [x.as_dict() for x in db.query(models.Video).all()],
        "messages": [x.as_dict() for x in db.query(models.Message).all()],
        "recaps": [x.as_dict() for x in db.query(models.Recap).all()],
        "vaccines": [x.as_dict() for x in db.query(models.Vaccine).all()],
    }


@app.post("/api/import/validate")
def validate_import_data(payload: dict = Body(...), user=Depends(auth.require_admin)):
    try:
        _, result = imports.validate_import_payload(payload, settings.MAX_IMPORT_RECORDS)
        return result
    except imports.ImportValidationError as exc:
        raise HTTPException(400, str(exc))


@app.post("/api/import")
def import_data(
    payload: dict = Body(...),
    confirm: bool = Query(False),
    db: Session = Depends(get_db),
    user=Depends(auth.require_admin),
):
    if not confirm:
        raise HTTPException(400, "请先预检并明确确认导入")
    try:
        result = imports.apply_import(
            db, payload, _sqlite_database_path(), settings.UPLOAD_DIR,
            settings.BACKUP_DIR, settings.BACKUP_RETENTION,
            settings.MAX_IMPORT_RECORDS,
        )
    except imports.ImportValidationError as exc:
        raise HTTPException(400, str(exc))
    except backup.BackupValidationError as exc:
        raise HTTPException(500, f"导入前备份失败：{exc}")
    return {"ok": True, **result}


@app.get("/api/diary/{diary_id}")
def get_diary(diary_id: int, db: Session = Depends(get_db), user=Depends(auth.require_user)):
    diary = db.get(models.Diary, diary_id)
    if not diary:
        raise HTTPException(404, "日记不存在")
    return diary.as_dict()


@app.get("/api/admin/history/{resource}")
def list_admin_history(
    resource: str,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    user=Depends(auth.require_admin),
):
    if resource == "albums":
        total = db.query(func.count(models.Album.id)).scalar() or 0
        rows = (
            db.query(models.Album, func.count(models.Photo.id))
            .outerjoin(models.Photo, models.Photo.albumId == models.Album.id)
            .group_by(models.Album.id)
            .order_by(models.Album.date.desc(), models.Album.id.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )
        items = [_album_summary(album, photo_count) for album, photo_count in rows]
    elif resource == "daily":
        total = db.query(func.count(models.Daily.id)).scalar() or 0
        items = [
            item.as_dict()
            for item in (
                db.query(models.Daily)
                .order_by(models.Daily.time.desc(), models.Daily.id.desc())
                .offset(offset)
                .limit(limit)
                .all()
            )
        ]
    elif resource == "diary":
        total = db.query(func.count(models.Diary.id)).scalar() or 0
        items = [
            item.as_dict()
            for item in (
                db.query(models.Diary)
                .order_by(models.Diary.date.desc(), models.Diary.id.desc())
                .offset(offset)
                .limit(limit)
                .all()
            )
        ]
    else:
        raise HTTPException(404, "不支持的历史资源")
    return {
        "items": items,
        "total": int(total),
        "limit": limit,
        "offset": offset,
        "hasMore": offset + len(items) < total,
    }


# ---------------- 通用资源 CRUD（放在最后，避免覆盖上面的具体路由） ----------------
@app.get("/api/{res}")
def list_res(res: str, db: Session = Depends(get_db), user=Depends(auth.require_user)):
    Model = RES.get(res)
    if not Model:
        raise HTTPException(404, "未知资源")
    return [x.as_dict() for x in db.query(Model).all()]


def _validated_resource_payload(res: str, payload: dict, update: bool) -> dict:
    request_models = schemas.RESOURCE_REQUESTS.get(res)
    if not request_models:
        raise HTTPException(404, "未知资源")
    schema = request_models[1 if update else 0]
    try:
        validated = schema.model_validate(payload)
    except ValidationError as exc:
        raise HTTPException(
            422,
            detail=exc.errors(include_url=False, include_context=False, include_input=False),
        )
    return validated.model_dump(exclude_unset=update)


@app.post("/api/{res}")
def create_res(res: str, payload: dict = Body(...), db: Session = Depends(get_db), user=Depends(auth.require_admin)):
    Model = RES.get(res)
    if not Model:
        raise HTTPException(404, "未知资源")
    values = _validated_resource_payload(res, payload, update=False)
    obj = Model(**{k: values[k] for k in Model.FIELDS if k in values})
    db.add(obj); db.commit(); db.refresh(obj)
    return obj.as_dict()


@app.put("/api/{res}/{item_id}")
def update_res(res: str, item_id: int, payload: dict = Body(...), db: Session = Depends(get_db), user=Depends(auth.require_admin)):
    Model = RES.get(res)
    if not Model:
        raise HTTPException(404, "未知资源")
    obj = db.get(Model, item_id)
    if not obj:
        raise HTTPException(404, "记录不存在")
    values = _validated_resource_payload(res, payload, update=True)
    for k in Model.FIELDS:
        if k in values:
            setattr(obj, k, values[k])
    db.commit(); db.refresh(obj)
    return obj.as_dict()


@app.delete("/api/{res}/{item_id}")
def delete_res(res: str, item_id: int, db: Session = Depends(get_db), user=Depends(auth.require_admin)):
    Model = RES.get(res)
    if not Model:
        raise HTTPException(404, "未知资源")
    obj = db.get(Model, item_id)
    if obj:
        db.delete(obj); db.commit()
    return {"ok": True}


# ---------------- 静态资源（前端 + 上传） ----------------
_ensure_dirs()


class CachedStaticFiles(StaticFiles):
    """静态资源响应带上长缓存头：入口 html 始终协商缓存（no-cache），
    其余 js/css/图片等由 index.html 里的 ?v= 版本号控制更新，可视为 immutable。"""

    def file_response(self, full_path, stat_result, scope, status_code=200):
        response = super().file_response(full_path, stat_result, scope, status_code)
        cache = "no-cache" if str(full_path).endswith(".html") else "public, max-age=31536000, immutable"
        response.headers["Cache-Control"] = cache
        return response


CLIENT_DIR = os.environ.get("CLIENT_DIR") or os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "client"))
if os.path.isdir(CLIENT_DIR):
    app.mount("/", CachedStaticFiles(directory=CLIENT_DIR, html=True), name="client")
