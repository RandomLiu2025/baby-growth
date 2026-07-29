from datetime import datetime, timezone

from sqlalchemy import Column, Integer, String, Float, Text, ForeignKey, JSON, Boolean
from sqlalchemy.orm import relationship

from .db import Base


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    username = Column(String, unique=True, nullable=False, index=True)
    password_hash = Column(String, nullable=False)
    role = Column(String, default="member")   # admin | member
    disabled = Column(Boolean, default=False)
    createdAt = Column(String, default=now_iso)

    def as_dict(self):
        return {"id": self.id, "username": self.username, "role": self.role,
                "disabled": bool(self.disabled), "createdAt": self.createdAt}


class InviteCode(Base):
    __tablename__ = "invites"
    id = Column(Integer, primary_key=True)
    code = Column(String, unique=True, index=True)
    note = Column(String, default="")
    usedBy = Column(String, nullable=True)
    usedAt = Column(String, nullable=True)
    createdAt = Column(String, default=now_iso)

    def as_dict(self):
        return {"id": self.id, "code": self.code, "note": self.note,
                "usedBy": self.usedBy, "usedAt": self.usedAt,
                "createdAt": self.createdAt, "used": bool(self.usedBy)}


class Baby(Base):
    __tablename__ = "baby"
    id = Column(Integer, primary_key=True)
    name = Column(String, default="宝贝")
    gender = Column(String, default="girl")
    birthday = Column(String, default="")
    avatar = Column(Text, default="")
    bio = Column(Text, default="")
    family = Column(Text, default="")

    FIELDS = ["name", "gender", "birthday", "avatar", "bio", "family"]

    def as_dict(self):
        return {k: getattr(self, k) for k in ["id", *self.FIELDS]}


class Milestone(Base):
    __tablename__ = "milestones"
    id = Column(Integer, primary_key=True)
    date = Column(String, index=True)
    title = Column(String, default="")
    category = Column(String, default="成长")
    desc = Column(Text, default="")
    image = Column(Text, default="")
    createdAt = Column(String, default=now_iso)

    FIELDS = ["date", "title", "category", "desc", "image"]

    def as_dict(self):
        return {k: getattr(self, k) for k in ["id", *self.FIELDS, "createdAt"]}


class Album(Base):
    __tablename__ = "albums"
    id = Column(Integer, primary_key=True)
    name = Column(String, default="")
    date = Column(String, default="")
    desc = Column(Text, default="")
    cover = Column(Text, default="")
    createdAt = Column(String, default=now_iso)
    photos = relationship("Photo", back_populates="album", cascade="all, delete-orphan",
                          order_by="Photo.sort")

    FIELDS = ["name", "date", "desc", "cover"]

    def as_dict(self):
        d = {k: getattr(self, k) for k in ["id", *self.FIELDS, "createdAt"]}
        d["photos"] = [p.as_dict() for p in self.photos]
        return d


class Photo(Base):
    __tablename__ = "photos"
    id = Column(Integer, primary_key=True)
    albumId = Column(Integer, ForeignKey("albums.id", ondelete="CASCADE"), index=True)
    url = Column(Text, default="")
    caption = Column(String, default="")
    desc = Column(Text, default="")
    takenAt = Column(String, default="")
    sort = Column(Integer, default=0)
    album = relationship("Album", back_populates="photos")

    def as_dict(self):
        return {k: getattr(self, k) for k in ["id", "albumId", "url", "caption", "desc", "takenAt", "sort"]}


class Growth(Base):
    __tablename__ = "growth"
    id = Column(Integer, primary_key=True)
    date = Column(String, index=True)
    height = Column(Float, nullable=True)
    weight = Column(Float, nullable=True)
    head = Column(Float, nullable=True)

    FIELDS = ["date", "height", "weight", "head"]

    def as_dict(self):
        return {k: getattr(self, k) for k in ["id", *self.FIELDS]}


class Daily(Base):
    __tablename__ = "daily"
    id = Column(Integer, primary_key=True)
    type = Column(String, default="feeding")       # feeding | diaper
    feedType = Column(String, default="")          # formula | breast
    amount = Column(Integer, nullable=True)        # ml
    diaperType = Column(String, default="")        # pee | poop
    time = Column(String, index=True, default=now_iso)
    note = Column(Text, default="")

    FIELDS = ["type", "feedType", "amount", "diaperType", "time", "note"]

    def as_dict(self):
        return {k: getattr(self, k) for k in ["id", *self.FIELDS]}


class Diary(Base):
    __tablename__ = "diary"
    id = Column(Integer, primary_key=True)
    date = Column(String, index=True)
    title = Column(String, default="")
    content = Column(Text, default="")
    images = Column(JSON, default=list)

    FIELDS = ["date", "title", "content", "images"]

    def as_dict(self):
        d = {k: getattr(self, k) for k in ["id", *self.FIELDS]}
        d["images"] = d.get("images") or []
        return d


class Video(Base):
    __tablename__ = "videos"
    id = Column(Integer, primary_key=True)
    date = Column(String, index=True)
    title = Column(String, default="")
    desc = Column(Text, default="")
    url = Column(Text, default="")          # 视频地址（上传或外链）
    cover = Column(Text, default="")        # 封面图，可空（空则用视频首帧）
    createdAt = Column(String, default=now_iso)

    FIELDS = ["date", "title", "desc", "url", "cover"]

    def as_dict(self):
        return {k: getattr(self, k) for k in ["id", *self.FIELDS, "createdAt"]}


class Vaccine(Base):
    __tablename__ = "vaccines"
    id = Column(Integer, primary_key=True)
    name = Column(String, default="")
    dose = Column(Integer, default=1)          # 第几剂
    plannedMonth = Column(Integer, default=0)  # 建议接种月龄
    date = Column(String, nullable=True)       # 实际接种日期（空=未接种）
    note = Column(String, default="")

    FIELDS = ["name", "dose", "plannedMonth", "date", "note"]

    def as_dict(self):
        return {k: getattr(self, k) for k in ["id", *self.FIELDS]}


class Share(Base):
    __tablename__ = "shares"
    id = Column(Integer, primary_key=True)
    token = Column(String, unique=True, index=True)
    albumId = Column(Integer, index=True)
    expiresAt = Column(String, nullable=True)   # ISO UTC，空表示永久
    createdAt = Column(String, default=now_iso)

    def as_dict(self):
        return {"id": self.id, "token": self.token, "albumId": self.albumId,
                "expiresAt": self.expiresAt, "createdAt": self.createdAt}


class Recap(Base):
    __tablename__ = "recaps"
    id = Column(Integer, primary_key=True)
    period = Column(String, default="week")   # week | month
    title = Column(String, default="")
    content = Column(Text, default="")
    createdAt = Column(String, default=now_iso)

    def as_dict(self):
        return {"id": self.id, "period": self.period, "title": self.title,
                "content": self.content, "createdAt": self.createdAt}


class Message(Base):
    __tablename__ = "messages"
    id = Column(Integer, primary_key=True)
    name = Column(String, default="")
    content = Column(Text, default="")
    color = Column(String, default="#ef8fa4")
    status = Column(String, default="pending", index=True)   # pending | approved
    createdAt = Column(String, default=now_iso)

    FIELDS = ["name", "content", "color", "status"]

    def as_dict(self):
        return {k: getattr(self, k) for k in ["id", *self.FIELDS, "createdAt"]}


class Setting(Base):
    __tablename__ = "settings"
    id = Column(Integer, primary_key=True)
    data = Column(JSON, default=dict)

    def as_dict(self):
        return self.data or {}
