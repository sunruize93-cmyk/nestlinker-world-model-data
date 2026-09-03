import unittest
from copy import deepcopy
import json
import tempfile
from pathlib import Path

from worldmodel_data.cli import main
from worldmodel_data.model_v0 import run_minimum_world_model
from worldmodel_data.model_v0 import run_scenario_matrix


ROOT = Path(__file__).resolve().parents[1]


def market_payload():
    return {
        "source": "seoul-rental-price-files",
        "generatedAt": "2026-09-03T00:00:00+00:00",
        "provenance": {
            "sourceId": "seoul-rental-price-files",
            "dataLabel": "derived_observed",
            "usage": "historical_time_sliced_distribution",
        },
        "records": [{
            "contractYear": 2024,
            "contractMonth": "2024-08",
            "guCode": "11620",
            "guName": "관악구",
            "buildingUse": "오피스텔",
            "leaseType": "monthly",
            "count": 100,
            "depositP25Manwon": 1000,
            "depositMedianManwon": 1500,
            "depositP75Manwon": 2000,
            "monthlyRentP25Manwon": 55,
            "monthlyRentMedianManwon": 65,
            "monthlyRentP75Manwon": 75,
        }],
    }


def safe_scenario(**overrides):
    scenario = {
        "scenarioId": "student-gwanak-8w",
        "scenarioEvidence": "synthetic",
        "profile": {
            "cashBudgetManwon": 3000,
            "maximumDepositExposureManwon": 2500,
            "monthlyHousingBudgetManwon": 90,
            "moveInWeeks": 8,
            "temporaryHousingMaxWeeks": 2,
            "temporaryHousingBudgetManwon": 100,
            "temporaryHousingWeeklyCostManwon": 40,
        },
        "market": {
            "contractMonth": "2024-08",
            "guCode": "11620",
            "buildingUse": "오피스텔",
            "leaseType": "monthly",
        },
        "checkpoints": {
            "ownershipAndAuthority": "verified",
            "rightsAndEncumbrances": "verified",
            "depositProtectionEligibility": "verified",
            "contractTerms": "verified",
        },
        "policy": {
            "minimumAffordabilityRate": 0.8,
            "verificationLeadWeeks": 2,
        },
        "simulation": {"seed": 7, "draws": 1000},
    }
    scenario.update(overrides)
    return scenario


