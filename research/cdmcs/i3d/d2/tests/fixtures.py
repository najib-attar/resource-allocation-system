"""Fictional explicit D1 choices; no production defaults or persistent records."""

from research.cdmcs.i3a.fixtures import basic, period, stamp
from research.cdmcs.i3c.admission import synthetic_fixture
from research.cdmcs.i3d.d1.tests.fixtures import context, policy, preference
from research.cdmcs.i3d.d2.planning import prepare


def fixture(count=8):
    value = basic()
    end = 15 * (count - 1) + 30
    value['horizon'] = period(0, end)
    value['participants'][1]['published'] = [period(0, end)]
    value['candidates'] = {'mode': 'explicit', 'anchor_participant': 'professor-A',
                           'starts': [stamp(15*i) for i in range(count)]}
    return value


def prepared(value=None, specs=None, weights=None, facts=None):
    value = fixture() if value is None else value
    specs = ([preference(p['id'], timezone=value['timezone']) for p in value['participants'] if p['required']]
             if specs is None else specs)
    return prepare(synthetic_fixture(value), specs, policy() if weights is None else weights,
                   context(value) if facts is None else facts)
