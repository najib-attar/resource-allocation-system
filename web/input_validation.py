"""Parse numeric and weekly slot form/import values; no persistence operations."""

from .engine_gateway import EngineIntegrationError


def integer(value, label, minimum=0):
    if isinstance(value, bool):
        raise EngineIntegrationError(f"Invalid {label}")
    try:
        number = int(value)
    except (TypeError, ValueError) as error:
        raise EngineIntegrationError(f"Invalid {label}") from error
    if (not str(value).strip().isdigit() or not minimum <= number <= 2147483647):
        raise EngineIntegrationError(f"Invalid {label}")
    return number


def minutes(value):
    parts = str(value).split(":")
    if len(parts) not in (1, 2):
        raise EngineIntegrationError("Invalid time")
    hour = integer(parts[0], "hour")
    minute = integer(parts[1], "minute") if len(parts) == 2 else 0
    if hour > 24 or minute > 59 or (hour == 24 and minute):
        raise EngineIntegrationError("Invalid time")
    return hour * 60 + minute


def parse_time_slots(value):
    result = []
    for occurrence in value.split(";"):
        parts = occurrence.strip().split("-")
        if len(parts) != 3:
            raise EngineIntegrationError("Invalid persisted request timeData")
        day, start, end = integer(parts[0], "day"), minutes(parts[1]), minutes(parts[2])
        if not 1 <= day <= 7 or not 0 <= start < end <= 1440:
            raise EngineIntegrationError("Invalid persisted time range")
        result.append({"day": day, "startMinutes": start, "endMinutes": end})
    return result
