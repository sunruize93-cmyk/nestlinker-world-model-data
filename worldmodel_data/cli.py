from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

from .manifest import file_entry, validate_snapshot
from .rtms import fetch_rtms, rolling_months, service_key_from_env

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "catalog" / "datasets.json"

SEED_FILES = {
    "data/public-housing/listings.json": (
        "rtms-sample.json", "molit-rtms-rent", "https://www.data.go.kr/data/15126469/openapi.do"
    ),
    "data/public-housing/summaries.json": (
        "rtms-summaries.json", "molit-rtms-rent", "https://www.data.go.kr/data/15126469/openapi.do"
    ),
    "data/public-housing/demographics.json": (
        "demographics.json", "moj-foreign-residents", "https://www.immigration.go.kr/bbs/immigration/227/608718/artclView.do", ["mois-resident-population"]
    ),
    "data/public-housing/market-regions.json": (
        "market-regions.json", "mois-legal-dong-codes", "https://www.data.go.kr/data/15077871/openapi.do"
    ),
    "data/gosiwon/listings.json": (
        "seoul-gosiwon-registry.json", "seoul-gosiwon-fire-registry", "https://www.data.go.kr/data/15030030/fileData.do"
    ),
    "data/koreaSubway/catalog.json": (
        "korea-subway-stations.json", "korea-subway-cc0", "https://gist.github.com/nemorize/ac5f39ff62b6bf82dc496d10c69b2b46"
    ),
}


def load_catalog() -> dict:
    return json.loads(CATALOG.read_text(encoding="utf-8"))


def command_catalog(args: argparse.Namespace) -> int:
    datasets = load_catalog()["datasets"]
    if args.category:
        datasets = [item for item in datasets if item["category"] == args.category]
    for item in datasets:
        print(f"{item['id']}\t{item['category']}\t{item['status']}\t{item['title']}")
    return 0


def command_import(args: argparse.Namespace) -> int:
    source_root = Path(args.source_root).expanduser().resolve()
    snapshot_dir = ROOT / "data" / "snapshots" / args.snapshot_date / "initial-public-baseline"
    if snapshot_dir.exists() and any(snapshot_dir.iterdir()) and not args.force:
        raise SystemExit(f"snapshot already exists: {snapshot_dir}; pass --force to replace generated files")
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    entries = []
    for relative, seed in SEED_FILES.items():
        target_name, source_id, source_url, *rest = seed
        secondary_source_ids = rest[0] if rest else None
        source = source_root / relative
        if not source.is_file():
            raise SystemExit(f"missing seed file: {source}")
        target = snapshot_dir / target_name
        shutil.copy2(source, target)
        entries.append(
            file_entry(target, snapshot_dir, source_id, source_url, secondary_source_ids)
        )
    manifest = {
        "schema_version": 1,
        "snapshot_id": f"initial-public-baseline-{args.snapshot_date}",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "data_label": "observed_and_derived_observed",
        "geography": "Korea market regions with a Seoul-first product focus",
        "derivation": "Imported from NestLinker public-data artifacts; no partner listing or user data included.",
        "limitations": [
            "RTMS rows are historical contracts, not currently available listings.",
            "Demographic statistics have different reference populations and dates.",
            "Gosiwon fire registration is not a safety certification or vacancy signal.",
            "Community subway coordinates require official validation for production routing."
        ],
        "files": entries,
    }
    (snapshot_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(snapshot_dir)
    return 0


def command_validate(_: argparse.Namespace) -> int:
    errors: list[str] = []
    catalog = load_catalog()
    datasets = catalog.get("datasets")
    if not isinstance(datasets, list) or not datasets:
        errors.append("catalog/datasets.json: datasets must be non-empty")
        datasets = []
    ids = [item.get("id") for item in datasets if isinstance(item, dict)]
    if len(ids) != len(set(ids)):
        errors.append("catalog/datasets.json: duplicate dataset id")
    required = {"id", "category", "title", "provider", "landing_url", "access", "license", "status", "privacy", "quality_notes"}
    for index, item in enumerate(datasets):
        if not isinstance(item, dict):
            errors.append(f"catalog dataset {index}: must be an object")
            continue
        missing = sorted(required - item.keys())
        if missing:
            errors.append(f"catalog dataset {item.get('id', index)}: missing {', '.join(missing)}")
        url = item.get("landing_url")
        if not isinstance(url, str) or not url.startswith("https://"):
            errors.append(f"catalog dataset {item.get('id', index)}: landing_url must use https")
    snapshots_root = ROOT / "data" / "snapshots"
    manifests = sorted(snapshots_root.glob("*/*/manifest.json")) if snapshots_root.exists() else []
    if not manifests:
        errors.append("data/snapshots: no snapshot manifests found")
    known = {str(value) for value in ids}
    for manifest in manifests:
        errors.extend(validate_snapshot(manifest.parent, known))
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print(f"OK: {len(datasets)} catalog sources, {len(manifests)} snapshot(s)")
    return 0


def command_fetch_rtms(args: argparse.Namespace) -> int:
    key = service_key_from_env()
    if not key:
        raise SystemExit("DATA_GO_KR_SERVICE_KEY is not set")
    if args.seoul_only:
        regions = json.loads((ROOT / "data" / "snapshots" / args.region_snapshot / "initial-public-baseline" / "market-regions.json").read_text(encoding="utf-8"))
        lawd_codes = [str(item["lawdCode"]) for item in regions if item.get("sido") == "서울특별시"]
    else:
        lawd_codes = args.lawd
    if not lawd_codes:
        raise SystemExit("provide --lawd CODE or --seoul-only")
    result = fetch_rtms(
        service_key=key,
        lawd_codes=lawd_codes,
        months=rolling_months(args.months),
        output_dir=ROOT / "data" / "raw" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
        delay=args.delay,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(prog="nestlinker-data")
    sub = result.add_subparsers(dest="command", required=True)
    catalog = sub.add_parser("catalog", help="list registered sources")
    catalog.add_argument("--category")
    catalog.set_defaults(handler=command_catalog)
    importer = sub.add_parser("import-nestlinker", help="import existing provenance-safe public snapshots")
    importer.add_argument("--source-root", required=True)
    importer.add_argument("--snapshot-date", required=True)
    importer.add_argument("--force", action="store_true")
    importer.set_defaults(handler=command_import)
    validate = sub.add_parser("validate", help="validate catalog and snapshot hashes")
    validate.set_defaults(handler=command_validate)
    rtms = sub.add_parser("fetch-rtms", help="fetch RTMS into ignored raw storage")
    rtms.add_argument("--months", type=int, default=3)
    rtms.add_argument("--lawd", action="append", default=[])
    rtms.add_argument("--seoul-only", action="store_true")
    rtms.add_argument("--region-snapshot", default="2026-09-01")
    rtms.add_argument("--delay", type=float, default=0.15)
    rtms.set_defaults(handler=command_fetch_rtms)
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    return int(args.handler(args))
