from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer
from jose import jwt, JWTError
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


def create_token(sub) -> str:
    exp = datetime.now(timezone.utc) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    return jwt.encode({"sub": str(sub), "exp": exp}, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def _user_from_token(token, db: Session):
    if not token:
        return None
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        uid = payload.get("sub")
    except JWTError:
        return None
    if not uid:
        return None
    u = db.get(models.User, int(uid))
    if u and getattr(u, "disabled", False):
        return None       # 已禁用账号视为未登录
    return u


def current_user_optional(token: str = Depends(oauth2), db: Session = Depends(get_db)):
    """返回当前用户或 None（用于公开接口区分是否管理员）。"""
    return _user_from_token(token, db)


def require_user(token: str = Depends(oauth2), db: Session = Depends(get_db)):
    """任何已登录用户（管理员或家庭成员）。"""
    user = _user_from_token(token, db)
    if not user:
        raise HTTPException(status_code=401, detail="请先登录")
    return user


def require_admin(token: str = Depends(oauth2), db: Session = Depends(get_db)):
    user = _user_from_token(token, db)
    if not user:
        raise HTTPException(status_code=401, detail="请先登录")
    if getattr(user, "role", "member") != "admin":
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return user
