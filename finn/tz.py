"""Timezone handling for exchange timestamps.

NSE publishes times as naive India wall-clock strings ("23-Oct-2026 22:50:22"). Verified 2026-10-27: HDFCBANK's
transcript broadcast at 22:50:22 carries a covering letter dated October 23, which only holds if the time is IST
(as UTC it would be 04:20 IST on the 24th), and NSE's own upload stamp in the file name (22:46:57) agrees.
So a naive NSE time gets the Asia/Kolkata zone attached, keeping the wall-clock reading; it is never treated as
UTC and shifted. A value that already has an offset is returned unchanged.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

try:
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
    try:
        IST = ZoneInfo("Asia/Kolkata")
    except ZoneInfoNotFoundError:           # host without a tz database: India has had no DST since 1945,
        IST = timezone(timedelta(hours=5, minutes=30), "IST")   # so the fixed offset is exact
except ImportError:                          # pragma: no cover - Python < 3.9
    IST = timezone(timedelta(hours=5, minutes=30), "IST")


def as_ist(dt: Optional[datetime]) -> Optional[datetime]:
    """Naive -> the same wall-clock time in IST. Aware -> unchanged (no double conversion)."""
    if dt is None or dt.tzinfo is not None and dt.utcoffset() is not None:
        return dt
    return dt.replace(tzinfo=IST)


def parse_nse(s: str, *formats: str) -> Optional[datetime]:
    """Parse an NSE timestamp string in the first matching format, as IST. None if no format matches."""
    s = (s or "").strip()
    for fmt in formats:
        try:
            return as_ist(datetime.strptime(s, fmt))
        except ValueError:
            continue
    return None
