"""Validated synthetic intent and separate cost coefficients, with no defaults."""

from dataclasses import dataclass
from datetime import date

from web.preference_values import (PreferenceError, PreferenceUnavailable, VALUE_FIELDS,
                                   check, clock, day, label, load_document, number,
                                   parse_values, record, zone)


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
    source_windows: tuple
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
        return PreferenceSpec(owner, revision, state, timezone, None, None, (), (), (), None, source)
    parsed = parse_values({key: value[key] for key in VALUE_FIELDS})
    return PreferenceSpec(owner, revision, state, timezone, parsed.first, parsed.last, parsed.weekdays,
                          parsed.windows, parsed.source_windows, parsed.desired_gap, source)


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


