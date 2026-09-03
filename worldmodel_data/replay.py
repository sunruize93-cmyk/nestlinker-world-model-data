from __future__ import annotations

import json
import statistics
from pathlib import Path
from typing import Iterable


def audit_replay_inputs(snapshot_dir: Path) -> dict[str, object]:
    """Describe which replay claims an immutable snapshot can support."""
    manifest = json.loads((snapshot_dir / "manifest.json").read_text(encoding="utf-8"))
    files = manifest.get("files", [])
    blockers: list[str] = []
    if any(item.get("usage") == "not_for_statistical_inference" for item in files):
        blockers.append("truncated_sample")
    has_time_sliced_distribution = any(
        item.get("usage") == "historical_time_sliced_distribution" for item in files
    )
    if not has_time_sliced_distribution:
        blockers.append("no_time_sliced_distribution")
    return {
        "snapshot_id": manifest.get("snapshot_id"),
        "statistical_replay": "blocked" if blockers else "supported",
        "structural_replay": "supported",
        "blockers": blockers,
    }


def _group_key(record: dict[str, object]) -> tuple[str, str, str, str]:
    return (
        str(record["contractMonth"])[5:7],
        str(record["guCode"]),
        str(record["buildingUse"]),
        str(record["leaseType"]),
    )


def _metric(
    pairs: Iterable[tuple[dict[str, object], dict[str, object]]],
    *,
    p25: str,
    median: str,
    p75: str,
) -> dict[str, int | float | None]:
    usable = [
        (train, test)
        for train, test in pairs
        if isinstance(train.get(median), (int, float))
        and isinstance(test.get(median), (int, float))
        and float(test[median]) > 0
    ]
    if not usable:
        return {
            "eligibleGroupCount": 0,
            "targetRecordCount": 0,
            "weightedAbsoluteErrorManwon": None,
            "weightedAbsolutePercentageError": None,
            "medianAbsolutePercentageError": None,
            "medianBandCoverage": None,
        }
    total_weight = sum(int(test["count"]) for _, test in usable)
    absolute = [abs(float(train[median]) - float(test[median])) for train, test in usable]
    weighted_error = sum(
        error * int(test["count"]) for error, (_, test) in zip(absolute, usable)
    ) / total_weight
    weighted_denominator = sum(float(test[median]) * int(test["count"]) for _, test in usable)
    percentages = [
        error / float(test[median]) for error, (_, test) in zip(absolute, usable)
    ]
    covered_weight = sum(
        int(test["count"])
        for train, test in usable
        if float(train[p25]) <= float(test[median]) <= float(train[p75])
    )
    return {
        "eligibleGroupCount": len(usable),
        "targetRecordCount": total_weight,
        "weightedAbsoluteErrorManwon": round(weighted_error, 2),
        "weightedAbsolutePercentageError": round(
            sum(error * int(test["count"]) for error, (_, test) in zip(absolute, usable))
            / weighted_denominator,
            4,
        ),
        "medianAbsolutePercentageError": round(statistics.median(percentages), 4),
        "medianBandCoverage": round(covered_weight / total_weight, 4),
    }


def run_historical_replay(
    payload: dict[str, object],
    *,
    years: tuple[int, ...] | None = None,
    min_group_count: int = 30,
) -> dict[str, object]:
    """Evaluate a prior-year same-month median baseline without future leakage."""
    if min_group_count < 1:
        raise ValueError("min_group_count must be positive")
    records = payload.get("records")
    if not isinstance(records, list):
        raise ValueError("payload must contain records")
    available = sorted({int(row["contractYear"]) for row in records})
    selected = tuple(years or available)
    if len(selected) < 2:
        raise ValueError("historical replay requires at least two years")
    if any(later != earlier + 1 for earlier, later in zip(selected, selected[1:])):
        raise ValueError("replay years must be consecutive")
    index = {}
    seen_keys = set()
    for row in records:
        key = (int(row["contractYear"]), *_group_key(row))
        if key in seen_keys:
            raise ValueError(f"duplicate replay group: {key}")
        seen_keys.add(key)
        if key[0] in selected and int(row["count"]) >= min_group_count:
            index[key] = row
    folds = []
    for train_year, test_year in zip(selected, selected[1:]):
        pairs = []
        for key, test in index.items():
            if key[0] != test_year:
                continue
            train = index.get((train_year, *key[1:]))
            if train is not None:
                pairs.append((train, test))
        if not pairs:
            raise ValueError(f"no eligible comparable groups for {train_year}->{test_year}")
        folds.append({
            "trainYear": train_year,
            "testYear": test_year,
            "baseline": "prior_year_same_month_group_median",
            "deposit": _metric(
                pairs,
                p25="depositP25Manwon",
                median="depositMedianManwon",
                p75="depositP75Manwon",
            ),
            "monthlyLeaseDeposit": _metric(
                ((train, test) for train, test in pairs if test["leaseType"] == "monthly"),
                p25="depositP25Manwon",
                median="depositMedianManwon",
                p75="depositP75Manwon",
            ),
            "jeonseDeposit": _metric(
                ((train, test) for train, test in pairs if test["leaseType"] == "jeonse"),
                p25="depositP25Manwon",
                median="depositMedianManwon",
                p75="depositP75Manwon",
            ),
            "monthlyRent": _metric(
                ((train, test) for train, test in pairs if test["leaseType"] == "monthly"),
                p25="monthlyRentP25Manwon",
                median="monthlyRentMedianManwon",
                p75="monthlyRentP75Manwon",
            ),
        })
    return {
        "schemaVersion": 1,
        "claimStatus": "retrospective_structural_market_replay_only",
        "years": list(selected),
        "minimumGroupCount": min_group_count,
        "folds": folds,
        "limitations": [
            "The baseline evaluates aggregate historical price-band stability, not listing availability.",
            "It has no contract-safety, deposit-loss, foreigner-friction, or user-outcome labels.",
            "The annual source files are final retrospective releases; receipt-year filtering removes known cross-year leakage but cannot reconstruct the exact file visible at a historical cutoff.",
            "Band coverage means a target group median fell within the prior-year interquartile band; it is not individual-contract interval coverage.",
        ],
    }


def as_receipt_filter_counterfactual(result: dict[str, object]) -> dict[str, object]:
    """Mark an intentionally leaky run so machine consumers cannot treat it as valid replay."""
    return {
        **result,
        "claimStatus": "sensitivity_counterfactual_not_valid_replay",
        "limitations": [
            "This counterfactual deliberately includes cross-year receipt records and is not a valid historical replay.",
            "It exists only to measure sensitivity to the receipt-year exclusion rule.",
            "It has no contract-safety, deposit-loss, foreigner-friction, or user-outcome labels.",
            "Band coverage concerns aggregate group medians, not individual contracts.",
        ],
    }
