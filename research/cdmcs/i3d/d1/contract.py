"""Validated synthetic intent and separate cost coefficients, with no defaults."""

from dataclasses import dataclass
from datetime import date
import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from research.cdmcs.i3a.execution import strict_json


class PreferenceError(ValueError):
    def __init__(self, code="INVALID_CONTRACT"):
        self.code = code
        super().__init__("Synthetic preference input rejected: " + code)


class PreferenceUnavailable(PreferenceError):
    """Known absence/unsupported context, not a zero-cost preference or infeasibility."""


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


def provenance(value):
    record(value, ("source", "fixture_id"))
    check(label(value["source"]).startswith("synthetic-"), "SYNTHETIC_PROVENANCE_REQUIRED")
    return (value["source"], label(value["fixture_id"]))


def envelope(value, fields, version_field):
    record(value, fields)
    check(value["synthetic"] is True, "SYNTHETIC_ONLY")
    number(value[version_field], 2**31 - 1, 1)
    if value[version_field] != 1:
        raise PreferenceUnavailable("UNSUPPORTED_VERSION")


def clock(value, *, end=False):
    check(type(value) is str and re.fullmatch(r"[0-9]{2}:[0-9]{2}", value), "INVALID_CLOCK")
    hour, minute = map(int, value.split(":"))
    check((0 <= hour < 24 and 0 <= minute < 60) or (end and hour == 24 and minute == 0), "INVALID_CLOCK")
    return hour * 60 + minute


@dataclass(frozen=True, repr=False)
class PreferenceSpec:
    owner: str
    revision: int
    state: str
    timezone: str
    first: date | None
    last: date | None
    weekdays: tuple
    windows: tuple
    desired_gap: int | str | None
    provenance: tuple

    def __repr__(self):
        return "PreferenceSpec(synthetic_only=True; preference withheld)"


@dataclass(frozen=True, repr=False)
class CostPolicy:
    identifier: str
    revision: int
    preferred_rate: int
    outside_window_rate: int
    outside_day_rate: int
    gap_weight: int
    nearby_limit: int
    exception_fee: int
    move_fixed_cost: int
    move_participant_cost: int
    delay_per_day: int
    provenance: tuple


def parse_preference(value):
    fields = ("preference_version", "synthetic", "owner", "revision", "state", "timezone",
              "effective", "preferred_weekdays", "preferred_windows", "desired_gap_minutes", "provenance")
    envelope(value, fields, "preference_version")
    owner, revision = label(value["owner"]), number(value["revision"], 2**63 - 1, 1)
    timezone, source = zone(value["timezone"]), provenance(value["provenance"])
    state = value["state"]
    check(type(state) is str and state in ("configured", "missing", "unknown", "unsupported"), "INVALID_STATE")
    if state != "configured":
        check(all(value[k] is None for k in ("effective", "preferred_weekdays", "preferred_windows", "desired_gap_minutes")),
              "STATE_VALUE_CONFLICT")
        return PreferenceSpec(owner, revision, state, timezone, None, None, (), (), None, source)
    check(all(value[k] is not None for k in ("effective", "preferred_weekdays", "preferred_windows", "desired_gap_minutes")),
          "MISSING_VALUE")
    effective = record(value["effective"], ("from", "until"))
    first, last = day(effective["from"]), day(effective["until"])
    check(first <= last, "INVALID_DATE_RANGE")
    weekdays = value["preferred_weekdays"]
    check(type(weekdays) is list and len(weekdays) <= 7, "INVALID_WEEKDAYS")
    weekdays = tuple(sorted(number(item, 7, 1) for item in weekdays))
    check(len(set(weekdays)) == len(weekdays), "DUPLICATE_WEEKDAY")
    windows = value["preferred_windows"]
    check(type(windows) is list and len(windows) <= 64, "WINDOW_BUDGET")
    segments = []
    for item in windows:
        record(item, ("weekday", "start", "end"))
        weekday = number(item["weekday"], 7, 1)
        start, end = clock(item["start"]), clock(item["end"], end=True)
        check(start != end, "EMPTY_WINDOW")
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
    return PreferenceSpec(owner, revision, state, timezone, first, last, weekdays, tuple(merged), gap, source)


def parse_policy(value):
    rates = ("preferred_rate", "outside_window_rate", "outside_day_rate")
    fees = ("exception_fee", "move_fixed_cost", "move_participant_cost", "delay_per_day")
    envelope(value, ("policy_version", "synthetic", "id", "revision", "rate_model", *rates,
                     "gap_weight", "nearby_limit", *fees, "provenance"), "policy_version")
    check(value["rate_model"] == "weekday_window_tiers_v1", "UNSUPPORTED_RATE_MODEL")
    parsed_rates = tuple(number(value[key], 10**8) for key in rates)
    check(parsed_rates[0] <= parsed_rates[1] <= parsed_rates[2], "CONFLICTING_RATES")
    return CostPolicy(label(value["id"]), number(value["revision"], 2**63 - 1, 1), *parsed_rates,
                      number(value["gap_weight"], 100000), number(value["nearby_limit"], 10080),
                      *(number(value[key], 10**7) for key in fees), provenance(value["provenance"]))


def load_document(raw):
    """Bounded UTF-8 JSON with duplicate-key/nonfinite rejection, not file I/O."""
    check(type(raw) is bytes and len(raw) <= 4 * 1024**2, "DOCUMENT_BUDGET")
    try:
        value = strict_json(raw.decode("utf-8"))
        check(type(value) is dict)
        return value
    except (ValueError, UnicodeError, RecursionError):
        raise PreferenceError("INVALID_JSON") from None
