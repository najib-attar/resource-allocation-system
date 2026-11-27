# Final relocation-aware CDMCS weight study

The archived sensitivity replay contains **576 observations**, formed by
18 configurations on the same 32 synthetic requests. Each of the four
meeting shapes has eight fixtures. Every configuration has a feasible
selection on all 32. The replay re-creates the seeded calendars and verifies
all archived feasibility counts, selected placements, waits, and common
burdens. It uses the archived placements without repeating the optimizer
comparison.

The [preliminary W0–W5 sweep](preliminary-w0-w5.md) held commitments fixed
and reported a different waiting and gap comparison. Its W5 choice used
delay 60 per day under a rule prioritizing earlier dates. The paired study
below includes one possible flexible relocation and evaluates the different
trade-off between waiting, disruption and individual burden.

## Common evaluation metrics

Each row averages over the same 32 requests with equal weight per request.
The columns measure the selected placement, regardless of the objective
that chose it.

- **Wait** is the elapsed minutes from the earliest candidate start,
  including infeasible early candidates, to the selected start.
- **Preferred coverage** is the share of each request's new meeting
  participant-minutes inside the required attendees' preferred days and
  hours. The replay reads those minutes from the common default profiles.
- **Fragmentation** is the increase in same-day positive idle gaps between
  adjacent calendar events per affected person, measured against their
  original calendars. It includes the effect of a proposed relocation.
  Gaps of any positive size count, even when an objective ignores them.
- **Max burden** is the maximum positive increase for one affected person,
  scored under the same fixed reference rubric for every placement.
  That rubric uses rates 1/2/4, the original gap weight 1 and cutoff 120,
  and the reference relocation burden of 8 per moved participant. The
  table reports the mean of the 32 per-request maxima and their observed
  peak. The institutional fixed relocation and waiting charges are
  separate from personal burden. These units reflect a synthetic proxy.
- **Moved** is the count of selections requiring a conditional relocation.
  The rate denominator is 32 in every row.

Rates are listed in the order preferred hours, other hours on a preferred
day, and nonpreferred day. The tapered configuration preserves the
120-minute penalty and tapers the gap penalty to zero over the following
30 minutes.

| Configuration | Rates | Gap | Cutoff min | Delay/day | Move fixed/person | Wait min | Preferred min % | Gap change/person | Max burden mean / peak | Moved | Decision |
| --- | --- | ---: | --- | ---: | --- | ---: | ---: | ---: | ---: | ---: | --- |
| default | 1/2/4 | 1 | 120 | 10 | 25/8 | 765.47 | 37.42 | +0.651 | 117.19 / 210 | 15/32 | 15 moves versus 10 for the selected configuration |
| preferred hour free | 0/2/4 | 1 | 120 | 10 | 25/8 | 875.16 | 44.69 | +0.664 | 122.81 / 210 | 16/32 | 16 moves versus 10 for the selected configuration |
| preferred hour double | 2/2/4 | 1 | 120 | 10 | 25/8 | 676.88 | 28.59 | +0.640 | 120.00 / 210 | 13/32 | Coverage 28.59% is below 36.42% |
| outside hour equal | 1/1/4 | 1 | 120 | 10 | 25/8 | 720.47 | 28.20 | +0.624 | 119.53 / 210 | 13/32 | Coverage 28.20% is below 36.42% |
| outside hour high | 1/4/4 | 1 | 120 | 10 | 25/8 | 884.53 | 43.83 | +0.671 | 132.19 / 210 | 17/32 | 17 moves versus 10 for the selected configuration |
| nonpreferred day low | 1/2/2 | 1 | 120 | 10 | 25/8 | 866.72 | 34.77 | +0.623 | 127.03 / 210 | 13/32 | Coverage 34.77% is below 36.42% |
| nonpreferred day high | 1/2/8 | 1 | 120 | 10 | 25/8 | 764.53 | 36.88 | +0.666 | 120.72 / 240 | 16/32 | Peak burden 240 exceeds 210 |
| uniform rates | 1/1/1 | 1 | 120 | 10 | 25/8 | 843.28 | 22.81 | +0.691 | 137.34 / 210 | 11/32 | Coverage 22.81% is below 36.42% |
| no gap weight | 1/2/4 | 0 | 120 | 10 | 25/8 | 647.81 | 48.98 | +0.532 | 136.88 / 225 | 4/32 | Peak burden 225 exceeds 210 |
| triple gap weight | 1/2/4 | 3 | 120 | 10 | 25/8 | 902.81 | 28.52 | +0.685 | 126.56 / 210 | 16/32 | Coverage 28.52% is below 36.42% |
| nearby 30 | 1/2/4 | 1 | 30 | 10 | 25/8 | 827.34 | 44.06 | +0.755 | 149.78 / 248 | 13/32 | Peak burden 248 exceeds 210 |
| nearby 240 | 1/2/4 | 1 | 240 | 10 | 25/8 | 812.34 | 40.47 | +0.602 | 147.44 / 240 | 11/32 | Peak burden 240 exceeds 210 |
| no delay | 1/2/4 | 1 | 120 | 0 | 25/8 | 765.47 | 37.42 | +0.651 | 117.19 / 210 | 15/32 | 15 moves versus 10 for the selected configuration |
| delay 40 | 1/2/4 | 1 | 120 | 40 | 25/8 | 586.88 | 34.69 | +0.693 | 120.00 / 240 | 13/32 | Peak burden 240 exceeds 210 and coverage 34.69% is below 36.42% |
| no relocation penalty | 1/2/4 | 1 | 120 | 10 | 0/0 | 819.84 | 36.17 | +0.685 | 117.66 / 210 | 18/32 | Coverage 36.17% is below 36.42% |
| higher fixed move | 1/2/4 | 1 | 120 | 10 | 150/8 | 685.31 | 36.72 | +0.605 | 120.94 / 240 | 4/32 | Peak burden 240 exceeds 210 |
| higher personal move | 1/2/4 | 1 | 120 | 10 | 25/50 | 675.00 | 37.11 | +0.610 | 117.66 / 210 | 10/32 | Fewest moves among configurations meeting both thresholds |
| tapered nearby | 1/2/4 | 1 | 120 + taper | 10 | 25/8 | 813.28 | 34.84 | +0.601 | 117.19 / 210 | 14/32 | Coverage 34.84% is below 36.42% |

