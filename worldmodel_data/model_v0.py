"""Mechanism-only foreign renter decision rehearsal.

The public seam is ``run_minimum_world_model``. It intentionally returns policy
proxies and synthetic stress tests, never a probability that a real contract is
safe or that a deposit will be returned.
"""

from __future__ import annotations

import hashlib
import json
import math
import random
import re
from collections import Counter
from copy import deepcopy
from datetime import datetime
from typing import Mapping


MODEL_VERSION = "minimum-world-model-v0"
APPROVED_MARKET_SOURCE = "seoul-rental-price-files"
APPROVED_DATA_LABEL = "derived_observed"
APPROVED_USAGE = "historical_time_sliced_distribution"
PROFILE_FIELDS = {
    "cashBudgetManwon", "maximumDepositExposureManwon", "monthlyHousingBudgetManwon",
    "moveInWeeks", "temporaryHousingMaxWeeks", "temporaryHousingBudgetManwon",
    "temporaryHousingWeeklyCostManwon",
}
MARKET_FIELDS = {"contractMonth", "guCode", "buildingUse", "leaseType"}
POLICY_FIELDS = {"minimumAffordabilityRate", "verificationLeadWeeks"}
SIMULATION_FIELDS = {"seed", "draws"}
SCENARIO_FIELDS = {
    "scenarioId", "scenarioEvidence", "profile", "market", "checkpoints", "policy", "simulation",
}
CHECKPOINTS = (
    "ownershipAndAuthority",
    "rightsAndEncumbrances",
    "depositProtectionEligibility",
    "contractTerms",
)


def _require_exact_fields(values: Mapping[str, object], allowed: set[str], label: str) -> None:
    unexpected = set(values) - allowed
    missing = allowed - set(values)
    if unexpected:
        raise ValueError(f"unexpected {label} fields: {sorted(map(str, unexpected))}")
    if missing:
        raise ValueError(f"missing {label} fields: {sorted(missing)}")


def _finite_number(values: Mapping[str, object], key: str, *, positive: bool = False) -> float:
    value = values.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{key} must be a finite number")
    invalid_range = value <= 0 if positive else value < 0
    if invalid_range:
        qualifier = "positive" if positive else "non-negative"
        raise ValueError(f"{key} must be {qualifier}")
    return float(value)


def _nonnegative_integer(values: Mapping[str, object], key: str) -> int:
    value = values.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{key} must be a non-negative integer")
    return value


def _selected_market(payload: Mapping[str, object], requested: Mapping[str, object]) -> dict:
    records = payload.get("records")
    if not isinstance(records, list):
        raise ValueError("market payload must contain records")
    matches = [
        row for row in records
        if isinstance(row, dict)
        and all(row.get(field) == requested.get(field) for field in (
            "contractMonth", "guCode", "buildingUse", "leaseType"
        ))
    ]
    if len(matches) != 1:
        raise ValueError(f"expected exactly one observed market cell, found {len(matches)}")
    return matches[0]


def _quantile_sample(rng: random.Random, p25: float, median: float, p75: float) -> float:
    lower = max(0.0, p25 - (median - p25))
    upper = p75 + (p75 - median)
    anchors = ((0.0, lower), (0.25, p25), (0.5, median), (0.75, p75), (1.0, upper))
    value = rng.random()
    for (left_p, left_v), (right_p, right_v) in zip(anchors, anchors[1:]):
        if value <= right_p:
            position = (value - left_p) / (right_p - left_p)
            return left_v + position * (right_v - left_v)
    return upper


def _percentile(values: list[float], probability: float) -> float:
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(probability * len(ordered)))
    return round(ordered[index], 2)


