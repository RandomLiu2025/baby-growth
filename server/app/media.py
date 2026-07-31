import os
from datetime import datetime, timezone
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from fastapi import HTTPException
from sqlalchemy import and_, exists, or_, select

from . import models


def valid_share(db, token: str, expired_status: int = 410):
    share = db.query(models.Share).filter_by(token=token).first()
    if not share:
        raise HTTPException(404, "分享链接无效或已撤销")
    if share.expiresAt:
        try:
            expires_at = datetime.fromisoformat(share.expiresAt)
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
        except (TypeError, ValueError):
            raise HTTPException(expired_status, "分享链接已过期")
        if datetime.now(timezone.utc) > expires_at:
            raise HTTPException(expired_status, "分享链接已过期")
    return share


def local_upload_name(url: str | None) -> str | None:
    if not isinstance(url, str):
        return None
    path = urlsplit(url).path
    prefix = "/uploads/"
    if not path.startswith(prefix):
        return None
    name = os.path.basename(path)
    return name if path == f"{prefix}{name}" else None


def scoped_media_url(url: str, token: str) -> str:
    if not local_upload_name(url):
        return url
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query["share"] = token
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def scoped_album_dict(album, token: str) -> dict:
    data = album.as_dict()
    data["cover"] = scoped_media_url(data.get("cover") or "", token)
    for photo in data.get("photos") or []:
        photo["url"] = scoped_media_url(photo.get("url") or "", token)
    return data


def _original_name(name: str) -> str:
    stem, ext = os.path.splitext(name)
    return f"{stem[:-6]}{ext}" if stem.endswith("_thumb") else name


def album_references_file(db, album_id: int, name: str) -> bool:
    names = {name, _original_name(name)}
    urls = [f"/uploads/{candidate}" for candidate in names]
    statement = select(or_(
        exists().where(and_(models.Album.id == album_id, models.Album.cover.in_(urls))),
        exists().where(and_(models.Photo.albumId == album_id, models.Photo.url.in_(urls))),
    ))
    return bool(db.execute(statement).scalar())


def authorize_media(db, user, share_token: str | None, name: str) -> str:
    if user:
        return "authenticated"
    if not share_token:
        raise HTTPException(401, "请先登录")
    try:
        share = valid_share(db, share_token, expired_status=404)
    except HTTPException:
        raise HTTPException(404, "文件不存在")
    if not album_references_file(db, share.albumId, name):
        raise HTTPException(404, "文件不存在")
    return "shared"
