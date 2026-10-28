# Isolated CDMCS C++17 research prototype

This is the I2-reviewed copy of the supplied I1 engine. It proposes schedules;
it never books, approves, persists, or changes a calendar. It is not selected by
the university application, EngineGateway, production build, or production CI.
The existing appointment scheduler and its JSON v1 contract are unchanged.

## Model

For explicit finite candidate starts, insert one meeting and optionally relocate
one flexible existing meeting that actually blocks it. Required people and
exclusive resources must remain conflict-free. Fixed events cannot move; there
are no cascades or unrelated moves. Extra availability and relocation produce
pending permission requests, not consent.

The lexicographic objective is `(total cost, maximum positive personal burden,
start, moved ID, replacement start)`. Preference costs combine event rates and
neighboring gaps; disruption, exceptions and delay have explicit costs. Weights
are illustrative, not validated university policy. Scores can legitimately be
negative. Exactness concerns this restricted finite model, not arbitrary
scheduling or participants' eventual approval.

Time is elapsed UTC minutes from a caller-selected anchor, not epoch seconds.
The caller supplies timezone-derived minute costs, local-day ordinals and absolute
availability windows. There is no timezone database inside C++. Adjacent
publication windows are NOT implicitly merged. See the [contract](docs/JSON_CONTRACT.md)
and [correctness/complexity notes](docs/CORRECTNESS_AND_COMPLEXITY.md).

## Build and test

Requires C++17, CMake 3.18+, Boost.JSON headers (tested with Boost 1.85.0), and
Python 3.10+ for the independent oracle. Boost.JSON compiles exactly once from
`boost/json/src.hpp`; no prebuilt Boost binary or new application dependency is
needed. Boost itself is not vendored. CMake does not download dependencies.

For reproducible headers, obtain Boost 1.85.0 from the
[official source archive](https://archives.boost.io/release/1.85.0/source/boost_1_85_0.tar.bz2).
Verify SHA-256 `7009fe1faa1697476bdc7027703a2badb84e849b7b0baad5086b087b971f8617`
against the [published archive metadata](https://archives.boost.io/release/1.85.0/source/boost_1_85_0.tar.bz2.json).
Extract it outside the checkout and retain its license with the headers.

From the repository root (PowerShell, with MinGW on PATH):

```powershell
$python = (Resolve-Path .venv/Scripts/python.exe).Path
& $python -m pip install -r research/cdmcs/i1/requirements-test.txt
cmake -S research/cdmcs/i1 -B build/cdmcs-i1 -G "MinGW Makefiles" `
  -DCMAKE_BUILD_TYPE=Release -DBOOST_JSON_INCLUDE_DIR=C:/deps/boost_1_85_0 `
  "-DPython3_EXECUTABLE=$python"
cmake --build build/cdmcs-i1 --parallel 2
ctest --test-dir build/cdmcs-i1 --output-on-failure
Get-Content -Raw research/cdmcs/i1/examples/demo_request.json | build/cdmcs-i1/cdmcs_i1.exe
```

On Linux omit `-G`, use your Python interpreter, and invoke `cdmcs_i1` without
`.exe`. Multi-config generators need `--config Release` and `ctest -C Release`.
Remove only your owned experimental build directory when done; never remove the
authoritative application backend or database directories.

The differential test is also directly runnable:

```text
python -B research/cdmcs/i1/tests/test_differential.py --binary <executable> --random 600
python -B research/cdmcs/i1/tests/test_hardening.py --binary <executable> -v
```

Tests default to stdout only and do not rewrite examples. Optional `--output`
on the differential runner saves a report to an explicit path. The three original
Python references remain byte-identical; tests verify their upstream SHA-256.
They are test-only dependencies, not production matching rules.

## Boundaries and review

- Output is top-K (1-100) plus the full feasible arrangement count, not a full
  feasible-time export. A single new start can have several relocation arrangements.
- Resource budgets fail the entire request rather than publishing partial answers.
  Exhausting a budget is not evidence that the mathematical instance is infeasible.
- Duplicate JSON object members follow Boost.JSON's last-member-wins semantics;
  callers must generate unique members. Unknown fields are ignored. This is not
  an untrusted public endpoint.
- No authentication, booking transaction, calendar synchronization, optional
  invitee ranking, or production gateway adapter is added.
- Any future connector needs explicit UTC anchoring, privacy, version/correlation
  validation, timeout, freshness verification, consent and transactional revalidation.

Read [review and verification](docs/REVIEW.md) for confirmed fixes, actual test
results, the preserved V15 oracle discrepancy and remaining integration decisions.
`docs/UPSTREAM_SHA256.json` describes the original ZIP contents, not edited files
in this directory. Original generated result files, redundant generated examples,
and the upstream engineering log are intentionally not imported.
