"""Re-evaluate archived CDMCS sensitivity selections on common metrics."""

import argparse
from collections import Counter, defaultdict
import csv
from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path
from statistics import mean

from research.cdmcs.final_validation.fixtures import RELATIONSHIPS, random_problem
from research.cdmcs.final_validation.model import FullCalendarScoring, Plan, candidate_plans
from research.cdmcs.final_validation.sensitivity import alternatives


def gaps(events, days):
    ordered = sorted(events, key=lambda event: event.start)
    return sum(
        left.end < right.start and days[left.start] == days[right.start]
        for left, right in zip(ordered, ordered[1:])
    )


def common_metrics(problem, plan, scorer):
    added = problem.meeting(plan.start)
    moved = replace(scorer.commitments[plan.moved_id], start=plan.replacement) if plan.moved_id else None
    preferred_minutes = sum(
        problem.profiles[person].rate_prefix[minute + 1] - problem.profiles[person].rate_prefix[minute] == 1
        for person in problem.required
        for minute in range(added.start, added.end)
    )
    affected = set(added.people).union(moved.people if moved else ())
    added_gaps = 0
    for person in affected:
        before = scorer.baseline[person]
        after = [event for event in before if event.id != plan.moved_id]
        if person in added.people:
            after.append(added)
        if moved and person in moved.people:
            after.append(moved)
        added_gaps += gaps(after, problem.days) - gaps(before, problem.days)
    meeting_minutes = len(added.people) * added.duration
    return {
        "wait_minutes": plan.start - min(problem.starts),
        "preferred_minutes": preferred_minutes,
        "required_meeting_minutes": meeting_minutes,
        "coverage_percent": 100 * preferred_minutes / meeting_minutes,
        "added_gaps": added_gaps,
        "affected_people": len(affected),
        "gaps_per_affected_person": added_gaps / len(affected),
        "max_positive_burden": scorer.score(plan).burden,
        "relocation": int(bool(moved)),
    }


def evaluate(archive, output):
    variants = alternatives()
    with archive.open(encoding="utf-8", newline="") as handle:
        archived = list(csv.DictReader(handle))
    seen = set()
    cases = {}
    by_variant = defaultdict(list)
    raw = []
    for row in archived:
        case, variant = row["case"], row["variant"]
        if (case, variant) in seen or variant not in variants:
            raise ValueError(f"Unexpected duplicate or variant in the archive for {case}/{variant}")
        seen.add((case, variant))
        shape = tuple(map(int, row["relationship"].split(":")))
        group = RELATIONSHIPS.index(shape)
        replicate = int(case.removeprefix(f"sensitivity-{group}-"))
        seed = 20261207 + 1000 * group + replicate
        if seed != int(row["seed"]):
            raise ValueError(f"Archive seed differs for {case}")
        if case not in cases:
            problem = random_problem(case, shape, seed, variants["default"])
            problem.validate()
            cases[case] = (problem, FullCalendarScoring(problem), frozenset(candidate_plans(problem)))
        problem, scorer, legal_plans = cases[case]
        if len(legal_plans) != int(row["feasible"]) or bool(legal_plans) != bool(row["selected_start"]):
            raise ValueError(f"Archive feasibility differs for {case}/{variant}")
        outcome = {
            "case": case, "relationship": row["relationship"], "seed": seed, "variant": variant,
            "feasible_arrangements": len(legal_plans), "selected_start": row["selected_start"],
            "moved_id": row["moved_id"], "replacement": row["replacement"],
        }
        if legal_plans:
            plan = Plan(int(row["selected_start"]), row["moved_id"], int(row["replacement"]))
            if plan not in legal_plans:
                raise ValueError(f"Archived selection is infeasible for {case}/{variant}")
            outcome.update(common_metrics(problem, plan, scorer))
            for metric, column in (("wait_minutes", "delay_minutes"), ("max_positive_burden", "default_burden_at_selection")):
                if outcome[metric] != int(row[column]):
                    raise ValueError(f"Archived {metric} differs for {case}/{variant}")
            by_variant[variant].append(outcome)
        raw.append(outcome)
    if seen != {(case, variant) for case in cases for variant in variants}:
        raise ValueError("Sensitivity configurations are incompletely paired.")
    if Counter(problem.relationship for problem, _, _ in cases.values()) != dict.fromkeys(RELATIONSHIPS, 8):
        raise ValueError("Expected eight archived fixtures for each relationship.")

    metrics = {}
    for name, settings in variants.items():
        values = by_variant[name]
        moves = sum(row["relocation"] for row in values)
        metrics[name] = {
            "rates": settings.rates,
            "gap_weight": settings.gap_weight,
            "nearby_minutes": settings.nearby_limit,
            "gap_rule": "tapered" if name == "tapered_nearby" else "cutoff",
            "delay_per_day": settings.delay,
            "base_relocation_penalty": settings.fixed_move,
            "person_relocation_penalty": settings.participant_move,
            "feasible_cases": len(values),
            "waiting_minutes": mean(row["wait_minutes"] for row in values),
            "preferred_coverage_percent": mean(row["coverage_percent"] for row in values),
            "new_gaps_per_person": mean(row["gaps_per_affected_person"] for row in values),
            "mean_max_personal_burden": mean(row["max_positive_burden"] for row in values),
            "peak_max_personal_burden": max(row["max_positive_burden"] for row in values),
            "moved_cases": moves,
            "move_percent": 100 * moves / len(values),
        }

    output.mkdir(parents=True, exist_ok=True)
    with (output / "weight-observations.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, lineterminator="\n", fieldnames=list(dict.fromkeys(field for sample in raw for field in sample)))
        writer.writeheader()
        writer.writerows(raw)
    (output / "weight-summary.json").write_text(
        json.dumps({"archive_sha256": sha256(archive.read_bytes()).hexdigest(), "observations": len(raw),
                    "paired_fixtures": len(cases), "metrics": metrics}, indent=2) + "\n", encoding="utf-8",
    )
    table = [
        "| Configuration | Rates | Gap | Cutoff min | Delay/day | Move fixed/person | Wait min | Preferred min % | Gap change/person | Max burden mean / peak | Moved |",
        "| --- | --- | ---: | --- | ---: | --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for name, row in metrics.items():
        rule = f"{row['nearby_minutes']} + taper" if row["gap_rule"] == "tapered" else str(row["nearby_minutes"])
        rates = "/".join(map(str, row["rates"]))
        table.append(
            f"| {name.replace('_', ' ')} | {rates} | {row['gap_weight']} | {rule} | {row['delay_per_day']} "
            f"| {row['base_relocation_penalty']}/{row['person_relocation_penalty']} | {row['waiting_minutes']:.2f} "
            f"| {row['preferred_coverage_percent']:.2f} | {row['new_gaps_per_person']:+.3f} "
            f"| {row['mean_max_personal_burden']:.2f} / {row['peak_max_personal_burden']} "
            f"| {row['moved_cases']}/{row['feasible_cases']} |"
        )
    markdown = "\n".join(table) + "\n"
    (output / "weight-table.md").write_text(markdown, encoding="utf-8")
    print(f"Verified {len(raw)} archived observations across {len(cases)} paired fixtures and {len(metrics)} configurations.")
    print(markdown)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    evaluate(args.archive, args.output)


if __name__ == "__main__":
    main()
