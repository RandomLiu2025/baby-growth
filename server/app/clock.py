from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .config import settings


def business_timezone() -> ZoneInfo:
    try:
        return ZoneInfo(settings.APP_TIMEZONE)
    except (ZoneInfoNotFoundError, ValueError, TypeError) as exc:
        raise RuntimeError(f"无效的 APP_TIMEZONE：{settings.APP_TIMEZONE}") from exc


def validate_timezone() -> None:
    business_timezone()


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def as_utc(now: datetime | None = None) -> datetime:
    current = now or utc_now()
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc)


def local_now(now: datetime | None = None) -> datetime:
    return as_utc(now).astimezone(business_timezone())


def local_today(now: datetime | None = None) -> date:
    return local_now(now).date()


def business_time_context(now: datetime | None = None) -> dict[str, str]:
    current = as_utc(now)
    return {
        "timeZone": settings.APP_TIMEZONE,
        "now": current.isoformat(),
        "today": local_today(current).isoformat(),
    }


def local_date_utc_bounds(value: date) -> tuple[datetime, datetime]:
    zone = business_timezone()
    local_start = datetime.combine(value, time.min, tzinfo=zone)
    local_end = local_start + timedelta(days=1)
    return local_start.astimezone(timezone.utc), local_end.astimezone(timezone.utc)


def local_day_utc_bounds(now: datetime | None = None) -> tuple[datetime, datetime]:
    return local_date_utc_bounds(local_today(now))


def local_period(now: datetime | None, days: int) -> tuple[date, date, datetime, datetime]:
    end_date = local_today(now)
    start_date = end_date - timedelta(days=max(1, days) - 1)
    start_utc, _ = local_date_utc_bounds(start_date)
    _, end_utc = local_date_utc_bounds(end_date)
    return start_date, end_date, start_utc, end_utc