class MinimumWorldModelTests(unittest.TestCase):
    def test_same_seed_replays_the_same_observed_market_scenario(self):
        first = run_minimum_world_model(market_payload(), safe_scenario())
        second = run_minimum_world_model(market_payload(), safe_scenario())

        self.assertEqual(first, second)
        self.assertEqual(first["claimStatus"], "mechanism_test_only_not_calibrated")
        self.assertEqual(first["evidence"]["observed"]["sourceRecordCount"], 100)
        self.assertEqual(first["evidence"]["observed"]["evidenceGrade"], "observed")
        self.assertEqual(first["evidence"]["synthetic"]["evidenceGrade"], "synthetic")
        self.assertEqual(first["scenarioInputs"]["profile"]["evidenceGrade"], "synthetic")
        self.assertEqual(first["scenarioInputs"]["checkpoints"]["evidenceGrade"], "synthetic")
        self.assertEqual(first["scenarioInputs"]["policy"]["evidenceGrade"], "modeled")
        self.assertEqual(first["reproducibility"], {"modelVersion": "minimum-world-model-v0", "seed": 7, "draws": 1000})

    def test_missing_checkpoint_blocks_progress_before_convenience_is_considered(self):
        scenario = deepcopy(safe_scenario())
        scenario["checkpoints"]["rightsAndEncumbrances"] = "missing"

        result = run_minimum_world_model(market_payload(), scenario)

        self.assertFalse(result["mechanismGate"]["passes"])
        self.assertIsNone(result["safetyGate"]["passes"])
        self.assertEqual(result["safetyGate"]["status"], "unknown_missing_outcome_calibration")
        self.assertEqual(result["recommendedAction"], "complete_real_world_checkpoints")
        self.assertEqual(result["nextCheckpoint"], "rightsAndEncumbrances")
        self.assertEqual(result["mechanismGate"]["unresolvedCheckpoints"], ["rightsAndEncumbrances"])

    def test_more_deposit_tolerance_never_increases_the_exposure_proxy(self):
        strict = deepcopy(safe_scenario())
        strict["profile"]["maximumDepositExposureManwon"] = 1500
        tolerant = deepcopy(strict)
        tolerant["profile"]["maximumDepositExposureManwon"] = 3000

        strict_result = run_minimum_world_model(market_payload(), strict)
        tolerant_result = run_minimum_world_model(market_payload(), tolerant)

        self.assertGreater(
            strict_result["evidence"]["modeled"]["depositExposureExceedanceRate"],
            tolerant_result["evidence"]["modeled"]["depositExposureExceedanceRate"],
        )
        self.assertEqual(strict_result["recommendedAction"], "adjust_budget_or_market_constraints")
        self.assertEqual(tolerant_result["recommendedAction"], "proceed_to_human_contract_review")

    def test_scenario_matrix_is_order_independent_and_never_recommends_signing(self):
        first = deepcopy(safe_scenario())
        first.pop("simulation")
        first.pop("scenarioEvidence")
        second = deepcopy(first)
        second["scenarioId"] = "student-gwanak-2w-missing-check"
        second["profile"]["moveInWeeks"] = 2
        second["checkpoints"]["contractTerms"] = "missing"
        spec = {
            "schemaVersion": 1,
            "claimStatus": "synthetic_profiles_for_mechanism_test_only",
            "seed": 20260903,
            "draws": 500,
            "scenarios": [first, second],
        }
        reversed_spec = {**spec, "scenarios": [second, first]}

        forward = run_scenario_matrix(market_payload(), spec)
        reverse = run_scenario_matrix(market_payload(), reversed_spec)

        self.assertEqual(forward, reverse)
        self.assertEqual(forward["claimStatus"], "mechanism_test_only_not_calibrated")
        self.assertEqual(forward["scenarioCount"], 2)
        self.assertTrue(all("sign" not in row["recommendedAction"] for row in forward["results"]))
        self.assertEqual(
            forward["results"][0]["evidence"]["synthetic"]["depositP95Manwon"],
            forward["results"][1]["evidence"]["synthetic"]["depositP95Manwon"],
        )

        invalid_seed = {**spec, "seed": "20260903"}
        with self.assertRaisesRegex(ValueError, "matrix seed"):
            run_scenario_matrix(market_payload(), invalid_seed)

        duplicate = {**spec, "scenarios": [first, first]}
        with self.assertRaisesRegex(ValueError, "unique"):
            run_scenario_matrix(market_payload(), duplicate)

        injected = deepcopy(first)
        injected["simulation"] = {"seed": 1, "draws": 100, "email": "student@example.com"}
        with self.assertRaisesRegex(ValueError, "unexpected matrix scenario fields"):
            run_scenario_matrix(market_payload(), {**spec, "scenarios": [injected]})

        mislabeled = deepcopy(first)
        mislabeled["scenarioEvidence"] = "observed"
        with self.assertRaisesRegex(ValueError, "unexpected matrix scenario fields"):
            run_scenario_matrix(market_payload(), {**spec, "scenarios": [mislabeled]})

    def test_completed_checkpoints_do_not_consume_future_verification_time(self):
        scenario = deepcopy(safe_scenario())
        scenario["profile"]["moveInWeeks"] = 0
        scenario["profile"]["temporaryHousingMaxWeeks"] = 0
        scenario["profile"]["temporaryHousingBudgetManwon"] = 0

        result = run_minimum_world_model(market_payload(), scenario)

        self.assertTrue(result["mechanismGate"]["housingContinuityFallbackSatisfied"])
        self.assertEqual(result["recommendedAction"], "proceed_to_human_contract_review")

    def test_invalid_budget_and_market_quantiles_are_rejected(self):
        invalid_budget = deepcopy(safe_scenario())
        invalid_budget["profile"]["maximumDepositExposureManwon"] = -1
        with self.assertRaisesRegex(ValueError, "maximumDepositExposureManwon"):
            run_minimum_world_model(market_payload(), invalid_budget)

        invalid_market = market_payload()
        invalid_market["records"][0]["depositP25Manwon"] = 3000
        with self.assertRaisesRegex(ValueError, "deposit quantiles"):
            run_minimum_world_model(invalid_market, safe_scenario())

        small_market = market_payload()
        small_market["records"][0]["count"] = 9
        with self.assertRaisesRegex(ValueError, "at least 10"):
            run_minimum_world_model(small_market, safe_scenario())

        invalid_checkpoint = deepcopy(safe_scenario())
        invalid_checkpoint["checkpoints"]["contractTerms"] = "probably"
        with self.assertRaisesRegex(ValueError, "verified, missing or conflict"):
            run_minimum_world_model(market_payload(), invalid_checkpoint)

        personal_data = deepcopy(safe_scenario())
        personal_data["profile"]["email"] = "student@example.com"
        with self.assertRaisesRegex(ValueError, "unexpected profile fields"):
            run_minimum_world_model(market_payload(), personal_data)

        personal_identifier = deepcopy(safe_scenario())
        personal_identifier["scenarioId"] = "01012345678"
        with self.assertRaisesRegex(ValueError, "safe slug"):
            run_minimum_world_model(market_payload(), personal_identifier)

        original = run_minimum_world_model(market_payload(), safe_scenario())
        renamed = deepcopy(safe_scenario())
        renamed["scenarioId"] = "renamed-synthetic-case"
        self.assertEqual(original, run_minimum_world_model(market_payload(), renamed))
        self.assertRegex(original["scenarioRef"], r"^scenario-[0-9a-f]{16}$")

        noisy_market = deepcopy(safe_scenario())
        noisy_market["market"]["note"] = "changes-no-behavior"
        with self.assertRaisesRegex(ValueError, "unexpected market fields"):
            run_minimum_world_model(market_payload(), noisy_market)

        fabricated = market_payload()
        fabricated["source"] = "totally-fabricated"
        with self.assertRaisesRegex(ValueError, "approved derived-observed source"):
            run_minimum_world_model(fabricated, safe_scenario())

    def test_cli_runs_a_provenance_bound_scenario_matrix(self):
        scenario = deepcopy(safe_scenario())
        scenario.pop("simulation")
        scenario.pop("scenarioEvidence")
        spec = {
            "schemaVersion": 1,
            "claimStatus": "synthetic_profiles_for_mechanism_test_only",
            "seed": 99,
            "draws": 200,
            "scenarios": [scenario],
        }
        snapshot = ROOT / "data/snapshots/2026-09-03/seoul-rental-history"
        with tempfile.TemporaryDirectory() as directory:
            specification = Path(directory) / "scenarios.json"
            output = Path(directory) / "result.json"
            specification.write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")

            exit_code = main([
                "minimum-world-model",
                "--snapshot-dir", str(snapshot),
                "--scenario-file", str(specification),
                "--output", str(output),
            ])
            result = json.loads(output.read_text(encoding="utf-8"))

            renamed_spec = deepcopy(spec)
            renamed_spec["scenarios"][0]["scenarioId"] = "renamed-cli-case"
            renamed_file = Path(directory) / "renamed-scenarios.json"
            renamed_output = Path(directory) / "renamed-result.json"
            renamed_file.write_text(json.dumps(renamed_spec, ensure_ascii=False), encoding="utf-8")
            main([
                "minimum-world-model",
                "--snapshot-dir", str(snapshot),
                "--scenario-file", str(renamed_file),
                "--output", str(renamed_output),
            ])
            renamed_result = json.loads(renamed_output.read_text(encoding="utf-8"))

        self.assertEqual(exit_code, 0)
        self.assertEqual(result["inputSnapshot"], "seoul-rental-history-2026-09-03")
        self.assertEqual(result["scenarioCount"], 1)
        self.assertEqual(len(result["inputDataSha256"]), 64)
        self.assertEqual(len(result["inputManifestSha256"]), 64)
        self.assertEqual(len(result["inputCommit"]), 40)
        self.assertEqual(len(result["scenarioSpecificationSha256"]), 64)
        self.assertEqual(len(result["modelCodeSha256"]), 64)
        self.assertEqual(result, renamed_result)

    def test_published_reference_matrix_is_exactly_replayable(self):
        snapshot = ROOT / "data/snapshots/2026-09-03/seoul-rental-history"
        specification = ROOT / "docs/model/MINIMUM_WORLD_MODEL_SCENARIOS_V0.json"
        expected = json.loads(
            (ROOT / "docs/model/MINIMUM_WORLD_MODEL_RUN_V0.json").read_text(encoding="utf-8")
        )
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "result.json"
            main([
                "minimum-world-model",
                "--snapshot-dir", str(snapshot),
                "--scenario-file", str(specification),
                "--output", str(output),
            ])
            actual = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(actual, expected)

    def test_conflict_escalation_takes_precedence_over_a_missing_checkpoint(self):
        scenario = deepcopy(safe_scenario())
        scenario["checkpoints"]["ownershipAndAuthority"] = "missing"
        scenario["checkpoints"]["contractTerms"] = "conflict"

        result = run_minimum_world_model(market_payload(), scenario)

        self.assertEqual(result["recommendedAction"], "escalate_to_licensed_professional")
        self.assertEqual(result["nextCheckpoint"], "contractTerms")

    def test_urgent_missing_evidence_uses_only_a_bounded_affordable_fallback(self):
        scenario = deepcopy(safe_scenario())
        scenario["profile"]["moveInWeeks"] = 0
        scenario["checkpoints"]["contractTerms"] = "missing"
        scenario["profile"]["maximumDepositExposureManwon"] = 1500

        feasible = run_minimum_world_model(market_payload(), scenario)
        scenario["profile"]["temporaryHousingBudgetManwon"] = 0
        infeasible = run_minimum_world_model(market_payload(), scenario)

        self.assertEqual(feasible["recommendedAction"], "use_bounded_temporary_housing_and_verify")
        self.assertTrue(feasible["mechanismGate"]["housingContinuityFallbackSatisfied"])
        self.assertEqual(feasible["requiredActions"], [
            "use_bounded_temporary_housing",
            "adjust_budget_or_market_constraints",
            "complete_real_world_checkpoints",
        ])
        self.assertEqual(infeasible["recommendedAction"], "no_safe_path_adjust_deadline_or_fallback")
        self.assertFalse(infeasible["mechanismGate"]["housingContinuityFallbackSatisfied"])


if __name__ == "__main__":
    unittest.main()
