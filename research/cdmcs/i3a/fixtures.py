"""Deterministic fictional inputs; no application data or current-time defaults."""

from datetime import datetime, timedelta, timezone


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
