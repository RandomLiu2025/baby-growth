from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, Request, Response
from fastapi.security import OAuth2PasswordBearer
import jwt
from jwt import InvalidTokenError
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from .config import settings
from .db import get_db
from . import models

pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2 = OAuth2PasswordBearer(tokenUrl="api/auth/login", auto_error=False)


def hash_pw(p: str) -> str:
    return pwd_ctx.hash(p)


def verify_pw(p: str, h: str) -> bool:
    try:
        return pwd_ctx.verify(p, h)
    except Exception:
        return False


def create_token(sub, session_version: int = 0) -> str:
    exp = datetime.now(timezone.utc) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    return jwt.encode(
        {"sub": str(sub), "ver": int(session_version or 0), "exp": exp},
        settings.SECRET_KEY,
        algorithm=settings.ALGORITHM,
    )


def set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=settings.SESSION_COOKIE_NAME,
        value=token,
        max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        httponly=True,
        secure=settings.SESSION_COOKIE_SECURE,
        samesite="strict",
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(
        key=settings.SESSION_COOKIE_NAME,
        httponly=True,
        secure=settings.SESSION_COOKIE_SECURE,
        samesite="strict",
        path="/",
    )


def _user_from_token(token, db: Session):
    if not token:
        return None
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        uid = payload.get("sub")
        token_version = int(payload.get("ver", 0))
    except (InvalidTokenError, TypeError, ValueError):
        return None
    if not uid:
        return None
    try:
        user_id = int(uid)
    except (TypeError, ValueError):
        return None
    u = db.get(models.User, user_id)
    if u and int(getattr(u, "sessionVersion", 0) or 0) != token_version:
        return None
    if u and getattr(u, "disabled", False):
        return None       # 已禁用账号视为未登录
    return u


def _request_token(request: Request, bearer_token: str | None) -> str | None:
    return bearer_token or request.cookies.get(settings.SESSION_COOKIE_NAME)


def current_user_optional(
    request: Request,
    token: str = Depends(oauth2),
    db: Session = Depends(get_db),
):
    """返回当前用户或 None（用于公开接口区分是否管理员）。"""
    return _user_from_token(_request_token(request, token), db)


def require_user(
    request: Request,
    token: str = Depends(oauth2),
    db: Session = Depends(get_db),
):
    """任何已登录用户（管理员或家庭成员）。"""
    user = _user_from_token(_request_token(request, token), db)
    if not user:
        raise HTTPException(status_code=401, detail="请先登录")
    return user


def require_admin(
    request: Request,
    token: str = Depends(oauth2),
    db: Session = Depends(get_db),
):
    user = _user_from_token(_request_token(request, token), db)
    if not user:
        raise HTTPException(status_code=401, detail="请先登录")
    if getattr(user, "role", "member") != "admin":
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return user
