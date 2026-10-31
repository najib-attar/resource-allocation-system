"""Synthetic test admission, not a new calendar authorization policy."""

from dataclasses import dataclass, field, replace

from research.cdmcs.i3a.snapshot import Interval, Preference, Snapshot, parse_snapshot
from research.cdmcs.i3b.projection import CalendarProjection


class AdmissionError(ValueError):
    def __init__(self):
        super().__init__("Synthetic shadow input or execution scope is invalid.")


_SEAL = object()


@dataclass(frozen=True, repr=False)
class ShadowInput:
    _snapshot: Snapshot = field(repr=False)
    _bound: Snapshot = field(repr=False)
    _seal: object = field(repr=False)

    def __repr__(self):
        return "ShadowInput(synthetic_test_only=True; calendar withheld)"


def _admit(snapshot):
    return ShadowInput(snapshot, snapshot, _SEAL)


def synthetic_fixture(value):
    """Parse explicitly synthetic JSON facts with the existing strict I3a parser."""
    try:
        return _admit(parse_snapshot(value))
    except (ValueError, TypeError, KeyError, OverflowError, RecursionError):
        raise AdmissionError() from None


def synthetic_projection(projection, *, disposable_fixture=False, preferences=()):
    """Trusted test harness only: the caller must OWN the synthetic database fixture.

    This declaration is not a mechanism for authorizing real calendars. Missing
    preferences remain None. Explicit test preferences never become user policy.
    The database origin and exact horizon/candidate scope are retained unchanged.
    """
    if disposable_fixture is not True or type(projection) is not CalendarProjection:
        raise AdmissionError()
    snapshot = projection.internal_snapshot()
    if (type(snapshot) is not Snapshot or snapshot.origin != "authorized_calendar"
            or not isinstance(preferences, tuple)):
        raise AdmissionError()
    try:
        prepared = dict(preferences)
        if len(prepared) != len(preferences) or not set(prepared) <= {p.id for p in snapshot.participants}:
            raise ValueError()
        for pref in prepared.values():
            if (type(pref) is not Preference or not isinstance(pref.source, str)
                    or not pref.source.startswith("synthetic-") or len(pref.source) > 256):
                raise ValueError()
            values = ((pref.base_rate, 10**8), (pref.preferred_break, 1440),
                      (pref.gap_weight, 100000), (pref.nearby_limit, 10080))
            if any(type(v) is not int or not 0 <= v <= bound for v, bound in values) or not isinstance(pref.bands, tuple):
                raise ValueError()
            if len(pref.bands) > 1024:
                raise ValueError()
            end = snapshot.anchor
            for band in pref.bands:
                if type(band) is not tuple or len(band) != 2:
                    raise ValueError()
                window, rate = band
                if (type(window) is not Interval or type(window.start) is not int or type(window.end) is not int
                        or not end <= window.start < window.end <= snapshot.horizon.end
                        or window.start % 60 or window.end % 60
                        or type(rate) is not int or not 0 <= rate <= 10**8):
                    raise ValueError()
                end = window.end
        return _admit(replace(snapshot, participants=tuple(
            replace(p, preference=prepared.get(p.id, p.preference)) for p in snapshot.participants),
            provenance=(*snapshot.provenance, ("shadow_test_scope", "disposable synthetic fixture only"),
                        ("shadow_preferences", "explicit synthetic fixture" if prepared else "unavailable"))))
    except (ValueError, TypeError, AttributeError):
        raise AdmissionError() from None


def admitted_snapshot(value):
    if (type(value) is not ShadowInput or value._seal is not _SEAL
            or value._snapshot is not value._bound
            or type(value._snapshot) is not Snapshot
            or value._snapshot.origin not in {"synthetic", "authorized_calendar"}):
        raise AdmissionError()
    return value._snapshot
