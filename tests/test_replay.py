import unittest
from argparse import Namespace
import csv
import io
import json
import tempfile
import zipfile
from pathlib import Path

from worldmodel_data.replay import (
    as_receipt_filter_counterfactual,
    audit_replay_inputs,
    run_historical_replay,
)
from worldmodel_data.manifest import sha256_file, validate_snapshot
from worldmodel_data.cli import command_historical_replay
from worldmodel_data.seoul_rents import build_monthly_aggregates, publish_monthly_snapshot


ROOT = Path(__file__).resolve().parents[1]


class HistoricalReplayTests(unittest.TestCase):
    @staticmethod
    def _write_archive(path, rows, encoding="utf-8-sig"):
        headers = [
            "접수년도", "자치구코드", "자치구명", "계약일", "전월세구분",
            "보증금(만원)", "임대료(만원)", "건물용도",
        ]
        text = io.StringIO(newline="")
        writer = csv.writer(text)
        writer.writerow(headers)
        writer.writerows(rows)
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as output:
            output.writestr("rents.csv", text.getvalue().encode(encoding))

    def test_initial_snapshot_is_rejected_for_statistical_replay(self):
        snapshot = ROOT / "data" / "snapshots" / "2026-09-01" / "initial-public-baseline"

        audit = audit_replay_inputs(snapshot)

        self.assertEqual(audit["statistical_replay"], "blocked")
        self.assertEqual(audit["structural_replay"], "supported")
        self.assertIn("truncated_sample", audit["blockers"])
        self.assertIn("no_time_sliced_distribution", audit["blockers"])

    def test_official_archives_compile_to_minimal_monthly_aggregates(self):
        rows = [
            ["2023", "11110", "종로구", "20230102", "월세", "1000", "50", "단독다가구"],
            ["2023", "11110", "종로구", "20230103", "월세", "2000", "70", "단독다가구"],
            ["2023", "11110", "종로구", "20221231", "월세", "9999", "999", "단독다가구"],
            ["2023", "11110", "종로구", "20230104", "", "1000", "50", "단독다가구"],
            ["2024", "11110", "종로구", "20230105", "월세", "9999", "999", "단독다가구"],
        ]
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "2023.zip"
            self._write_archive(archive, rows)

            payload = build_monthly_aggregates({2023: archive})

        self.assertEqual(payload["sourceRowCount"], 5)
        self.assertEqual(payload["excludedWrongContractYear"], 1)
        self.assertEqual(payload["excludedReceiptYearMismatch"], 1)
        self.assertEqual(payload["excludedReceiptYearMismatchByContractMonth"], {"2023-01": 1})
        self.assertEqual(payload["excludedInvalidRows"], 1)
        self.assertEqual(payload["excludedInvalidRowsByReason"], {"invalid_lease_type": 1})
        self.assertEqual(payload["records"], [{
            "contractYear": 2023,
            "contractMonth": "2023-01",
            "guCode": "11110",
            "guName": "종로구",
            "buildingUse": "단독다가구",
            "leaseType": "monthly",
            "count": 2,
            "depositP25Manwon": 1250,
            "depositMedianManwon": 1500,
            "depositP75Manwon": 1750,
            "monthlyRentP25Manwon": 55,
            "monthlyRentMedianManwon": 60,
            "monthlyRentP75Manwon": 65,
        }])

    def test_receipt_year_filter_can_be_disabled_only_for_sensitivity_analysis(self):
        rows = [
            ["2023", "11110", "종로구", "20230102", "월세", "1000", "50", "단독다가구"],
            ["2024", "11110", "종로구", "20230103", "월세", "3000", "70", "단독다가구"],
        ]
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "2023.zip"
            self._write_archive(archive, rows)

            filtered = build_monthly_aggregates({2023: archive})
            included = build_monthly_aggregates(
                {2023: archive}, exclude_receipt_year_mismatch=False
            )

        self.assertEqual(filtered["records"][0]["count"], 1)
        self.assertEqual(included["records"][0]["count"], 2)
        self.assertEqual(included["records"][0]["depositMedianManwon"], 2000)
        self.assertEqual(included["excludedReceiptYearMismatch"], 0)
        self.assertEqual(included["includedReceiptYearMismatchForSensitivity"], 1)

    def test_archive_with_systemic_exact_duplicates_is_quarantined(self):
        row = ["2025", "11110", "종로구", "20250102", "월세", "1000", "50", "단독다가구"]
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "2025.zip"
            self._write_archive(archive, [row, row], "cp949")

            with self.assertRaisesRegex(ValueError, "systemic exact duplicates"):
                build_monthly_aggregates({2025: archive})

    def test_replay_uses_prior_year_same_month_without_future_leakage(self):
        def record(year, median, count=50):
            return {
                "contractYear": year,
                "contractMonth": f"{year}-01",
                "guCode": "11110",
                "guName": "종로구",
                "buildingUse": "단독다가구",
                "leaseType": "monthly",
                "count": count,
                "depositP25Manwon": median - 200,
                "depositMedianManwon": median,
                "depositP75Manwon": median + 200,
                "monthlyRentP25Manwon": 40,
                "monthlyRentMedianManwon": 50,
                "monthlyRentP75Manwon": 60,
            }

        payload = {"records": [record(2022, 1000), record(2023, 1200), record(2024, 99999)]}

        result = run_historical_replay(payload, years=(2022, 2023), min_group_count=30)

        self.assertEqual(result["folds"][0]["trainYear"], 2022)
        self.assertEqual(result["folds"][0]["testYear"], 2023)
        self.assertEqual(result["folds"][0]["deposit"]["weightedAbsoluteErrorManwon"], 200)
        self.assertEqual(result["folds"][0]["monthlyLeaseDeposit"]["weightedAbsoluteErrorManwon"], 200)
        self.assertEqual(result["folds"][0]["jeonseDeposit"]["eligibleGroupCount"], 0)
        self.assertEqual(result["folds"][0]["deposit"]["medianBandCoverage"], 1.0)
        self.assertEqual(result["claimStatus"], "retrospective_structural_market_replay_only")

    def test_receipt_filter_counterfactual_cannot_claim_valid_replay(self):
        result = as_receipt_filter_counterfactual({
            "claimStatus": "retrospective_structural_market_replay_only",
            "limitations": ["receipt-year filtering removes known cross-year leakage"],
            "folds": [],
        })

        self.assertEqual(result["claimStatus"], "sensitivity_counterfactual_not_valid_replay")
        self.assertIn("deliberately includes", result["limitations"][0])
        self.assertNotIn("filtering removes", " ".join(result["limitations"]))

    def test_replay_rejects_nonconsecutive_years(self):
        with self.assertRaisesRegex(ValueError, "consecutive"):
            run_historical_replay({"records": []}, years=(2022, 2024))

    def test_replay_rejects_duplicate_group_keys(self):
        row = {
            "contractYear": 2022, "contractMonth": "2022-01", "guCode": "11110",
            "buildingUse": "단독다가구", "leaseType": "monthly", "count": 30,
            "depositP25Manwon": 500, "depositMedianManwon": 1000,
            "depositP75Manwon": 1500, "monthlyRentP25Manwon": 40,
            "monthlyRentMedianManwon": 50, "monthlyRentP75Manwon": 60,
        }
        with self.assertRaisesRegex(ValueError, "duplicate replay group"):
            run_historical_replay({"records": [row, dict(row)]}, years=(2022, 2023))

    def test_replay_rejects_empty_or_single_year_inputs(self):
        with self.assertRaisesRegex(ValueError, "at least two"):
            run_historical_replay({"records": []}, years=(2023,))

    def test_published_history_snapshot_is_provenance_valid_and_privacy_minimal(self):
        rows = [
            ["2023", "11110", "종로구", f"202301{day:02d}", "월세", "1000", "50", "단독다가구"]
            for day in range(1, 11)
        ]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "2023.zip"
            target = root / "2026-09-03" / "seoul-rental-history"
            self._write_archive(archive, rows)
            acquisitions = {2023: {
                "official_file": "서울특별시_전월세가_2023.zip",
                "retrieved_at": "2026-09-03T00:09:29Z",
                "sha256": sha256_file(archive),
                "bytes": archive.stat().st_size,
            }}

            publish_monthly_snapshot(
                {2023: archive},
                target,
                created_at="2026-09-03T00:00:00+00:00",
                input_commit="a" * 40,
                acquisitions=acquisitions,
            )

            known = {"seoul-rental-price-files": {
                "landing_url": "https://data.seoul.go.kr/dataList/OA-21276/A/1/datasetView.do",
                "status": "seeded",
            }}
            self.assertEqual(validate_snapshot(target, known), [])
            self.assertEqual(audit_replay_inputs(target)["statistical_replay"], "supported")
            published = (target / "seoul-rental-monthly.json").read_text(encoding="utf-8")
            self.assertNotIn("건물명", published)
            self.assertNotIn("법정동명", published)
            manifest_path = target / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["files"][0]["minimum_cell_count"] = 11
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            self.assertTrue(any(
                "below minimum_cell_count" in error
                for error in validate_snapshot(target, known)
            ))
            manifest["files"][0]["minimum_cell_count"] = 10
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "immutable"):
                publish_monthly_snapshot(
                    {2023: archive}, target,
                    created_at="2026-09-03T00:00:00+00:00", input_commit="a" * 40,
                    acquisitions=acquisitions,
                )
            (target / "seoul-rental-monthly.json").write_text("{}", encoding="utf-8")
            with self.assertRaisesRegex(SystemExit, "snapshot validation failed"):
                command_historical_replay(Namespace(
                    snapshot_dir=str(target),
                    output=str(root / "result.json"),
                    minimum_counts=[30],
                ))


if __name__ == "__main__":
    unittest.main()
