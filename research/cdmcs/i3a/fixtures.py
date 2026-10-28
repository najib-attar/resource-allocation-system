"""Deterministic fictional inputs; no application data or current-time defaults."""

import json
from datetime import datetime, timedelta


def stamp(minutes=0, anchor="2030-01-07T06:00:00+00:00"):
    return (datetime.fromisoformat(anchor) + timedelta(minutes=minutes)).isoformat()


def period(start=0, end=180, anchor="2030-01-07T06:00:00+00:00"):
    return {"start": stamp(start, anchor), "end": stamp(end, anchor)}


def participant(name, *, required=True, published_required=True, role="professor", end=180):
    return {"id": name, "required": required, "published_required": published_required,
            "calendar_state": "known", "published": [period(0, end)] if published_required else [],
            "preference": {}, "role_label": role}


def commitment(name, people, start, end, resources=()):
    return {"id": name, "people": list(people), "resources": list(resources),
            "interval": period(start, end), "protected": True}


def basic():
    return {"snapshot_version": 1, "snapshot_id": "synthetic-basic", "synthetic": True,
            "timezone": "Europe/Istanbul", "utc_anchor": stamp(), "horizon": period(),
            "duration_minutes": 30, "organizer": "organizer",
            "participants": [participant("organizer", published_required=False, role="student"),
                             participant("professor-A")], "commitments": [], "required_resources": [],
            "candidates": {"mode": "production_grid", "anchor_participant": "professor-A", "step_minutes": 15},
            "provenance": {"source": "I3a fictional fixture", "calendar": "Explicit 7 January 2030; no legacy expansion"}}


def rebase(value, anchor):
    """Shift this module's explicitly dated fictional fixtures, never real records."""
    if isinstance(value, dict):
        return {key: rebase(item, anchor) for key, item in value.items()}
    if isinstance(value, list):
        return [rebase(item, anchor) for item in value]
    if isinstance(value, str) and value.startswith("2030-01-07T"):
        delta = datetime.fromisoformat(value) - datetime.fromisoformat(stamp())
        return (datetime.fromisoformat(anchor) + delta).isoformat()
    return value


def matrix():
    cases = []

    def add(name, value):
        value["snapshot_id"] = "synthetic-" + name
        cases.append(value)

    add("one-professor", basic())
    value = basic()
    second = participant("professor-B")
    second["published"] = [period(30, 150)]
    value["participants"].append(second)
    value["commitments"] = [commitment("class-A", ["professor-A"], 60, 90),
                            commitment("class-B", ["professor-B"], 120, 135)]
    add("multiple-professors", value)
    for role in ("student", "professor", "administrator", "committee organizer"):
        value = basic()
        value["participants"][0]["role_label"] = role
        add("organizer-" + role.replace(" ", "-"), value)
    value = basic()
    value["participants"].append(participant("optional-student", required=False, published_required=False, role="student"))
    value["commitments"] = [commitment("optional-class", ["optional-student"], 0, 60)]
    value["preferred_start"] = stamp(0)
    value["participants"][1]["preference"] = {"base_rate": 1, "rate_bands": [{"interval": period(0, 30), "rate": 0}],
                                               "source": "fictional early-time preference"}
    add("optional-unavailable-ranking-difference", value)
    value = basic()
    value["horizon"] = period(10, 180)
    value["participants"][1]["published"] = [period(7, 67), period(67, 187)]
    add("touching-windows-offset-grid", value)
    value = basic()
    value["commitments"] = [commitment("first", ["professor-A"], 0, 30)]
    add("adjacent-commitment", value)
    value = basic()
    value["commitments"] = [commitment("overlap-1", ["organizer", "professor-A"], 15, 45),
                            commitment("overlap-2", ["organizer", "professor-A"], 30, 60)]
    add("overlapping-protected-calendars", value)
    value = basic()
    value["candidates"] = {"mode": "explicit", "anchor_participant": "professor-A",
                           "starts": [stamp(t) for t in (1, 16, 31, 150)]}
    value["commitments"] = [commitment("manual-conflict", ["professor-A"], 31, 61)]
    add("manual-off-grid", value)
    value = basic()
    value["duration_minutes"] = 60
    add("cross-midnight", rebase(value, "2030-01-07T20:30:00+00:00"))
    value = basic()
    value["horizon"] = period(0, 2880)
    value["participants"][1]["published"] = [period(0, 2880)]
    add("over-100-feasible-weekday-boundary", value)
    for name, anchor in (("dst-spring", "2026-03-28T23:00:00+00:00"), ("dst-fall", "2026-10-24T22:00:00+00:00")):
        value = basic()
        value["timezone"] = "Europe/Berlin"
        value["horizon"] = period(0, 360)
        value["participants"][1]["published"] = [period(0, 360)]
        value["duration_minutes"] = 60
        add(name, rebase(value, anchor))
    for state in ("missing", "unresolved"):
        value = basic()
        value["participants"][1]["calendar_state"] = state
        add("mandatory-" + state, value)
    value = basic()
    optional = participant("optional-unknown", required=False, published_required=False)
    optional["calendar_state"] = "unresolved"
    value["participants"].append(optional)
    add("optional-unresolved", value)
    value = basic()
    value["required_resources"] = ["room-synthetic"]
    add("exclusive-resource-unsupported", value)
    value = basic()
    value["unsupported_information"] = ["Projector compatibility is outside the appointment contract"]
    add("capability-unsupported", value)
    value = basic()
    value["commitments"] = [commitment("fully-busy", ["professor-A"], 0, 180)]
    add("empty-feasible-set", value)
    value = basic()
    value["horizon"] = period(0, 30)
    value["commitments"] = [commitment("adjacent-after-horizon", ["professor-A"], 30, 60)]
    add("exact-end-boundary", value)
    value = basic()
    value["participants"][1]["published"] = []
    add("empty-candidate-grid", value)
    for name, local in (("invalid-dst-gap", "2026-03-29T02:30"), ("invalid-dst-fold", "2026-10-25T02:30")):
        value = basic()
        value["timezone"] = "Europe/Berlin"
        value["horizon"]["start"] = local
        add(name, value)
    value = basic()
    value["duration_minutes"] = True
    add("invalid-numeric", value)
    value = basic()
    value["participants"][1]["published"] *= 1025
    add("excessive-windows", value)
    value = basic()
    value["timezone"] = "America/St_Johns"
    add("backward-civil-date-unsupported", rebase(value, "2010-11-07T01:00:00+00:00"))
    for duration in (1, 2):
        for start in range(4):
            for end in range(start + 1, 5):
                value = basic()
                value["horizon"] = period(0, 4)
                value["duration_minutes"] = duration
                value["commitments"] = [commitment("protected", ["professor-A"], start, end)]
                value["candidates"] = {"mode": "explicit", "anchor_participant": "professor-A",
                                       "starts": [stamp(t) for t in range(5 - duration)]}
                expected = [t for t in range(5 - duration) if t + duration <= start or t >= end]
                value["provenance"]["independent_expected_offsets"] = json.dumps(expected)
                add(f"exhaustive-d{duration}-busy{start}-{end}", value)
    return cases


def expected_status(value):
    name = value["snapshot_id"]
    if "-invalid-" in name or name.endswith("excessive-windows"):
        return "input_engine_error"
    if name.endswith(("mandatory-missing", "mandatory-unresolved", "exclusive-resource-unsupported",
                      "capability-unsupported", "backward-civil-date-unsupported")):
        return "unsupported_comparison"
    return "equal"
