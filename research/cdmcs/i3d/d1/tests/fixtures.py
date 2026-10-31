"""Explicit fictional choices and test coefficients, never production defaults."""

from research.cdmcs.i3a.fixtures import basic
from research.cdmcs.i3a.snapshot import parse_snapshot
from research.cdmcs.i3d.d1.compiler import compile_preferences


def preference(owner="organizer", **changes):
    value = {"preference_version": 1, "synthetic": True, "owner": owner, "revision": 1,
             "state": "configured", "timezone": "Europe/Istanbul",
             "effective": {"from": "2029-01-01", "until": "2031-12-31"},
             "preferred_weekdays": [], "preferred_windows": [], "desired_gap_minutes": 15,
             "provenance": {"source": "synthetic-owner-choice", "fixture_id": "fictional-D1"}}
    value.update(changes)
    return value


def policy(**changes):
    value = {"policy_version": 1, "synthetic": True, "id": "synthetic-coefficients", "revision": 1,
             "rate_model": "weekday_window_tiers_v1", "preferred_rate": 1,
             "outside_window_rate": 2, "outside_day_rate": 4, "gap_weight": 1,
             "nearby_limit": 120, "exception_fee": 0, "move_fixed_cost": 0,
             "move_participant_cost": 0, "delay_per_day": 0,
             "provenance": {"source": "synthetic-test-coefficients", "fixture_id": "fictional-D1"}}
    value.update(changes)
    return value


def calendar():
    return basic()


def context(value=None, **changes):
    value = value or basic()
    result = {"context_version": 1, "synthetic": True, "state": "complete",
              "coverage": {"start": value["utc_anchor"], "end": value["horizon"]["end"]},
              "complete_for": sorted(p["id"] for p in value["participants"] if p["required"]),
              "left_boundary": "calendar_start", "right_boundary": "calendar_end",
              "commitments": list(value["commitments"]),
              "provenance": {"source": "synthetic-complete-calendar", "fixture_id": "fictional-D1"}}
    result.update(changes)
    return result


def compile_case(value=None, specs=None, weights=None, facts=None):
    value = value or calendar()
    specs = specs if specs is not None else [preference(p['id'], timezone=value['timezone'])
                                           for p in value['participants'] if p['required']]
    return compile_preferences(parse_snapshot(value), specs, policy() if weights is None else weights,
                               context(value) if facts is None else facts)