## Mathematical model and selection

For a required participant $i$, let $S_i$ be the sum of per-minute time
rates across scheduled events and the penalties between consecutive
same-day events. With a hard cutoff $L$ and desired gap $g_i^*$, an
adjacent gap $g$ contributes $w_g |g - g_i^*|$ when $0 \le g \le L$.
Gaps above $L$ contribute zero. The tapered configuration instead reduces
the penalty to zero over the 30 minutes following $L$. Hard availability,
protected commitments and resource conflicts determine feasibility before
ranking.

For a feasible arrangement $x$, let $R_x$ contain the required participants
in the optional moved meeting, and let $I_x$ be 1 when that meeting moves and
0 otherwise. Let $t_x$ be the proposed start, $t_0$ the earliest submitted
start and $D(t)$ the local civil date represented as a day index. The tested
fixtures use published availability windows, so no exception fee enters the
comparison.

$$
\begin{aligned}
b_i(x) &= S_i(\mathrm{after}\ x)-S_i(\mathrm{before})
          + m_p\,\mathbf{1}_{i\in R_x},\\
C(x) &= \sum_i b_i(x) + m_0 I_x + \lambda [D(t_x)-D(t_0)],\\
B(x) &= \max\bigl(0, \max_i b_i(x)\bigr).
\end{aligned}
$$

Ranking minimizes $C(x)$ first, then $B(x)$, and then uses start and move
identifiers for deterministic ties. The chosen values $m_0=25$ and $m_p=50$
add $25 + 50k$ to total modeled cost when a meeting with $k$ required
participants moves. Compared with the default $25 + 8k$, the increase is
$42k$. This changes the ranking of feasible moves while preserving the score
of every direct option under the shared time, gap and delay weights.

Use the **higher personal move** configuration. Its provisional coefficients
are rates 1/2/4, gap weight 1, a 120-minute hard cutoff, delay 10 per local day,
fixed relocation penalty 25, and relocation burden 50 per affected
participant.

The configuration screen keeps observed peak common burden at or below 210
and mean preferred-minute coverage at or above 36.421875%. The latter is the
default's exact 37.421875% minus one percentage point. It then minimizes the
number of relocation proposals selected, then mean elapsed minutes, with
archive configuration order as the final tie-break. The thresholds were
chosen after examining the synthetic results. They express provisional
demonstration priorities and require human validation before institutional use.

The selected configuration reduced relocations from 15 to 10 of 32 and the
mean wait from 765.47 to 675.00 minutes. It added 0.610 gaps per affected
person on average, compared with 0.651 under the default. The trade-off
was 0.31 percentage points less preferred-time coverage and 0.47 more
common units in mean max burden. Peak burden was 210 in both. Raising the
fixed move penalty alone produced four moves but reached a peak burden of
240. Removing gap weight also produced four moves and raised both mean and
peak common burden. The demo configuration remains provisional until
human preference calibration. Keep it separate from persisted institutional
policy and live-calendar optimization.

## Reproduce

From the research-validation checkout at `e985498`, put its repository root
on `PYTHONPATH` and run [evaluate_weights.py](evaluate_weights.py) with Python
3.13. Pass the archived CSV via
`--archive research/cdmcs/final_validation/evidence/sensitivity_cases.csv`
and a new directory via `--output`. The command emits the raw
[576 observations](weight-observations.csv), the
[18-row comparison and decisions](weight-comparison.csv), the
[JSON summary](weight-summary.json), and a Markdown table. The summary records
the archive checksum, exact thresholds, and unrounded aggregates.
