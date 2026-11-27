# Preliminary fixed-calendar weight experiments

The earlier W0–W5 sweep held calendars and candidate times fixed. It reported
206 feasible requests out of 240 and used a 120-minute nearby-gap cutoff.
The sweep disabled relocation. Rates are per minute in preferred hours,
other hours on a preferred day, and nonpreferred days, respectively.

| Configuration | Rates | Gap weight | Delay per day | Mean wait (days) | Preferred minutes | Mean unweighted gap penalty change per participant | Mean additional W0 cost per request |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| W0 baseline | 1/2/4 | 1 | 10 | 0.869 | 42.2% | 5.37 | 0.00 |
| W1 equal rates | 1/1/1 | 1 | 10 | 0.850 | 22.2% | 0.77 | 37.52 |
| W2 strong preference | 1/4/8 | 1 | 10 | 0.864 | 54.5% | 12.98 | 13.64 |
| W3 no gap cost | 1/2/4 | 0 | 10 | 0.796 | 57.3% | 27.37 | 62.11 |
| W4 strong gap cost | 1/2/4 | 4 | 10 | 0.937 | 30.7% | 1.10 | 17.65 |
| W5 strong delay | 1/2/4 | 1 | 60 | 0.539 | 41.5% | 7.17 | 6.60 |

The preliminary decision rule kept time and gap preferences in the objective,
required mean wait at or below 0.60 days, and capped mean extra cost at 10
under the W0 rubric. W5 met those conditions in the reported sweep. The upper
limits reflected a proposed policy for interpreting synthetic results.

Provenance comes from slides 2–4 of the preserved local source
`CDMCS_Equation_Weights_and_Final_Choice.pptx`
(SHA-256 `267861a597effa206b682ff3d962cf424f60177c98a8de13e9686a63e1ba8655`).
The slides cite `cdmcs_weight_sensitivity.py`. The archive available for the
final comparison contains the separate relocation-aware study. The table above
transcribes the preliminary results at the source's precision.

The [relocation-aware weight study](weight-analysis.md) uses 32 paired
fixtures, counts added same-day gaps, evaluates maximum individual burden,
and includes the number of conditional relocation options selected.
