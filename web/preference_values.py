"""Pure preference values shared by private persistence and synthetic research.

This module has no identity, provenance, calendar, database or optimizer access.
Parsing values does not authorize their storage, export or execution.
"""

from dataclasses import dataclass
from datetime import date
import json
import math
import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class PreferenceError(ValueError):
    def __init__(self, code="INVALID_CONTRACT"):
        self.code = code
        super().__init__("Preference input rejected: " + code)


class PreferenceUnavailable(PreferenceError):
    """Missing or unsupported information is never an implicit zero preference."""


def check(condition, code="INVALID_CONTRACT"):
    if not condition:
        raise PreferenceError(code)


def record(value, fields):
    check(type(value) is dict)
    check(not set(value) - set(fields), "UNKNOWN_FIELD")
    check(not set(fields) - set(value), "MISSING_FIELD")
    return value


def number(value, maximum, minimum=0):
    check(type(value) is int and minimum <= value <= maximum, "INVALID_INTEGER")
    return value


def label(value):
    try:
        check(type(value) is str and 0 < len(value.encode("utf-8")) <= 256, "INVALID_IDENTIFIER")
    except UnicodeError:
        raise PreferenceError("INVALID_IDENTIFIER") from None
    return value


def day(value):
    check(type(value) is str and re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value), "INVALID_DATE")
    try:
        result = date.fromisoformat(value)
        check(date(1970, 1, 1) <= result < date(2100, 1, 1), "INVALID_DATE")
        return result
    except ValueError:
        raise PreferenceError("INVALID_DATE") from None


def zone(value):
    label(value)
    try:
        ZoneInfo(value)
    except (ValueError, ZoneInfoNotFoundError):
        raise PreferenceError("INVALID_TIMEZONE") from None
    return value


def clock(value, *, end=False):
    check(type(value) is str and re.fullmatch(r"[0-9]{2}:[0-9]{2}", value), "INVALID_CLOCK")
    hour, minute = map(int, value.split(":"))
    check((0 <= hour < 24 and 0 <= minute < 60) or (end and hour == 24 and minute == 0), "INVALID_CLOCK")
    return hour * 60 + minute


@dataclass(frozen=True, repr=False)
class PreferenceValues:
    timezone: str
    first: date
    last: date
    weekdays: tuple
    windows: tuple
    source_windows: tuple
    desired_gap: int | str
    original_windows: tuple

    def __repr__(self):
        return "PreferenceValues(private=True)"

    def document(self):
        return {"timezone": self.timezone,
                "effective": {"from": self.first.isoformat(), "until": self.last.isoformat()},
                "preferred_weekdays": list(self.weekdays),
                "preferred_windows": [{"weekday": d, "start": a, "end": b}
                                      for d, a, b in self.original_windows],
                "desired_gap_minutes": self.desired_gap}


VALUE_FIELDS = ("timezone", "effective", "preferred_weekdays", "preferred_windows", "desired_gap_minutes")


def parse_values(value):
    record(value, VALUE_FIELDS)
    check(all(value[k] is not None for k in VALUE_FIELDS), "MISSING_VALUE")
    timezone = zone(value["timezone"])
    effective = record(value["effective"], ("from", "until"))
    first, last = day(effective["from"]), day(effective["until"])
    check(first <= last, "INVALID_DATE_RANGE")
    weekdays = value["preferred_weekdays"]
    check(type(weekdays) is list and len(weekdays) <= 7, "INVALID_WEEKDAYS")
    weekdays = tuple(sorted(number(item, 7, 1) for item in weekdays))
    check(len(set(weekdays)) == len(weekdays), "DUPLICATE_WEEKDAY")
    windows = value["preferred_windows"]
    check(type(windows) is list and len(windows) <= 64, "WINDOW_BUDGET")
    segments, source_windows, originals = [], [], []
    for item in windows:
        record(item, ("weekday", "start", "end"))
        weekday = number(item["weekday"], 7, 1)
        start, end = clock(item["start"]), clock(item["end"], end=True)
        check(start != end, "EMPTY_WINDOW")
        originals.append((weekday, item["start"], item["end"]))
        source_windows.append((weekday, start, end if end > start else end + 1440))
        segments.append((weekday, start, end if end > start else 1440))
        if end < start and end:
            segments.append((weekday % 7 + 1, 0, end))
    segments.sort()
    merged = []
    for weekday, start, end in segments:
        check(not weekdays or weekday in weekdays, "WEEKDAY_WINDOW_CONFLICT")
        if merged and merged[-1][0] == weekday:
            check(start >= merged[-1][2], "OVERLAPPING_WINDOWS")
            if start == merged[-1][2]:
                merged[-1] = (weekday, merged[-1][1], end)
                continue
        merged.append((weekday, start, end))
    gap = value["desired_gap_minutes"]
    if gap != "indifferent":
        gap = number(gap, 1440)
    return PreferenceValues(timezone, first, last, weekdays, tuple(merged),
                            tuple(sorted(source_windows)), gap, tuple(sorted(originals)))


def load_document(raw):
    """Bounded UTF-8 object; reject duplicate keys, nonfinite numbers and recursion."""
    check(type(raw) is bytes and len(raw) <= 4 * 1024**2, "DOCUMENT_BUDGET")

    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError()
            result[key] = value
        return result

    def constant(_):
        raise ValueError()

    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs, parse_constant=constant)
        check(type(value) is dict)
        pending = [(value, 0)]
        while pending:
            item, depth = pending.pop()
            check(depth <= 32, "INVALID_JSON")
            if type(item) is dict:
                pending.extend((child, depth + 1) for child in item.values())
            elif type(item) is list:
                pending.extend((child, depth + 1) for child in item)
            elif type(item) is float:
                check(math.isfinite(item), "INVALID_JSON")
        return value
    except (ValueError, UnicodeError, RecursionError):
        raise PreferenceError("INVALID_JSON") from None
