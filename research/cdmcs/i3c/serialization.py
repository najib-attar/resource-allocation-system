"""Trusted internal codec entry point; never part of I3a's synthetic exporter."""

from research.cdmcs.i3a.adapter import _serialize_cdmcs, _serialize_production
from .admission import admitted_snapshot


def candidate_requests(scope, normalized, candidate, compare):
    if (admitted_snapshot(scope) is not normalized.snapshot or normalized.unsupported
            or type(candidate) is not int or candidate not in normalized.candidates):
        raise ValueError("Invalid internal fixed-calendar execution scope")
    # The codecs share mechanics, not admission policy. The origin is NOT relabeled.
    result = [("cdmcs", [], _serialize_cdmcs(normalized, (candidate,)))]
    if compare:
        result.append(("production", ["--appointments-json"], _serialize_production(normalized, candidate)))
    return result
