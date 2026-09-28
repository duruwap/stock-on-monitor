"""거래 시간 판정.

tzdata 의존성을 피하기 위해 시간대를 직접 계산한다.
- 한국: UTC+9 고정 (서머타임 없음)
- 미국 동부: 3월 둘째 일요일 02:00 ~ 11월 첫째 일요일 02:00 서머타임(UTC-4), 그 외 UTC-5
공휴일은 반영하지 않는다. 대신 시세원이 알려주는 장 상태(session)가 있으면 그것을 우선한다.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

KST = timezone(timedelta(hours=9), "KST")


def _nth_sunday(year: int, month: int, n: int) -> date:
    d = date(year, month, 1)
    d += timedelta(days=(6 - d.weekday()) % 7)
    return d + timedelta(weeks=n - 1)


def us_eastern_offset(now_utc: datetime) -> timedelta:
    y = now_utc.year
    # 서머타임 전환 시각(UTC): 시작 = 현지 02:00 EST(UTC 07:00), 종료 = 현지 02:00 EDT(UTC 06:00)
    start = datetime.combine(_nth_sunday(y, 3, 2), time(7), tzinfo=timezone.utc)
    end = datetime.combine(_nth_sunday(y, 11, 1), time(6), tzinfo=timezone.utc)
    return timedelta(hours=-4) if start <= now_utc < end else timedelta(hours=-5)


def to_eastern(now_utc: datetime) -> datetime:
    return now_utc.astimezone(timezone(us_eastern_offset(now_utc)))


def _within(local: datetime, start: time, end: time) -> bool:
    return local.weekday() < 5 and start <= local.time() < end


def is_regular_session(market: str, now_utc: datetime | None = None) -> bool:
    now_utc = now_utc or datetime.now(timezone.utc)
    if market == "KR":
        return _within(now_utc.astimezone(KST), time(9, 0), time(15, 30))
    return _within(to_eastern(now_utc), time(9, 30), time(16, 0))


def is_active_window(market: str, now_utc: datetime | None = None) -> bool:
    """시세가 바뀔 수 있는 넓은 시간대 (장전·장후 거래 포함). 이 시간 밖에서는 조회 빈도를 낮춘다."""
    now_utc = now_utc or datetime.now(timezone.utc)
    if market == "KR":
        # 대체거래소(NXT) 프리·애프터마켓 포함 08:00~20:00
        return _within(now_utc.astimezone(KST), time(8, 0), time(20, 0))
    return _within(to_eastern(now_utc), time(4, 0), time(20, 0))