def run_minimum_world_model(
    market_payload: Mapping[str, object], scenario: Mapping[str, object]
) -> dict[str, object]:
    """Run one deterministic, evidence-labelled decision rehearsal scenario."""
    profile = scenario.get("profile")
    market_request = scenario.get("market")
    checkpoints = scenario.get("checkpoints")
    policy = scenario.get("policy")
    simulation = scenario.get("simulation")
    if not all(isinstance(value, Mapping) for value in (
        profile, market_request, checkpoints, policy, simulation
    )):
        raise ValueError("scenario requires profile, market, checkpoints, policy and simulation")
    _require_exact_fields(scenario, SCENARIO_FIELDS, "scenario")
    _require_exact_fields(profile, PROFILE_FIELDS, "profile")
    _require_exact_fields(market_request, MARKET_FIELDS, "market")
    _require_exact_fields(checkpoints, set(CHECKPOINTS), "checkpoint")
    _require_exact_fields(policy, POLICY_FIELDS, "policy")
    _require_exact_fields(simulation, SIMULATION_FIELDS, "simulation")
    if scenario.get("scenarioEvidence") != "synthetic":
        raise ValueError("scenarioEvidence must be synthetic for the v0 mechanism test")
    provenance = market_payload.get("provenance")
    if (
        not isinstance(provenance, Mapping)
        or market_payload.get("source") != APPROVED_MARKET_SOURCE
        or provenance.get("sourceId") != APPROVED_MARKET_SOURCE
        or provenance.get("dataLabel") != APPROVED_DATA_LABEL
        or provenance.get("usage") != APPROVED_USAGE
    ):
        raise ValueError("market payload must carry the approved derived-observed source provenance")
    source_generated_at = market_payload.get("generatedAt")
    if not isinstance(source_generated_at, str):
        raise ValueError("market payload requires a timestamped generatedAt")
    try:
        parsed_source_time = datetime.fromisoformat(source_generated_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("market payload generatedAt must be an ISO timestamp") from exc
    if parsed_source_time.tzinfo is None:
        raise ValueError("market payload generatedAt must include a timezone")
    market = _selected_market(market_payload, market_request)
    scenario_id = scenario.get("scenarioId")
    if not isinstance(scenario_id, str) or not scenario_id:
        raise ValueError("scenarioId must be a non-empty string")
    seed_value = simulation.get("seed")
    draws_value = simulation.get("draws")
    if isinstance(seed_value, bool) or not isinstance(seed_value, int):
        raise ValueError("simulation seed must be an integer")
    if isinstance(draws_value, bool) or not isinstance(draws_value, int):
        raise ValueError("simulation draws must be an integer")
    seed = seed_value
    draws = draws_value
    if not 100 <= draws <= 100_000:
        raise ValueError("simulation draws must be between 100 and 100000")
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", str(market["contractMonth"])):
        raise ValueError("contractMonth must be YYYY-MM")
    count = _nonnegative_integer(market, "count")
    if count < 10:
        raise ValueError("observed market cell must contain at least 10 source records")
    deposit_quantiles = tuple(_finite_number(market, key) for key in (
        "depositP25Manwon", "depositMedianManwon", "depositP75Manwon"
    ))
    rent_quantiles = tuple(_finite_number(market, key) for key in (
        "monthlyRentP25Manwon", "monthlyRentMedianManwon", "monthlyRentP75Manwon"
    ))
    if tuple(sorted(deposit_quantiles)) != deposit_quantiles:
        raise ValueError("deposit quantiles must be non-decreasing")
    if tuple(sorted(rent_quantiles)) != rent_quantiles:
        raise ValueError("monthly rent quantiles must be non-decreasing")
    cash_budget = _finite_number(profile, "cashBudgetManwon")
    deposit_limit = _finite_number(profile, "maximumDepositExposureManwon", positive=True)
    rent_budget = _finite_number(profile, "monthlyHousingBudgetManwon")
    move_in_weeks = _nonnegative_integer(profile, "moveInWeeks")
    temporary_max_weeks = _nonnegative_integer(profile, "temporaryHousingMaxWeeks")
    temporary_budget = _finite_number(profile, "temporaryHousingBudgetManwon")
    temporary_weekly_cost = _finite_number(profile, "temporaryHousingWeeklyCostManwon")
    minimum_affordability = _finite_number(policy, "minimumAffordabilityRate")
    if minimum_affordability > 1:
        raise ValueError("minimumAffordabilityRate must be between 0 and 1")
    verification_weeks = _nonnegative_integer(policy, "verificationLeadWeeks")
    rng = random.Random(seed)
    deposits = [
        _quantile_sample(
            rng,
            float(market["depositP25Manwon"]),
            float(market["depositMedianManwon"]),
            float(market["depositP75Manwon"]),
        )
        for _ in range(draws)
    ]
    rents = [
        _quantile_sample(
            rng,
            float(market["monthlyRentP25Manwon"]),
            float(market["monthlyRentMedianManwon"]),
            float(market["monthlyRentP75Manwon"]),
        )
        for _ in range(draws)
    ]
    affordable = [
        deposit + rent <= cash_budget and deposit <= deposit_limit and rent <= rent_budget
        for deposit, rent in zip(deposits, rents)
    ]
    affordability_rate = round(sum(affordable) / draws, 4)
    exceedance_rate = round(sum(value > deposit_limit for value in deposits) / draws, 4)
    observed = {
        "evidenceGrade": "observed",
        "sourceDataLabel": provenance["dataLabel"],
        "source": provenance["sourceId"],
        "sourceUsage": provenance["usage"],
        "sourceGeneratedAt": source_generated_at,
        "sourceRecordCount": market["count"],
        "marketCell": {key: market[key] for key in (
            "contractMonth", "guCode", "guName", "buildingUse", "leaseType"
        )},
        "quantileAnchorsManwon": {key: market[key] for key in (
            "depositP25Manwon", "depositMedianManwon", "depositP75Manwon",
            "monthlyRentP25Manwon", "monthlyRentMedianManwon", "monthlyRentP75Manwon",
        )},
    }
    synthetic = {
        "evidenceGrade": "synthetic",
        "method": "piecewise_linear_quantile_stress_draws",
        "limitation": "Draws independently interpolate and extrapolate deposit and rent marginals from aggregate quantiles; they do not preserve their joint distribution and are not listings or calibrated forecasts.",
        "depositP95Manwon": _percentile(deposits, 0.95),
        "monthlyRentP95Manwon": _percentile(rents, 0.95),
    }
    statuses = {name: checkpoints.get(name) for name in CHECKPOINTS}
    if any(value not in {"verified", "missing", "conflict"} for value in statuses.values()):
        raise ValueError("every mandatory checkpoint must be verified, missing or conflict")
    conflicts = [name for name in CHECKPOINTS if statuses[name] == "conflict"]
    unresolved = [name for name in CHECKPOINTS if statuses[name] != "verified"]
    remaining_verification_weeks = verification_weeks if unresolved else 0
    fallback_weeks_needed = max(0, remaining_verification_weeks - move_in_weeks)
    fallback_feasible = (
        fallback_weeks_needed <= temporary_max_weeks
        and fallback_weeks_needed * temporary_weekly_cost <= temporary_budget
    )
    continuity_satisfied = move_in_weeks >= remaining_verification_weeks or fallback_feasible
    mechanism_gate = {
        "passes": False,
        "marketAffordabilityStressSatisfied": affordability_rate >= minimum_affordability,
        "depositP95StressSatisfied": synthetic["depositP95Manwon"] <= deposit_limit,
        "mandatoryCheckpointsSatisfied": not unresolved,
        "housingContinuityFallbackSatisfied": continuity_satisfied,
        "unresolvedCheckpoints": unresolved,
        "conflictingCheckpoints": conflicts,
    }
    mechanism_gate["passes"] = all((
        mechanism_gate["marketAffordabilityStressSatisfied"],
        mechanism_gate["depositP95StressSatisfied"],
        mechanism_gate["mandatoryCheckpointsSatisfied"],
        mechanism_gate["housingContinuityFallbackSatisfied"],
    ))
    next_checkpoint = conflicts[0] if conflicts else (unresolved[0] if unresolved else None)
    if conflicts:
        action = "escalate_to_licensed_professional"
    elif unresolved and move_in_weeks < verification_weeks and fallback_feasible:
        action = "use_bounded_temporary_housing_and_verify"
    elif unresolved and move_in_weeks < verification_weeks:
        action = "no_safe_path_adjust_deadline_or_fallback"
    elif unresolved:
        action = "complete_real_world_checkpoints"
    elif not mechanism_gate["marketAffordabilityStressSatisfied"] or not mechanism_gate["depositP95StressSatisfied"]:
        action = "adjust_budget_or_market_constraints"
    elif not continuity_satisfied:
        action = "use_bounded_temporary_housing"
    else:
        action = "proceed_to_human_contract_review"
    required_actions = []
    if unresolved and move_in_weeks < verification_weeks and fallback_feasible:
        required_actions.append("use_bounded_temporary_housing")
    elif not continuity_satisfied:
        required_actions.append("adjust_deadline_or_fallback")
    if conflicts:
        required_actions.append("escalate_to_licensed_professional")
    if not mechanism_gate["marketAffordabilityStressSatisfied"] or not mechanism_gate["depositP95StressSatisfied"]:
        required_actions.append("adjust_budget_or_market_constraints")
    if unresolved and not conflicts:
        required_actions.append("complete_real_world_checkpoints")
    if not required_actions:
        required_actions.append("proceed_to_human_contract_review")
    input_digest = hashlib.sha256(
        json.dumps(scenario, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return {
        "schemaVersion": 1,
        "scenarioId": scenario.get("scenarioId"),
        "claimStatus": "mechanism_test_only_not_calibrated",
        "recommendedAction": action,
        "requiredActions": required_actions,
        "nextCheckpoint": next_checkpoint,
        "mechanismGate": mechanism_gate,
        "safetyGate": {
            "status": "unknown_missing_outcome_calibration",
            "passes": None,
            "missingTerms": [
                "depositLossTailRisk_R_D",
                "contractHarmTailRisk_R_C",
                "housingContinuityProbability_P_H",
            ],
            "limitation": "Mechanism checks cannot establish the complete safety-first objective without real outcome labels.",
        },
        "scenarioInputs": {
            "profile": {
                "evidenceGrade": "synthetic",
                "values": dict(profile),
                "limitation": "Test profile, not an observed person.",
            },
            "checkpoints": {
                "evidenceGrade": "synthetic",
                "values": statuses,
                "limitation": "Exercise state, not verification of a real property or contract.",
            },
            "policy": {
                "evidenceGrade": "modeled",
                "values": dict(policy),
                "limitation": "Uncalibrated product policy parameters for mechanism testing.",
            },
        },
        "evidence": {
            "observed": observed,
            "modeled": {
                "evidenceGrade": "modeled",
                "affordabilityRate": affordability_rate,
                "depositExposureExceedanceRate": exceedance_rate,
                "limitation": "Policy proxy over synthetic price draws; not deposit-loss or contract-harm probability.",
            },
            "synthetic": synthetic,
        },
        "reproducibility": {
            "modelVersion": MODEL_VERSION,
            "seed": seed,
            "draws": draws,
        },
        "inputSha256": input_digest,
    }


def run_scenario_matrix(
    market_payload: Mapping[str, object], specification: Mapping[str, object]
) -> dict[str, object]:
    """Run an order-independent matrix with common random streams per market cell."""
    if specification.get("schemaVersion") != 1:
        raise ValueError("scenario matrix schemaVersion must be 1")
    _require_exact_fields(
        specification,
        {"schemaVersion", "claimStatus", "seed", "draws", "scenarios"},
        "scenario matrix",
    )
    if specification.get("claimStatus") != "synthetic_profiles_for_mechanism_test_only":
        raise ValueError("scenario matrix must declare synthetic_profiles_for_mechanism_test_only")
    scenarios = specification.get("scenarios")
    if not isinstance(scenarios, list) or not scenarios:
        raise ValueError("scenario matrix requires a non-empty scenarios list")
    if len(scenarios) > 1000:
        raise ValueError("scenario matrix cannot exceed 1000 scenarios")
    master_seed = specification.get("seed")
    draws = specification.get("draws")
    if isinstance(master_seed, bool) or not isinstance(master_seed, int):
        raise ValueError("matrix seed must be an integer")
    if isinstance(draws, bool) or not isinstance(draws, int) or not 100 <= draws <= 100_000:
        raise ValueError("matrix draws must be an integer between 100 and 100000")
    identifiers = [row.get("scenarioId") for row in scenarios if isinstance(row, Mapping)]
    if len(identifiers) != len(scenarios) or any(not isinstance(value, str) or not value for value in identifiers):
        raise ValueError("every scenario requires a non-empty scenarioId")
    if len(set(identifiers)) != len(identifiers):
        raise ValueError("scenarioId values must be unique")
    results = []
    for scenario in sorted(scenarios, key=lambda row: row["scenarioId"]):
        prepared = deepcopy(scenario)
        prepared["scenarioEvidence"] = "synthetic"
        market = prepared.get("market")
        if not isinstance(market, Mapping):
            raise ValueError("every scenario requires a market object")
        canonical_market = {key: market.get(key) for key in sorted(MARKET_FIELDS)}
        market_stream = json.dumps(canonical_market, ensure_ascii=False, separators=(",", ":"))
        digest = hashlib.sha256(f"{master_seed}:{market_stream}".encode("utf-8")).digest()
        prepared["simulation"] = {
            "seed": int.from_bytes(digest[:8], "big"),
            "draws": draws,
        }
        results.append(run_minimum_world_model(market_payload, prepared))
    actions = Counter(str(row["recommendedAction"]) for row in results)
    return {
        "schemaVersion": 1,
        "modelVersion": MODEL_VERSION,
        "claimStatus": "mechanism_test_only_not_calibrated",
        "scenarioCount": len(results),
        "masterSeed": master_seed,
        "drawsPerScenario": draws,
        "actionCounts": dict(sorted(actions.items())),
        "results": results,
        "nonClaims": [
            "No result estimates real deposit-loss or contract-harm probability.",
            "No action is a legal conclusion or instruction to sign a real contract.",
            "Historical aggregate price bands do not represent current inventory.",
        ],
    }
