"""Serialize dated events for calendar applications."""

from datetime import timezone
from uuid import NAMESPACE_URL, uuid5


def ics_timestamp(value):
    return value.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _text_line(name, value):
    escaped = (value.replace("\\", "\\\\").replace("\r\n", "\n").replace("\r", "\n")
               .replace("\n", "\\n").replace(",", "\\,").replace(";", "\\;"))
    line = bytearray(f"{name}:".encode("ascii"))
    lines = []
    for char in escaped:
        if ord(char) < 32 or ord(char) == 127:
            continue
        encoded = char.encode("utf-8")
        if len(line) + len(encoded) > 75:
            lines.append(bytes(line))
            line = bytearray(b" ")
        line.extend(encoded)
    lines.append(bytes(line))
    return b"\r\n".join(lines)


def course_calendar(schedule):
    week = schedule["week"]
    lines = [b"BEGIN:VCALENDAR", b"VERSION:2.0", b"PRODID:-//Campus Space//Course Timetable//EN"]
    stamp = ics_timestamp(week["now"])
    for day in week["dates"]:
        for entry in schedule["classes"].get(day, ()):
            identity = f"urn:campus-space:course-session:{entry['session_id']}:{entry['crn']}:{day.isoformat()}"
            uid = uuid5(NAMESPACE_URL, identity)
            lines.extend([
                b"BEGIN:VEVENT", f"UID:{uid}".encode("ascii"), f"DTSTAMP:{stamp}".encode("ascii"),
                f"DTSTART:{ics_timestamp(entry['start'])}".encode("ascii"),
                f"DTEND:{ics_timestamp(entry['end'])}".encode("ascii"),
                b"CLASS:PRIVATE", b"STATUS:CONFIRMED",
                _text_line("SUMMARY", f"{entry['course'].code} · {entry['title']} (CRN {entry['crn']})"),
            ])
            if entry["calendar_location"]:
                lines.append(_text_line("LOCATION", entry["calendar_location"]))
            lines.append(b"END:VEVENT")
    lines.extend([b"END:VCALENDAR", b""])
    return b"\r\n".join(lines)
