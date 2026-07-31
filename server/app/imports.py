import copy
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from sqlalchemy.orm.attributes import flag_modified

from . import backup, models, secret_store
from .defaults import DEFAULT_SETTINGS


class ImportValidationError(Exception):
    pass


def _date_value(value: str | None) -> str | None:
    if value in (None, ""):
        return value
    date.fromisoformat(value)
    return value


def _datetime_value(value: str | None) -> str | None:
    if value in (None, ""):
        return value
    datetime.fromisoformat(value.replace("Z", "+00:00"))
    return value


class ImportModel(BaseModel):
    model_config = ConfigDict(extra="ignore")


class BabyImport(ImportModel):
    name: str = Field(default="宝贝", max_length=100)
    gender: Literal["girl", "boy"] = "girl"
    birthday: str = ""
    avatar: str = Field(default="", max_length=4096)
    bio: str = Field(default="", max_length=20000)
    family: str = Field(default="", max_length=20000)

    _birthday = field_validator("birthday")(_date_value)


class MilestoneImport(ImportModel):
    date: str
    title: str = Field(max_length=300)
    category: str = Field(default="成长", max_length=100)
    desc: str = Field(default="", max_length=20000)
    image: str = Field(default="", max_length=4096)
    createdAt: str | None = None

    _date = field_validator("date")(_date_value)
    _created = field_validator("createdAt")(_datetime_value)


class PhotoImport(ImportModel):
    url: str = Field(default="", max_length=4096)
    caption: str = Field(default="", max_length=500)
    desc: str = Field(default="", max_length=20000)
    takenAt: str = ""
    sort: int = Field(default=0, ge=0, le=100000)

    _taken = field_validator("takenAt")(_date_value)


class AlbumImport(ImportModel):
    name: str = Field(default="", max_length=300)
    date: str = ""
    desc: str = Field(default="", max_length=20000)
    cover: str = Field(default="", max_length=4096)
    createdAt: str | None = None
    photos: list[PhotoImport] = Field(default_factory=list, max_length=10000)

    _date = field_validator("date")(_date_value)
    _created = field_validator("createdAt")(_datetime_value)


class GrowthImport(ImportModel):
    date: str
    height: float | None = Field(default=None, ge=10, le=300)
    weight: float | None = Field(default=None, ge=0.1, le=500)
    head: float | None = Field(default=None, ge=5, le=100)

    _date = field_validator("date")(_date_value)


class DailyImport(ImportModel):
    type: Literal["feeding", "diaper"] = "feeding"
    feedType: Literal["", "formula", "breast"] = ""
    amount: int | None = Field(default=None, ge=0, le=5000)
    diaperType: Literal["", "pee", "poop"] = ""
    time: str
    note: str = Field(default="", max_length=5000)

    _time = field_validator("time")(_datetime_value)


class DiaryImport(ImportModel):
    date: str
    title: str = Field(default="", max_length=500)
    content: str = Field(default="", max_length=100000)
    images: list[str] = Field(default_factory=list, max_length=500)

    _date = field_validator("date")(_date_value)


class VideoImport(ImportModel):
    date: str
    title: str = Field(default="", max_length=500)
    desc: str = Field(default="", max_length=20000)
    url: str = Field(default="", max_length=4096)
    cover: str = Field(default="", max_length=4096)
    createdAt: str | None = None

    _date = field_validator("date")(_date_value)
    _created = field_validator("createdAt")(_datetime_value)


class MessageImport(ImportModel):
    name: str = Field(default="", max_length=100)
    content: str = Field(default="", max_length=5000)
    color: str = Field(default="#ef8fa4", pattern=r"^#[0-9a-fA-F]{6}$")
    status: Literal["pending", "approved"] = "pending"
    createdAt: str | None = None

    _created = field_validator("createdAt")(_datetime_value)


class RecapImport(ImportModel):
    period: Literal["week", "month"] = "week"
    title: str = Field(default="", max_length=500)
    content: str = Field(default="", max_length=100000)
    createdAt: str | None = None

    _created = field_validator("createdAt")(_datetime_value)


class VaccineImport(ImportModel):
    name: str = Field(default="", max_length=300)
    dose: int = Field(default=1, ge=1, le=100)
    plannedMonth: int = Field(default=0, ge=0, le=300)
    date: str | None = None
    note: str = Field(default="", max_length=2000)

    _date = field_validator("date")(_date_value)


