from collections import OrderedDict
from ipaddress import ip_address
from math import ceil
from threading import Lock
from time import monotonic

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import auth, models, schemas
from ..config import DEFAULT_ADMIN_PASSWORD, settings
from ..db import get_db


router = APIRouter(prefix="/api/auth", tags=["auth"])
_LOGIN_LIMIT_WINDOW = 15 * 60
_LOGIN_IDENTITY_MAX_ATTEMPTS = 5
_LOGIN_IP_MAX_ATTEMPTS = 30
_LOGIN_MAX_BUCKETS = 4096


class _LoginRateLimiter:
    def __init__(
        self,
        window: int,
        identity_limit: int,
        ip_limit: int,
        max_buckets: int,
    ):
        self.window = window
        self.identity_limit = identity_limit
        self.ip_limit = ip_limit
        self.max_buckets = max_buckets
        self.identity_attempts: OrderedDict[tuple[str, str], list[float]] = OrderedDict()
        self.ip_attempts: OrderedDict[str, list[float]] = OrderedDict()
        self.lock = Lock()
        self.next_cleanup = 0.0

    @staticmethod
    def normalize_username(username: str) -> str:
        return username.strip().casefold()

    def _active_attempts(self, store, key, now: float) -> list[float]:
        attempts = store.get(key)
        if not attempts:
            return []
        active = [attempt for attempt in attempts if now - attempt < self.window]
        if active:
            store[key] = active
            store.move_to_end(key)
        else:
            store.pop(key, None)
        return active

    def _cleanup(self, now: float) -> None:
        if now < self.next_cleanup:
            return
        for store in (self.identity_attempts, self.ip_attempts):
            expired = [
                key
                for key, attempts in store.items()
                if not attempts or now - attempts[-1] >= self.window
            ]
            for key in expired:
                store.pop(key, None)
        self.next_cleanup = now + min(60, self.window)

    def _append(self, store, key, now: float) -> None:
        attempts = self._active_attempts(store, key, now)
        if key not in store:
            if len(store) >= self.max_buckets:
                store.popitem(last=False)
            store[key] = attempts
        store[key].append(now)
        store.move_to_end(key)

    def retry_after(self, client_ip: str, username: str) -> int | None:
        now = monotonic()
        identity_key = (client_ip, self.normalize_username(username))
        with self.lock:
            self._cleanup(now)
            identity_attempts = self._active_attempts(self.identity_attempts, identity_key, now)
            ip_attempts = self._active_attempts(self.ip_attempts, client_ip, now)
            remaining = []
            if len(identity_attempts) >= self.identity_limit:
                remaining.append(self.window - (now - identity_attempts[0]))
            if len(ip_attempts) >= self.ip_limit:
                remaining.append(self.window - (now - ip_attempts[0]))
            if not remaining:
                return None
            return max(1, ceil(max(remaining)))

    def record_failure(self, client_ip: str, username: str) -> None:
        now = monotonic()
        identity_key = (client_ip, self.normalize_username(username))
        with self.lock:
            self._cleanup(now)
            self._append(self.identity_attempts, identity_key, now)
            self._append(self.ip_attempts, client_ip, now)

    def clear_identity(self, client_ip: str, username: str) -> None:
        identity_key = (client_ip, self.normalize_username(username))
        with self.lock:
            self.identity_attempts.pop(identity_key, None)

    def reset(self) -> None:
        with self.lock:
            self.identity_attempts.clear()
            self.ip_attempts.clear()
            self.next_cleanup = 0.0


_login_limiter = _LoginRateLimiter(
    window=_LOGIN_LIMIT_WINDOW,
    identity_limit=_LOGIN_IDENTITY_MAX_ATTEMPTS,
    ip_limit=_LOGIN_IP_MAX_ATTEMPTS,
    max_buckets=_LOGIN_MAX_BUCKETS,
)


