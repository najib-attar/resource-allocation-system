# Compare the five application allocation strategies

Use the same synthetic university to see how many requests each strategy serves,
which it rejects, and how decisions translate into room and time segments.

## Reproduce the comparison

With the application Python dependencies and a C++17 compiler installed, run these
commands from the repository root:

```powershell
python scripts/build_backend.py --if-needed
python scripts/compare_allocation_strategies.py --seed 41 --size moderate --repeats 5 > allocation-comparison.json
```

The comparison generates the fixture once and varies only the strategy. It uses
the same validated C++ JSON gateway as the application in standalone mode. It
does not connect to PostgreSQL, review eligibility, publish allocations, or use
the experimental CDMCS algorithms. The report includes both the fixture and build
fingerprints, per-type results, each rejected request ID and its reason, and all
timing samples. The runner checks that every measured engine response matches
its strategy's warm-up response. Use `--size large` for a separate 1,200-request
experiment and record the new fixture fingerprint.

## Verified example

Seed 41 generated 120 requests, including 30 exams, with 20 rooms, 106 synthetic
users and 12 existing busy slots. The fixture SHA-256 was
`7ba6254e29ac93457dad7a7bd13867b761799374fe01bb6d20101902c9845fc7`.
The example ran on Windows AMD64 with Python 3.12.14, MinGW GCC 14.3.0 and
engine protocol version `allocation-engine-json-1`.

| Strategy | Served | Rejected | Exams served | Allocation segments | Median gateway ms |
| --- | ---: | ---: | ---: | ---: | ---: |
| Greedy | 45 | 75 | 13 | 46 | 828 |
| Priority | 45 | 75 | 13 | 46 | 891 |
| Multi-room Exam Greedy | 57 | 63 | 27 | 81 | 969 |
| Multi-room Exam Best Fit | 59 | 61 | 27 | 70 | 786 |
| Shared-room Exam Best Fit | 59 | 61 | 27 | 74 | 940 |

A served request is one engine approval. A request can generate multiple
segments through recurrence or room splitting. Missing facilities were the
most common recorded rejection reason in every strategy (33â€“34 requests),
followed by spaces under maintenance (12â€“14). Greedy and Priority each
reported insufficient capacity for 13 requests. The three exam strategies
each reported three capacity-related exam rejections and served 27 of the
30 exams. The full JSON report retains each detailed reason.

Each median uses five serial measured calls after one warm-up per strategy.
The order rotates across repetitions. Gateway wall time includes checking the
engine artifact, starting its process, transferring JSON and validating the
response. The sample ran while local regression suites were active. Absolute
times and their ordering can vary with the host load and compiler. These
counts describe this fictional fixture, and the comparison establishes
neither university-wide performance nor a universal strategy ranking.
