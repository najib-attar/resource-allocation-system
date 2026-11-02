"""Pure numerical values, not institutional authorization or scheduling execution."""

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json

from .preference_values import (PreferenceError, PreferenceUnavailable, check, label,
                                load_document, number, record, zone)


COEFFICIENT_FIELDS = ('preferred_rate', 'outside_window_rate', 'outside_day_rate',
    'gap_weight', 'nearby_limit', 'exception_fee', 'move_fixed_cost',
    'move_participant_cost', 'delay_per_day')
OPERATION = 'cdmcs_schedule_v1'
OBJECTIVE = 'V15_restricted_one_blocking_move'
RATE_MODEL = 'weekday_window_tiers_v1'
PREFIX_TOTAL_LIMIT = 10**12
# Triangle bound: 3 event costs, 9 gaps, two exception fees and one move fee/person.
ENGINE_SCORE_BOUND = 256 * (3 * PREFIX_TOTAL_LIMIT + 9 * 10080 * 100000 + 3 * 10**7) + 10**7 + (2**32 - 1) * 10**7


@dataclass(frozen=True)
class CostCoefficients:
    preferred_rate: int
    outside_window_rate: int
    outside_day_rate: int
    gap_weight: int
    nearby_limit: int
    exception_fee: int
    move_fixed_cost: int
    move_participant_cost: int
    delay_per_day: int

    def document(self):
        return {key: getattr(self, key) for key in COEFFICIENT_FIELDS}


def parse_coefficients(value):
    record(value, COEFFICIENT_FIELDS)
    rates = tuple(number(value[key], 10**8) for key in COEFFICIENT_FIELDS[:3])
    check(rates[0] <= rates[1] <= rates[2], 'CONFLICTING_RATES')
    return CostCoefficients(*rates, number(value['gap_weight'], 100000),
        number(value['nearby_limit'], 10080),
        *(number(value[key], 10**7) for key in COEFFICIENT_FIELDS[5:]))


def _text(value):
    label(value)
    check(bool(value.strip()) and not any(ord(c) < 32 or ord(c) == 127 for c in value), 'INVALID_TEXT')
    return value


def _instant(value):
    _text(value)
    try:
        result = datetime.fromisoformat(value)
        check(result.tzinfo is not None and result.utcoffset() is not None, 'INVALID_EFFECTIVE_INTERVAL')
        result = result.astimezone(timezone.utc)
        check(datetime(1970, 1, 1, tzinfo=timezone.utc) <= result < datetime(2100, 1, 1, tzinfo=timezone.utc),
              'INVALID_EFFECTIVE_INTERVAL')
        return result
    except (ValueError, OverflowError):
        raise PreferenceError('INVALID_EFFECTIVE_INTERVAL') from None


def _microseconds(value):
    delta = value - datetime(1970, 1, 1, tzinfo=timezone.utc)
    return (delta.days * 86400 + delta.seconds) * 1000000 + delta.microseconds


@dataclass(frozen=True, repr=False)
class InstitutionalCostPolicy:
    revision: int
    timezone: str
    effective_from: datetime
    effective_until: datetime
    cost_unit: str
    calibration_ref: str
    provenance_ref: str
    coefficients: CostCoefficients

    def __repr__(self):
        return 'InstitutionalCostPolicy(origin=institutional_policy; contents withheld)'

    def document(self):
        return {'policy_contract_version': 1, 'origin': 'institutional_policy', 'policy_id': 'university',
            'revision': self.revision, 'objective_version': 1, 'engine_operation': OPERATION,
            'objective_model': OBJECTIVE, 'rate_model': RATE_MODEL, 'timezone': self.timezone,
            'effective': {'from': self.effective_from.isoformat(), 'until': self.effective_until.isoformat()},
            'cost_unit': self.cost_unit, 'calibration_ref': self.calibration_ref,
            'provenance': {'type': 'institutional_policy', 'source_ref': self.provenance_ref},
            'coefficients': self.coefficients.document()}

    def canonical_bytes(self):
        # A fixed scalar array avoids object-key order and floating epoch arithmetic.
        # PostgreSQL jsonb's scalar-array text uses these same separators/UTF-8.
        items = [1, 'institutional_policy', 'university', self.revision, 1, OPERATION,
            OBJECTIVE, RATE_MODEL, self.timezone, _microseconds(self.effective_from),
            _microseconds(self.effective_until), self.cost_unit, self.calibration_ref,
            'institutional_policy', self.provenance_ref,
            *(getattr(self.coefficients, key) for key in COEFFICIENT_FIELDS)]
        return json.dumps(items, ensure_ascii=False, separators=(', ', ': '), allow_nan=False).encode('utf-8')

    @property
    def content_digest(self):
        return hashlib.sha256(self.canonical_bytes()).hexdigest()


def parse_institutional_policy(value, *, university_timezone, expected_digest=None):
    """Validate explicit values only. A valid digest conveys no actor authority."""
    if type(value) is bytes:
        value = load_document(value)
    record(value, ('policy_contract_version', 'origin', 'policy_id', 'revision', 'objective_version',
        'engine_operation', 'objective_model', 'rate_model', 'timezone', 'effective', 'cost_unit',
        'calibration_ref', 'provenance', 'coefficients'))
    for key in ('policy_contract_version', 'objective_version'):
        number(value[key], 2**31 - 1, 1)
        if value[key] != 1:
            raise PreferenceUnavailable('UNSUPPORTED_VERSION')
    check(value['origin'] == 'institutional_policy' and value['policy_id'] == 'university', 'INVALID_POLICY_ORIGIN')
    check(value['engine_operation'] == OPERATION and value['objective_model'] == OBJECTIVE
          and value['rate_model'] == RATE_MODEL, 'UNSUPPORTED_COST_MODEL')
    configured = zone(university_timezone)
    check(zone(value['timezone']) == configured, 'POLICY_TIMEZONE_MISMATCH')
    effective = record(value['effective'], ('from', 'until'))
    first, last = _instant(effective['from']), _instant(effective['until'])
    check(first < last, 'INVALID_EFFECTIVE_INTERVAL')
    provenance = record(value['provenance'], ('type', 'source_ref'))
    check(provenance['type'] == 'institutional_policy', 'INVALID_POLICY_PROVENANCE')
    policy = InstitutionalCostPolicy(number(value['revision'], 2**63 - 1, 1), configured, first, last,
        _text(value['cost_unit']), _text(value['calibration_ref']), _text(provenance['source_ref']),
        parse_coefficients(value['coefficients']))
    if expected_digest is not None:
        check(type(expected_digest) is str and expected_digest == policy.content_digest, 'POLICY_DIGEST_MISMATCH')
    return policy
