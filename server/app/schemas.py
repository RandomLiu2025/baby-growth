from datetime import date, datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _date_value(value: str | None) -> str | None:
    if value in (None, ""):
        return value
    date.fromisoformat(value)
    return value


def _datetime_value(value: str | None) -> str | None:
    if value in (None, ""):
        return value
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("时间必须包含时区")
    return parsed.astimezone(timezone.utc).isoformat()


class RequestModel(BaseModel):
    model_config = ConfigDict(extra="ignore")


class RegisterRequest(RequestModel):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=256)
    code: str = Field(min_length=1, max_length=128)

    @field_validator("username", "code")
    @classmethod
    def strip_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("不能为空")
        return value


class ChangePasswordRequest(RequestModel):
    oldPassword: str = Field(max_length=256)
    newPassword: str = Field(max_length=256)


class UploadCompleteRequest(RequestModel):
    uploadId: str = Field(pattern=r"^[a-f0-9]{32}$")
    total: int = Field(ge=1, le=10000)
    filename: str = Field(min_length=1, max_length=500)
    fileSize: int = Field(ge=1)


class ChatMessage(RequestModel):
    role: Literal["user", "assistant"]
    content: str = Field(default="", max_length=10000)


class AIChatRequest(RequestModel):
    messages: list[ChatMessage] = Field(default_factory=list, max_length=20)


class BabyRequest(RequestModel):
    name: str = Field(default="宝贝", max_length=100)
    gender: Literal["girl", "boy"] = "girl"
    birthday: str = ""
    avatar: str = Field(default="", max_length=4096)
    bio: str = Field(default="", max_length=20000)
    family: str = Field(default="", max_length=20000)

    _birthday = field_validator("birthday")(_date_value)


class ThemeSettings(RequestModel):
    model_config = ConfigDict(extra="allow")
    name: str = Field(default="甜心粉", max_length=100)
    primary: str = Field(default="#ec8aa0", pattern=r"^#[0-9a-fA-F]{6}$")
    primaryD: str = Field(default="#d75f7e", pattern=r"^#[0-9a-fA-F]{6}$")
    secondary: str = Field(default="#7fc6d0", pattern=r"^#[0-9a-fA-F]{6}$")
    accent: str = Field(default="#ffc178", pattern=r"^#[0-9a-fA-F]{6}$")
    bg: str = Field(default="#fff6f3", pattern=r"^#[0-9a-fA-F]{6}$")


class DecoSettings(RequestModel):
    model_config = ConfigDict(extra="allow")
    enabled: bool = True
    opacity: float = Field(default=0.5, ge=0, le=1)
    emoji: list[str] = Field(default_factory=list, max_length=50)


class FeedingSettings(RequestModel):
    model_config = ConfigDict(extra="allow")
    defaultAmount: int = Field(default=150, ge=0, le=5000)
    dailyTarget: int = Field(default=900, ge=0, le=20000)


class AISettings(RequestModel):
    model_config = ConfigDict(extra="allow")
    enabled: bool = False
    apiKey: str = Field(default="", max_length=4096)
    apiKeyConfigured: bool = False
    clearApiKey: bool = False
    baseUrl: str = Field(default="https://api.openai.com/v1", max_length=4096)
    model: str = Field(default="gpt-4o-mini", max_length=300)


class SettingsRequest(RequestModel):
    model_config = ConfigDict(extra="allow")
    theme: ThemeSettings
    deco: DecoSettings
    modules: dict[str, bool]
    home: dict[str, bool]
    feeding: FeedingSettings
    ai: AISettings
    faviconUrl: str = Field(default="", max_length=4096)
    photoFrame: Literal["polaroid", "matted", "wood", "none"] = "polaroid"


class PhotoRequest(RequestModel):
    url: str = Field(default="", max_length=4096)
    caption: str = Field(default="", max_length=500)
    desc: str = Field(default="", max_length=20000)
    takenAt: str = ""
    sort: int = Field(default=0, ge=0, le=100000)

    _taken = field_validator("takenAt")(_date_value)


class AlbumRequest(RequestModel):
    name: str = Field(default="", max_length=300)
    date: str = ""
    desc: str = Field(default="", max_length=20000)
    cover: str = Field(default="", max_length=4096)
    photos: list[PhotoRequest] = Field(default_factory=list, max_length=10000)

    _date = field_validator("date")(_date_value)


class PhotoUpdateRequest(RequestModel):
    caption: str | None = Field(default=None, max_length=500)
    desc: str | None = Field(default=None, max_length=20000)


class MessageCreateRequest(RequestModel):
    name: str = Field(default="访客", max_length=40)
    content: str = Field(min_length=1, max_length=1000)
    color: str | None = Field(default=None, pattern=r"^#[0-9a-fA-F]{6}$")


class InviteCreateRequest(RequestModel):
    note: str = Field(default="", max_length=60)


class UserStatusRequest(RequestModel):
    disabled: bool