def _client_ip(request: Request) -> str:
    direct_ip = request.client.host if request.client else "unknown"
    if not settings.TRUST_PROXY_HEADERS:
        return direct_ip
    forwarded_for = request.headers.get("X-Forwarded-For", "")
    candidate = forwarded_for.split(",", 1)[0].strip()
    if not candidate:
        return direct_ip
    try:
        return ip_address(candidate).compressed
    except ValueError:
        return direct_ip


def _enforce_login_rate(client_ip: str, username: str) -> None:
    retry_after = _login_limiter.retry_after(client_ip, username)
    if retry_after is None:
        return
    wait_minutes = max(1, ceil(retry_after / 60))
    raise HTTPException(
        429,
        f"登录尝试过于频繁，请 {wait_minutes} 分钟后再试",
        headers={"Retry-After": str(retry_after)},
    )


@router.post("/login")
def login(
    request: Request,
    response: Response,
    form: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
):
    client_ip = _client_ip(request)
    _enforce_login_rate(client_ip, form.username)
    user = db.query(models.User).filter_by(username=form.username).first()
    if not user or not auth.verify_pw(form.password, user.password_hash):
        _login_limiter.record_failure(client_ip, form.username)
        raise HTTPException(401, "账号或密码不正确")
    if user.disabled:
        _login_limiter.record_failure(client_ip, form.username)
        raise HTTPException(403, "该账号已被禁用，请联系管理员")
    _login_limiter.clear_identity(client_ip, form.username)
    auth.set_session_cookie(response, auth.create_token(user.id, user.sessionVersion))
    return {"user": user.as_dict()}


@router.post("/register")
def register(response: Response, payload: schemas.RegisterRequest, db: Session = Depends(get_db)):
    if len(payload.password) < settings.MIN_PASSWORD_LENGTH:
        raise HTTPException(400, f"密码至少 {settings.MIN_PASSWORD_LENGTH} 位")
    password_hash = auth.hash_pw(payload.password)
    claimed_at = models.now_iso()
    claim = db.execute(
        update(models.InviteCode)
        .where(models.InviteCode.code == payload.code, models.InviteCode.usedBy.is_(None))
        .values(usedBy=payload.username, usedAt=claimed_at)
        .execution_options(synchronize_session=False)
    )
    if claim.rowcount != 1:
        db.rollback()
        raise HTTPException(400, "邀请码无效或已被使用")
    user = models.User(
        username=payload.username,
        password_hash=password_hash,
        role="member",
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(400, "该用户名已被注册")
    db.refresh(user)
    auth.set_session_cookie(response, auth.create_token(user.id, user.sessionVersion))
    return {"user": user.as_dict()}


@router.post("/session", status_code=204)
def migrate_session(response: Response, user=Depends(auth.require_user)):
    auth.set_session_cookie(response, auth.create_token(user.id, user.sessionVersion))


@router.post("/logout", status_code=204)
def logout(response: Response):
    auth.clear_session_cookie(response)


@router.get("/me")
def me(user=Depends(auth.require_user)):
    return user.as_dict()


@router.post("/change-password")
def change_password(
    payload: schemas.ChangePasswordRequest,
    response: Response,
    db: Session = Depends(get_db),
    user=Depends(auth.require_user),
):
    if not auth.verify_pw(payload.oldPassword, user.password_hash):
        raise HTTPException(400, "当前密码不正确")
    if len(payload.newPassword) < settings.MIN_PASSWORD_LENGTH:
        raise HTTPException(400, f"新密码至少 {settings.MIN_PASSWORD_LENGTH} 位")
    if user.role == "admin" and payload.newPassword == DEFAULT_ADMIN_PASSWORD:
        raise HTTPException(400, "管理员不能使用公开默认密码")
    user.password_hash = auth.hash_pw(payload.newPassword)
    user.sessionVersion = int(user.sessionVersion or 0) + 1
    db.commit()
    auth.set_session_cookie(response, auth.create_token(user.id, user.sessionVersion))
    return {"ok": True}
