import os
import re
import copy
import uuid
import shutil
import subprocess
import mimetypes
import secrets
import random
from time import time
from collections import defaultdict
from contextlib import asynccontextmanager
from datetime import datetime, timezone, timedelta

from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, Form, Body, Request, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.security import OAuth2PasswordRequestForm
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session, selectinload
from sqlalchemy.orm.attributes import flag_modified

from .config import settings, DEFAULT_SECRET_KEY, DEFAULT_ADMIN_PASSWORD
from .db import Base, engine, get_db, SessionLocal
from . import models, auth, ai
from .defaults import DEFAULT_SETTINGS, DEFAULT_BABY


@asynccontextmanager
async def lifespan(app: FastAPI):
    _warn_insecure_defaults()
    _ensure_dirs()
    Base.metadata.create_all(engine)
    ensure_schema()
    db = SessionLocal()
    try:
        ensure_init(db)
    finally:
        db.close()
    yield


app = FastAPI(title="宝贝成长记 API", version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_list or ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
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


# ---------------- 初始化 ----------------
def _warn_insecure_defaults():
    """启动时检查是否仍在使用默认密钥/密码，打印醒目警告（不阻断启动，方便首次体验）。"""
    warns = []
    if settings.SECRET_KEY == DEFAULT_SECRET_KEY:
        warns.append("SECRET_KEY 仍为默认值——任何人都可伪造登录 token！请在 .env 中改为长随机字符串。")
    if settings.ADMIN_PASSWORD == DEFAULT_ADMIN_PASSWORD:
        warns.append("ADMIN_PASSWORD 仍为默认值 admin123，请尽快在 .env 中修改。")
    for w in warns:
        print(f"\033[1;31m[安全警告] {w}\033[0m")


def _ensure_dirs():
    if settings.DATABASE_URL.startswith("sqlite"):
        p = settings.DATABASE_URL.split("sqlite:///")[-1]
        d = os.path.dirname(p)
        if d:
            os.makedirs(d, exist_ok=True)
    os.makedirs(settings.UPLOAD_DIR, exist_ok=True)


def ensure_init(db: Session):
    admin = db.query(models.User).filter_by(username=settings.ADMIN_USERNAME).first()
    if not admin:
        db.add(models.User(username=settings.ADMIN_USERNAME,
                           password_hash=auth.hash_pw(settings.ADMIN_PASSWORD), role="admin"))
    elif admin.role != "admin":
        admin.role = "admin"
    if not db.get(models.Baby, 1):
        db.add(models.Baby(id=1, **DEFAULT_BABY))
    if not db.get(models.Setting, 1):
        db.add(models.Setting(id=1, data=copy.deepcopy(DEFAULT_SETTINGS)))
    db.commit()


def ensure_schema():
    """轻量升级：为已存在的 SQLite 库补加新增列，避免旧库升级后缺列。"""
    if not settings.DATABASE_URL.startswith("sqlite"):
        return
    from sqlalchemy import text
    additions = {"photos": [("desc", "TEXT DEFAULT ''")],
                 "users": [("role", "TEXT DEFAULT 'member'"), ("disabled", "INTEGER DEFAULT 0")]}
    with engine.connect() as conn:
        for table, cols in additions.items():
            try:
                existing = [r[1] for r in conn.execute(text(f"PRAGMA table_info({table})"))]
                for col, decl in cols:
                    if col not in existing:
                        conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {decl}"))
                conn.commit()
            except Exception:
                pass


def sanitize(data, is_admin):
    d = copy.deepcopy(data or {})
    if not is_admin and isinstance(d.get("ai"), dict):
        d["ai"] = {**d["ai"], "apiKey": ""}
    return d


# ---------------- 登录限流（内存级） ----------------
_LOGIN_LIMIT_WINDOW = 15 * 60      # 15 分钟
_LOGIN_MAX_ATTEMPTS = 5
_login_attempts: dict[str, list[float]] = defaultdict(list)

def _check_login_rate(ip: str):
    now = time()
    timestamps = _login_attempts[ip]
    # 清理窗口外的记录
    _login_attempts[ip] = [t for t in timestamps if now - t < _LOGIN_LIMIT_WINDOW]
    if len(_login_attempts[ip]) >= _LOGIN_MAX_ATTEMPTS:
        remaining = int(_LOGIN_LIMIT_WINDOW - (now - _login_attempts[ip][0]))
        raise HTTPException(429, f"登录尝试过于频繁，请 {remaining//60} 分钟后再试")
    _login_attempts[ip].append(now)


# ---------------- 鉴权 ----------------
@app.post("/api/auth/login")
def login(request: Request, form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    ip = request.client.host if request.client else "unknown"
    _check_login_rate(ip)
    user = db.query(models.User).filter_by(username=form.username).first()
    if not user or not auth.verify_pw(form.password, user.password_hash):
        raise HTTPException(401, "账号或密码不正确")
    if user.disabled:
        raise HTTPException(403, "该账号已被禁用，请联系管理员")
    # 登录成功后清除该 IP 的失败记录
    _login_attempts.pop(ip, None)
    return {"access_token": auth.create_token(user.id), "token_type": "bearer", "user": user.as_dict()}


@app.post("/api/auth/register")
def register(payload: dict = Body(...), db: Session = Depends(get_db)):
    username = (payload.get("username") or "").strip()
    password = payload.get("password") or ""
    code = (payload.get("code") or "").strip()
    if not username or not password:
        raise HTTPException(400, "请填写用户名和密码")
    if len(password) < 4:
        raise HTTPException(400, "密码至少 4 位")
    inv = db.query(models.InviteCode).filter_by(code=code).first()
    if not inv or inv.usedBy:
        raise HTTPException(400, "邀请码无效或已被使用")
    if db.query(models.User).filter_by(username=username).first():
        raise HTTPException(400, "该用户名已被注册")
    u = models.User(username=username, password_hash=auth.hash_pw(password), role="member")
    db.add(u)
    inv.usedBy = username
    inv.usedAt = models.now_iso()
    db.commit(); db.refresh(u)
    return {"access_token": auth.create_token(u.id), "token_type": "bearer", "user": u.as_dict()}


@app.get("/api/auth/me")
def me(user=Depends(auth.require_user)):
    return user.as_dict()


@app.post("/api/auth/change-password")
def change_password(payload: dict = Body(...), db: Session = Depends(get_db), user=Depends(auth.require_user)):
    old = payload.get("oldPassword") or ""
    new = payload.get("newPassword") or ""
    if not auth.verify_pw(old, user.password_hash):
        raise HTTPException(400, "当前密码不正确")
    if len(new) < 4:
        raise HTTPException(400, "新密码至少 4 位")
    user.password_hash = auth.hash_pw(new)
    db.commit()
    return {"ok": True}


@app.get("/api/health")
def health():
    return {"ok": True, "name": "宝贝成长记 API"}


# ---------------- 品牌（公开，未登录也能拿到 favicon / 宝贝名） ----------------
@app.get("/api/branding")
def branding(db: Session = Depends(get_db)):
    setting = db.get(models.Setting, 1)
    baby = db.get(models.Baby, 1)
    s = setting.data if setting else DEFAULT_SETTINGS
    return {
        "faviconUrl": (s or {}).get("faviconUrl", ""),
        "babyName": (baby.name if baby else DEFAULT_BABY.get("name", "")) or "",
    }


# ---------------- 汇总 ----------------
@app.get("/api/bootstrap")
def bootstrap(db: Session = Depends(get_db), user=Depends(auth.require_user)):
    is_admin = user.role == "admin"
    baby = db.get(models.Baby, 1)
    setting = db.get(models.Setting, 1)
    mq = db.query(models.Message)
    if not is_admin:
        mq = mq.filter_by(status="approved")
    return {
        "baby": baby.as_dict() if baby else DEFAULT_BABY,
        "settings": sanitize(setting.data if setting else DEFAULT_SETTINGS, is_admin),
        "milestones": [x.as_dict() for x in db.query(models.Milestone).all()],
        "albums": [x.as_dict() for x in db.query(models.Album).options(selectinload(models.Album.photos)).all()],
        "growth": [x.as_dict() for x in db.query(models.Growth).all()],
        "daily": [x.as_dict() for x in db.query(models.Daily).all()],
        "diary": [x.as_dict() for x in db.query(models.Diary).all()],
        "videos": [x.as_dict() for x in db.query(models.Video).all()],
        "messages": [x.as_dict() for x in mq.all()],
        "recaps": [r.as_dict() for r in db.query(models.Recap).order_by(models.Recap.id.desc()).all()],
        "vaccines": [v.as_dict() for v in db.query(models.Vaccine).all()],
        "limits": {"imageMB": settings.MAX_IMAGE_MB, "videoMB": settings.MAX_VIDEO_MB},
        "isAdmin": is_admin,
        "user": {"username": user.username, "role": user.role},
    }


# ---------------- 上传 ----------------
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".svg", ".avif", ".heic"}
VIDEO_EXT = {".mp4", ".webm", ".ogg", ".ogv", ".mov", ".m4v", ".mkv"}


def classify_upload(filename, content_type):
    """按扩展名 + MIME 判断类型，返回 (kind, ext, 大小上限MB)。不支持则 kind 为 None。"""
    ext = os.path.splitext(filename or "")[1].lower()
    ct = (content_type or "").lower()
    if ext in IMAGE_EXT or ct.startswith("image/"):
        return "image", (ext if ext in IMAGE_EXT else ".jpg"), settings.MAX_IMAGE_MB
    if ext in VIDEO_EXT or ct.startswith("video/"):
        return "video", (ext if ext in VIDEO_EXT else ".mp4"), settings.MAX_VIDEO_MB
    return None, ext, 0


def generate_poster(video_path):
    """用 ffmpeg 抽取一帧作为视频封面。无 ffmpeg 或失败时返回 None（优雅降级，前端会退回视频首帧）。"""
    if not shutil.which("ffmpeg"):
        return None
    poster_name = f"{uuid.uuid4().hex}.jpg"
    poster_path = os.path.join(settings.UPLOAD_DIR, poster_name)
    for seek in ("00:00:01", "0"):
        try:
            subprocess.run(
                ["ffmpeg", "-y", "-ss", seek, "-i", video_path, "-frames:v", "1",
                 "-vf", "scale='min(800,iw)':-2", poster_path],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15, check=True,
            )
            if os.path.isfile(poster_path) and os.path.getsize(poster_path) > 0:
                return f"/uploads/{poster_name}"
        except Exception:
            continue
    if os.path.isfile(poster_path) and os.path.getsize(poster_path) == 0:
        try:
            os.remove(poster_path)
        except OSError:
            pass
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
    except Exception:
        pass
    if os.path.isfile(thumb_path) and os.path.getsize(thumb_path) == 0:
        try:
            os.remove(thumb_path)
        except OSError:
            pass
    return None


def _bg_poster_and_thumb(video_path: str):
    """后台生成视频封面 + 封面缩略图。任何异常都吞掉，不影响主流程。"""
    try:
        poster = generate_poster(video_path)
        if poster:
            generate_thumb(os.path.join(settings.UPLOAD_DIR, os.path.basename(poster)))
    except Exception:
        pass


def _bg_thumb(image_path: str):
    """后台生成图片缩略图。任何异常都吞掉。"""
    try:
        generate_thumb(image_path)
    except Exception:
        pass


@app.post("/api/upload")
def upload(background_tasks: BackgroundTasks,
           files: list[UploadFile] = File(...),
           user=Depends(auth.require_admin)):
    urls, items = [], []
    for f in files:
        kind, ext, limit_mb = classify_upload(f.filename, f.content_type)
        if not kind:
            raise HTTPException(400, f"不支持的文件类型：{f.filename or '未命名'}（仅支持图片和视频）")
        limit = limit_mb * 1024 * 1024
        name = f"{uuid.uuid4().hex}{ext}"
        dest = os.path.join(settings.UPLOAD_DIR, name)
        size, exceeded = 0, False
        with open(dest, "wb") as out:
            while True:
                chunk = f.file.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > limit:
                    exceeded = True
                    break
                out.write(chunk)
        if exceeded:
            try:
                os.remove(dest)
            except OSError:
                pass
            zh = "图片" if kind == "image" else "视频"
            raise HTTPException(413, f"文件过大：{f.filename or '未命名'}（{zh}上限 {limit_mb}MB）")
        url = f"/uploads/{name}"
        # 缩略图/封面推迟到后台生成——立即返回响应，避免网络超时
        # 前端 MediaThumb 组件在 _thumb 不存在时会自动 fallback 到原图
        if kind == "video":
            background_tasks.add_task(_bg_poster_and_thumb, dest)
        else:
            background_tasks.add_task(_bg_thumb, dest)
        urls.append(url)
        items.append({"url": url, "kind": kind, "poster": None, "thumb": url})
    return {"urls": urls, "url": urls[0] if urls else None, "items": items}


# ---------------- 分片上传（用于大视频，避开 Cloudflare 100s 单请求上限） ----------------
CHUNKS_DIRNAME = ".chunks"
_UPLOAD_ID_RE = re.compile(r"^[a-f0-9]{32}$")


def _chunks_dir():
    d = os.path.join(settings.UPLOAD_DIR, CHUNKS_DIRNAME)
    os.makedirs(d, exist_ok=True)
    return d


@app.post("/api/upload/chunk")
def upload_chunk(
    file: UploadFile = File(...),
    uploadId: str = Form(...),
    index: int = Form(...),
    total: int = Form(...),
    user=Depends(auth.require_admin),
):
    if not _UPLOAD_ID_RE.match(uploadId):
        raise HTTPException(400, "无效的 uploadId")
    if total < 1 or total > 500:
        raise HTTPException(400, "无效的分片总数")
    if index < 0 or index >= total:
        raise HTTPException(400, "无效的分片编号")
    d = _chunks_dir()
    dest = os.path.join(d, f"{uploadId}_{index:04d}")
    size = 0
    limit = 10 * 1024 * 1024
    with open(dest, "wb") as out:
        while True:
            buf = file.file.read(1024 * 1024)
            if not buf:
                break
            size += len(buf)
            if size > limit:
                try:
                    out.close()
                    os.remove(dest)
                except Exception:
                    pass
                raise HTTPException(413, "单个分片超过 10MB")
            out.write(buf)
    return {"ok": True, "received": index + 1, "total": total}


@app.post("/api/upload/complete")
def upload_complete(
    background_tasks: BackgroundTasks,
    payload: dict = Body(...),
    user=Depends(auth.require_admin),
):
    uploadId = str(payload.get("uploadId") or "")
    total = int(payload.get("total") or 0)
    filename = str(payload.get("filename") or "")
    if not _UPLOAD_ID_RE.match(uploadId):
        raise HTTPException(400, "无效的 uploadId")
    if total < 1 or total > 500:
        raise HTTPException(400, "无效的分片总数")

    d = _chunks_dir()
    chunks = []
    for i in range(total):
        p = os.path.join(d, f"{uploadId}_{i:04d}")
        if not os.path.isfile(p):
            for cc in chunks:
                try: os.remove(cc)
                except Exception: pass
            raise HTTPException(400, f"缺少分片 {i+1}/{total}，请重新上传")
        chunks.append(p)

    kind, ext, limit_mb = classify_upload(filename, "")
    if not kind:
        for cc in chunks:
            try: os.remove(cc)
            except Exception: pass
        raise HTTPException(400, f"不支持的文件类型：{filename or '未命名'}（仅支持图片和视频）")
    limit = limit_mb * 1024 * 1024

    name = f"{uuid.uuid4().hex}{ext}"
    final_path = os.path.join(settings.UPLOAD_DIR, name)
    total_size, exceeded = 0, False
    with open(final_path, "wb") as out:
        for c in chunks:
            with open(c, "rb") as inp:
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
    for c in chunks:
        try: os.remove(c)
        except Exception: pass
    if exceeded:
        try: os.remove(final_path)
        except Exception: pass
        zh = "图片" if kind == "image" else "视频"
        raise HTTPException(413, f"文件过大：{filename or '未命名'}（{zh}上限 {limit_mb}MB，当前 {total_size // 1024 // 1024}MB）")

    url = f"/uploads/{name}"
    if kind == "video":
        background_tasks.add_task(_bg_poster_and_thumb, final_path)
    else:
        background_tasks.add_task(_bg_thumb, final_path)
    return {
        "urls": [url],
        "url": url,
        "items": [{"url": url, "kind": kind, "poster": None, "thumb": url}],
    }


# ---------------- 上传文件访问（支持 HTTP Range，用于视频拖动/流式播放） ----------------
@app.get("/uploads/{name}")
def serve_upload(name: str, request: Request):
    safe_name = os.path.basename(name)  # 防目录穿越
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
    cache = "public, max-age=60" if fallback else "public, max-age=86400"
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
                    chunk = f.read(min(65536, left))
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
                chunk = f.read(65536)
                if not chunk:
                    break
                yield chunk

    return StreamingResponse(whole(), media_type=ctype,
                             headers={**base_headers, "Content-Length": str(size)})


# ---------------- AI ----------------
@app.post("/api/ai/chat")
def ai_chat(payload: dict = Body(...), db: Session = Depends(get_db),
            user=Depends(auth.require_user)):
    return ai.chat(payload.get("messages") or [], db, is_admin=user.role == "admin")


# ---------------- 宝贝信息 ----------------
@app.get("/api/baby")
def get_baby(db: Session = Depends(get_db), user=Depends(auth.require_user)):
    b = db.get(models.Baby, 1)
    return b.as_dict() if b else DEFAULT_BABY


@app.put("/api/baby")
def put_baby(payload: dict = Body(...), db: Session = Depends(get_db), user=Depends(auth.require_admin)):
    b = db.get(models.Baby, 1) or models.Baby(id=1)
    for k in models.Baby.FIELDS:
        if k in payload:
            setattr(b, k, payload[k])
    db.add(b); db.commit(); db.refresh(b)
    return b.as_dict()


# ---------------- 显示设置 ----------------
@app.get("/api/settings")
def get_settings(db: Session = Depends(get_db), user=Depends(auth.require_user)):
    s = db.get(models.Setting, 1)
    return sanitize(s.data if s else DEFAULT_SETTINGS, user.role == "admin")


@app.put("/api/settings")
def put_settings(payload: dict = Body(...), db: Session = Depends(get_db), user=Depends(auth.require_admin)):
    s = db.get(models.Setting, 1) or models.Setting(id=1, data={})
    s.data = payload
    db.add(s)
    flag_modified(s, "data")
    db.commit()
    return s.as_dict()


# ---------------- 相册（含照片） ----------------
def _sync_photos(album, photos):
    album.photos.clear()
    for i, p in enumerate(photos or []):
        album.photos.append(models.Photo(
            url=p.get("url", ""), caption=p.get("caption", ""), desc=p.get("desc", ""),
            takenAt=p.get("takenAt", ""), sort=i))


@app.get("/api/albums")
def list_albums(db: Session = Depends(get_db)):
    return [a.as_dict() for a in db.query(models.Album).options(selectinload(models.Album.photos)).all()]


@app.post("/api/albums")
def create_album(payload: dict = Body(...), db: Session = Depends(get_db), user=Depends(auth.require_admin)):
    a = models.Album(**{k: payload.get(k, "") for k in models.Album.FIELDS})
    _sync_photos(a, payload.get("photos"))
    if not a.cover and a.photos:
        a.cover = a.photos[0].url
    db.add(a); db.commit(); db.refresh(a)
    return a.as_dict()


@app.put("/api/albums/{album_id}")
def update_album(album_id: int, payload: dict = Body(...), db: Session = Depends(get_db), user=Depends(auth.require_admin)):
    a = db.get(models.Album, album_id)
    if not a:
        raise HTTPException(404, "相册不存在")
    for k in models.Album.FIELDS:
        if k in payload:
            setattr(a, k, payload[k])
    if "photos" in payload:
        _sync_photos(a, payload["photos"])
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
def update_photo(photo_id: int, payload: dict = Body(...), db: Session = Depends(get_db), user=Depends(auth.require_admin)):
    """直接编辑单张照片/视频项的标题与描述。"""
    p = db.get(models.Photo, photo_id)
    if not p:
        raise HTTPException(404, "媒体不存在")
    for k in ["caption", "desc"]:
        if k in payload:
            setattr(p, k, payload[k])
    db.commit(); db.refresh(p)
    return p.as_dict()


# ---------------- 留言 ----------------
@app.get("/api/messages")
def list_messages(db: Session = Depends(get_db), user=Depends(auth.require_user)):
    return [m.as_dict() for m in db.query(models.Message).filter_by(status="approved").all()]


@app.post("/api/messages")
def create_message(payload: dict = Body(...), db: Session = Depends(get_db), user=Depends(auth.require_user)):
    colors = ["#ef8fa4", "#7fc8d4", "#ffca7a", "#9b8cff", "#6dc38f"]
    m = models.Message(
        name=(payload.get("name") or "访客")[:40],
        content=(payload.get("content") or "")[:1000],
        color=payload.get("color") or random.choice(colors),
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
    seed_sample(db, reset=True)
    return {"ok": True}


# ---------------- 邀请码（仅管理员） ----------------
@app.get("/api/invites")
def list_invites(db: Session = Depends(get_db), user=Depends(auth.require_admin)):
    return [i.as_dict() for i in db.query(models.InviteCode).order_by(models.InviteCode.id.desc()).all()]


@app.post("/api/invites")
def create_invite(payload: dict = Body(default={}), db: Session = Depends(get_db), user=Depends(auth.require_admin)):
    code = secrets.token_hex(4).upper()
    while db.query(models.InviteCode).filter_by(code=code).first():
        code = secrets.token_hex(4).upper()
    inv = models.InviteCode(code=code, note=(payload.get("note") or "")[:60])
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
def set_user_status(user_id: int, payload: dict = Body(...), db: Session = Depends(get_db), user=Depends(auth.require_admin)):
    u = db.get(models.User, user_id)
    if not u:
        raise HTTPException(404, "用户不存在")
    if u.role == "admin":
        raise HTTPException(400, "不能禁用管理员账号")
    u.disabled = bool(payload.get("disabled"))
    db.commit(); db.refresh(u)
    return u.as_dict()


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
def make_album_share(album_id: int, payload: dict = Body(default={}), db: Session = Depends(get_db), user=Depends(auth.require_admin)):
    if not db.get(models.Album, album_id):
        raise HTTPException(404, "相册不存在")
    db.query(models.Share).filter_by(albumId=album_id).delete()
    days = payload.get("days")
    exp = (datetime.now(timezone.utc) + timedelta(days=int(days))).isoformat() if days else None
    sh = models.Share(token=secrets.token_urlsafe(9).replace("-", "x").replace("_", "y"),
                      albumId=album_id, expiresAt=exp)
    db.add(sh); db.commit(); db.refresh(sh)
    return sh.as_dict()


@app.delete("/api/albums/{album_id}/share")
def revoke_album_share(album_id: int, db: Session = Depends(get_db), user=Depends(auth.require_admin)):
    db.query(models.Share).filter_by(albumId=album_id).delete(); db.commit()
    return {"ok": True}


@app.get("/api/share/{token}")
def view_share(token: str, db: Session = Depends(get_db)):
    sh = db.query(models.Share).filter_by(token=token).first()
    if not sh:
        raise HTTPException(404, "分享链接无效或已撤销")
    if sh.expiresAt:
        try:
            exp = datetime.fromisoformat(sh.expiresAt)
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=timezone.utc)
            if datetime.now(timezone.utc) > exp:
                raise HTTPException(410, "分享链接已过期")
        except HTTPException:
            raise
        except Exception:
            pass
    a = db.get(models.Album, sh.albumId)
    if not a:
        raise HTTPException(404, "相册不存在")
    b = db.get(models.Baby, 1)
    return {"album": a.as_dict(), "babyName": (b.name if b else "宝贝"), "expiresAt": sh.expiresAt}


# ---------------- 成长小结（生成需管理员，查看需登录） ----------------
@app.get("/api/recaps")
def list_recaps(db: Session = Depends(get_db), user=Depends(auth.require_user)):
    return [r.as_dict() for r in db.query(models.Recap).order_by(models.Recap.id.desc()).all()]


@app.post("/api/recaps/generate")
def gen_recap(payload: dict = Body(default={}), db: Session = Depends(get_db), user=Depends(auth.require_admin)):
    period = payload.get("period") if payload.get("period") in ("week", "month") else "week"
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


@app.post("/api/import")
def import_data(payload: dict = Body(...), db: Session = Depends(get_db), user=Depends(auth.require_admin)):
    d = payload or {}
    if isinstance(d.get("baby"), dict):
        b = db.get(models.Baby, 1) or models.Baby(id=1)
        for k in models.Baby.FIELDS:
            if k in d["baby"]:
                setattr(b, k, d["baby"][k])
        db.add(b)
    if isinstance(d.get("settings"), dict):
        s = db.get(models.Setting, 1) or models.Setting(id=1, data={})
        s.data = d["settings"]
        db.add(s)
        flag_modified(s, "data")
    simple = {"milestones": models.Milestone, "growth": models.Growth, "daily": models.Daily,
              "diary": models.Diary, "videos": models.Video, "messages": models.Message,
              "recaps": models.Recap, "vaccines": models.Vaccine}
    for key, Model in simple.items():
        if isinstance(d.get(key), list):
            db.query(Model).delete()
            cols = {c.name for c in Model.__table__.columns} - {"id"}
            for row in d[key]:
                if isinstance(row, dict):
                    db.add(Model(**{k: v for k, v in row.items() if k in cols}))
    if isinstance(d.get("albums"), list):
        for a in db.query(models.Album).all():
            db.delete(a)
        db.flush()
        for row in d["albums"]:
            if not isinstance(row, dict):
                continue
            a = models.Album(**{k: row.get(k, "") for k in models.Album.FIELDS})
            for i, p in enumerate(row.get("photos") or []):
                a.photos.append(models.Photo(url=p.get("url", ""), caption=p.get("caption", ""),
                                             desc=p.get("desc", ""), takenAt=p.get("takenAt", ""), sort=i))
            db.add(a)
    db.commit()
    return {"ok": True}


# ---------------- 通用资源 CRUD（放在最后，避免覆盖上面的具体路由） ----------------
@app.get("/api/{res}")
def list_res(res: str, db: Session = Depends(get_db), user=Depends(auth.require_user)):
    Model = RES.get(res)
    if not Model:
        raise HTTPException(404, "未知资源")
    return [x.as_dict() for x in db.query(Model).all()]


@app.post("/api/{res}")
def create_res(res: str, payload: dict = Body(...), db: Session = Depends(get_db), user=Depends(auth.require_admin)):
    Model = RES.get(res)
    if not Model:
        raise HTTPException(404, "未知资源")
    obj = Model(**{k: payload[k] for k in Model.FIELDS if k in payload})
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
    for k in Model.FIELDS:
        if k in payload:
            setattr(obj, k, payload[k])
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

CLIENT_DIR = os.environ.get("CLIENT_DIR") or os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "client"))
if os.path.isdir(CLIENT_DIR):
    app.mount("/", StaticFiles(directory=CLIENT_DIR, html=True), name="client")