class UserPasswordResetRequest(RequestModel):
    newPassword: str = Field(min_length=1, max_length=256)


class AlbumShareRequest(RequestModel):
    days: int | None = Field(default=None, ge=1, le=3650)


class RecapGenerateRequest(RequestModel):
    period: Literal["week", "month"] = "week"


class BackupCreateRequest(RequestModel):
    reason: str = Field(default="manual", max_length=80)


class CleanupPreviewRequest(RequestModel):
    olderThanHours: int = Field(default=24, ge=1, le=24 * 365)


class CleanupExecuteRequest(CleanupPreviewRequest):
    confirmToken: str = Field(min_length=1, max_length=4096)


class MilestoneRequest(RequestModel):
    date: str
    title: str = Field(max_length=300)
    category: str = Field(default="成长", max_length=100)
    desc: str = Field(default="", max_length=20000)
    image: str = Field(default="", max_length=4096)

    _date = field_validator("date")(_date_value)


class MilestoneUpdate(RequestModel):
    date: str | None = None
    title: str | None = Field(default=None, max_length=300)
    category: str | None = Field(default=None, max_length=100)
    desc: str | None = Field(default=None, max_length=20000)
    image: str | None = Field(default=None, max_length=4096)

    _date = field_validator("date")(_date_value)


class GrowthRequest(RequestModel):
    date: str
    height: float | None = Field(default=None, ge=10, le=300)
    weight: float | None = Field(default=None, ge=0.1, le=500)
    head: float | None = Field(default=None, ge=5, le=100)

    _date = field_validator("date")(_date_value)


class GrowthUpdate(RequestModel):
    date: str | None = None
    height: float | None = Field(default=None, ge=10, le=300)
    weight: float | None = Field(default=None, ge=0.1, le=500)
    head: float | None = Field(default=None, ge=5, le=100)

    _date = field_validator("date")(_date_value)


class DailyRequest(RequestModel):
    type: Literal["feeding", "diaper"] = "feeding"
    feedType: Literal["", "formula", "breast"] = ""
    amount: int | None = Field(default=None, ge=0, le=5000)
    diaperType: Literal["", "pee", "poop"] = ""
    time: str
    note: str = Field(default="", max_length=5000)

    _time = field_validator("time")(_datetime_value)


class DailyUpdate(RequestModel):
    type: Literal["feeding", "diaper"] | None = None
    feedType: Literal["", "formula", "breast"] | None = None
    amount: int | None = Field(default=None, ge=0, le=5000)
    diaperType: Literal["", "pee", "poop"] | None = None
    time: str | None = None
    note: str | None = Field(default=None, max_length=5000)

    _time = field_validator("time")(_datetime_value)


class DiaryRequest(RequestModel):
    date: str
    title: str = Field(default="", max_length=500)
    content: str = Field(default="", max_length=100000)
    images: list[str] = Field(default_factory=list, max_length=500)

    _date = field_validator("date")(_date_value)


class DiaryUpdate(RequestModel):
    date: str | None = None
    title: str | None = Field(default=None, max_length=500)
    content: str | None = Field(default=None, max_length=100000)
    images: list[str] | None = Field(default=None, max_length=500)

    _date = field_validator("date")(_date_value)


class VideoRequest(RequestModel):
    date: str
    title: str = Field(default="", max_length=500)
    desc: str = Field(default="", max_length=20000)
    url: str = Field(default="", max_length=4096)
    cover: str = Field(default="", max_length=4096)

    _date = field_validator("date")(_date_value)


class VideoUpdate(RequestModel):
    date: str | None = None
    title: str | None = Field(default=None, max_length=500)
    desc: str | None = Field(default=None, max_length=20000)
    url: str | None = Field(default=None, max_length=4096)
    cover: str | None = Field(default=None, max_length=4096)

    _date = field_validator("date")(_date_value)


class VaccineRequest(RequestModel):
    name: str = Field(default="", max_length=300)
    dose: int = Field(default=1, ge=1, le=100)
    plannedMonth: int = Field(default=0, ge=0, le=300)
    date: str | None = None
    note: str = Field(default="", max_length=2000)

    _date = field_validator("date")(_date_value)


class VaccineUpdate(RequestModel):
    name: str | None = Field(default=None, max_length=300)
    dose: int | None = Field(default=None, ge=1, le=100)
    plannedMonth: int | None = Field(default=None, ge=0, le=300)
    date: str | None = None
    note: str | None = Field(default=None, max_length=2000)

    _date = field_validator("date")(_date_value)


RESOURCE_REQUESTS: dict[str, tuple[type[BaseModel], type[BaseModel]]] = {
    "milestones": (MilestoneRequest, MilestoneUpdate),
    "growth": (GrowthRequest, GrowthUpdate),
    "daily": (DailyRequest, DailyUpdate),
    "diary": (DiaryRequest, DiaryUpdate),
    "videos": (VideoRequest, VideoUpdate),
    "vaccines": (VaccineRequest, VaccineUpdate),
}
