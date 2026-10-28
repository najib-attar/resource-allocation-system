"""Complete explicit-candidate comparisons; errors never count as infeasibility."""

from dataclasses import asdict
from statistics import median

from .adapter import cdmcs_request, normalize, production_request
from .execution import ERROR, UNSUPPORTED
from .snapshot import SnapshotError, integer, parse_snapshot


def compare(value, engines, repetitions=1, warmups=0, ranking=True):
    report = {"input": value, "status": ERROR, "complete": False, "feasible_set_equal": None,
              "calls": [], "discrepancies": [], "reasons": [], "ranking": None}
    try:
        integer(repetitions, 1, 5, "repetitions")
        integer(warmups, 0, 2, "warmups")
        normalized = normalize(parse_snapshot(value))
        report["normalized"] = asdict(normalized)
        report["snapshot_id"] = normalized.snapshot.id
        report["candidate_count"] = len(normalized.candidates)
        if normalized.unsupported:
            report.update(status=UNSUPPORTED, reasons=list(normalized.unsupported))
            return report
        if 2 * len(normalized.candidates) * (repetitions + warmups) + 2 > 10000:
            raise SnapshotError("Experiment exceeds 10000 process invocations")
        observations = {name: [] for name in ("production", "cdmcs")}
        feasible = {name: set() for name in observations}
        halted = False
        for round_number in range(-warmups, repetitions):
            for index, start in enumerate(normalized.candidates):
                requests = {"production": production_request(normalized, start),
                            "cdmcs": cdmcs_request(normalized, (start,))}
                order = ("production", "cdmcs") if (index + round_number) % 2 == 0 else ("cdmcs", "production")
                pair = {}
                for name in order:
                    record = engines.execute(name, requests[name])
                    record.update(phase="warmup" if round_number < 0 else "validation", round=round_number, candidate=start)
                    report["calls"].append(record)
                    pair[name] = record["classification"]
                    if round_number >= 0:
                        observations[name].append(record)
                        if record["classification"] == "feasible":
                            feasible[name].add(start)
                if pair["production"] != pair["cdmcs"]:
                    report["discrepancies"].append({"round": round_number, "candidate": start, "outcomes": pair})
                if any(state not in ("feasible", "infeasible") for state in pair.values()):
                    halted = True
                    break
            if halted:
                break
        errors = [call for call in report["calls"] if call["classification"] not in ("feasible", "infeasible")]
        # Repeated results must also agree within each engine; union alone is not evidence.
        for name, records in observations.items():
            for start in normalized.candidates:
                states = {row["classification"] for row in records if row["candidate"] == start}
                if len(states) > 1:
                    report["discrepancies"].append({"engine": name, "candidate": start, "nondeterministic": sorted(states)})
        report["feasible_sets"] = {name: sorted(starts) for name, starts in feasible.items()}
        report["complete"] = not errors
        report["feasible_set_equal"] = (feasible["production"] == feasible["cdmcs"] and not report["discrepancies"]) if not errors else None
        report["status"] = (ERROR if any(row["classification"] == ERROR for row in errors) else UNSUPPORTED) if errors else ("equal" if report["feasible_set_equal"] else "discrepancy")
        if ranking and normalized.snapshot.candidate_mode == "production_grid" and normalized.candidates and not errors:
            batch = {}
            for name, request in (("production", production_request(normalized)), ("cdmcs", cdmcs_request(normalized))):
                record = engines.execute(name, request)
                record["phase"] = "ranking"
                report["calls"].append(record)
                batch[name] = record
                if record["classification"] not in ("feasible", "infeasible"):
                    report["status"] = ERROR
            if all(row["classification"] in ("feasible", "infeasible") for row in batch.values()):
                production = batch["production"]["payload"]["recommendations"]
                cdmcs = batch["cdmcs"]["payload"]["recommendations"]
                starts_p = [row["start"] for row in production]
                starts_c = [normalized.snapshot.anchor + row["start_minute"] * 60 for row in cdmcs]
                if (any(t not in feasible["production"] for t in starts_p)
                        or any(t not in feasible["cdmcs"] for t in starts_c)
                        or len(starts_p) != min(100, len(feasible["production"]))
                        or batch["cdmcs"]["payload"]["solutions_evaluated"] != len(feasible["cdmcs"])):
                    report["status"] = "discrepancy"
                    report["discrepancies"].append({"ranking_feasibility_mismatch": True})
                report["ranking"] = {"same_objective": False, "production": production, "cdmcs": cdmcs,
                                     "same_start_order": starts_p == starts_c, "limit": 100,
                                     "production_truncated": len(feasible["production"]) > len(starts_p),
                                     "cdmcs_truncated": batch["cdmcs"]["payload"]["truncated"],
                                     "explanation": "Production: optional invitees, preferred-time distance, chronology. CDMCS: synthetic incremental cost, fairness, chronology on normalized fixed busy unions."}
        elif normalized.snapshot.candidate_mode == "explicit":
            report["ranking"] = {"unsupported": "Production recommendation grid does not enumerate arbitrary explicit/manual candidates"}
        report["timings"] = {}
        for name, records in observations.items():
            keys = ("encode", "launch", "communicate", "decode_validate", "total")
            report["timings"][name] = {key + "_median_ns": median(row["timings_ns"][key] for row in records
                                                       if key in row["timings_ns"]) for key in keys
                                       if any(key in row["timings_ns"] for row in records)}
            report["timings"][name]["measured_calls"] = len(records)
        report["methodology"] = {"repetitions": repetitions, "warmup_rounds": warmups,
                                 "order": "Alternating engine order for identical singleton candidates",
                                 "scope": "End-to-end child process, not pure C++ computation",
                                 "launch": "Popen construction only; startup may continue during communicate",
                                 "communicate": "Includes remaining startup, input transfer, parse, compute and serialize",
                                 "ranking_calls_in_timing": False}
    except (SnapshotError, ValueError, OSError) as error:
        report["status"] = ERROR
        report["reasons"].append(str(error))
    return report