class ImportDocument(ImportModel):
    version: Literal[1]
    exportedAt: str | None = None
    baby: BabyImport
    settings: dict = Field(default_factory=dict)
    milestones: list[MilestoneImport] = Field(default_factory=list, max_length=50000)
    albums: list[AlbumImport] = Field(default_factory=list, max_length=10000)
    growth: list[GrowthImport] = Field(default_factory=list, max_length=50000)
    daily: list[DailyImport] = Field(default_factory=list, max_length=50000)
    diary: list[DiaryImport] = Field(default_factory=list, max_length=50000)
    videos: list[VideoImport] = Field(default_factory=list, max_length=50000)
    messages: list[MessageImport] = Field(default_factory=list, max_length=50000)
    recaps: list[RecapImport] = Field(default_factory=list, max_length=50000)
    vaccines: list[VaccineImport] = Field(default_factory=list, max_length=50000)

    _exported = field_validator("exportedAt")(_datetime_value)


def _summary(document: ImportDocument) -> dict:
    return {
        "milestones": len(document.milestones),
        "albums": len(document.albums),
        "photos": sum(len(album.photos) for album in document.albums),
        "growth": len(document.growth),
        "daily": len(document.daily),
        "diary": len(document.diary),
        "videos": len(document.videos),
        "messages": len(document.messages),
        "recaps": len(document.recaps),
        "vaccines": len(document.vaccines),
    }


def validate_import_payload(payload, max_records: int = 50000):
    try:
        document = ImportDocument.model_validate(payload)
    except (ValidationError, ValueError, TypeError) as exc:
        raise ImportValidationError(str(exc)) from exc
    try:
        secret_store.protect_settings_data(document.settings)
    except secret_store.SecretStorageError as exc:
        raise ImportValidationError(str(exc)) from exc
    summary = _summary(document)
    total = sum(summary.values())
    if total > max_records:
        raise ImportValidationError(f"导入记录总数超过 {max_records} 上限")
    return document, {
        "valid": True,
        "version": document.version,
        "summary": summary,
        "warnings": ["JSON 不包含照片和视频文件本体", "导入会撤销现有相册分享链接"],
    }


def _deep_merge(base: dict, override: dict) -> dict:
    result = copy.deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def _kwargs(item: BaseModel) -> dict:
    return item.model_dump(exclude_none=True)


def _replace_data(db, document: ImportDocument) -> None:
    baby = db.get(models.Baby, 1) or models.Baby(id=1)
    for field, value in _kwargs(document.baby).items():
        setattr(baby, field, value)
    db.add(baby)

    setting = db.get(models.Setting, 1) or models.Setting(id=1, data={})
    setting.data = secret_store.protect_settings_data(_deep_merge(DEFAULT_SETTINGS, document.settings))
    db.add(setting)
    flag_modified(setting, "data")

    db.query(models.Photo).delete(synchronize_session=False)
    db.query(models.Share).delete(synchronize_session=False)
    db.query(models.Album).delete(synchronize_session=False)
    resources = {
        "milestones": models.Milestone,
        "growth": models.Growth,
        "daily": models.Daily,
        "diary": models.Diary,
        "videos": models.Video,
        "messages": models.Message,
        "recaps": models.Recap,
        "vaccines": models.Vaccine,
    }
    for key, model in resources.items():
        db.query(model).delete(synchronize_session=False)
        for item in getattr(document, key):
            db.add(model(**_kwargs(item)))

    for album_data in document.albums:
        values = _kwargs(album_data)
        photos = values.pop("photos", [])
        album = models.Album(**values)
        for index, photo_data in enumerate(photos):
            photo_data["sort"] = index
            album.photos.append(models.Photo(**photo_data))
        db.add(album)
    db.flush()


def apply_import(
    db,
    payload,
    database_path,
    upload_dir,
    backup_dir,
    retention: int = 2,
    max_records: int = 50000,
):
    document, validation = validate_import_payload(payload, max_records=max_records)
    backup_info = backup.create_backup("pre-import", database_path, upload_dir, backup_dir, retention)
    try:
        _replace_data(db, document)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return {**validation, "backupId": backup_info["backupId"]}
