from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def infer_record_count(path: Path) -> int | None:
    if path.suffix.lower() != ".json":
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if isinstance(payload, list):
        return len(payload)
    if not isinstance(payload, dict):
        return None
    for key in ("listings", "districts", "records", "items"):
        value = payload.get(key)
        if isinstance(value, list):
            return len(value)
    by_city = payload.get("byCity")
    if isinstance(by_city, dict):
        unique: set[tuple[str, float | None, float | None]] = set()
        for city in by_city.values():
            if not isinstance(city, dict):
                continue
            lines = city.get("stationsByLine")
            if not isinstance(lines, dict):
                continue
            for stations in lines.values():
                if not isinstance(stations, list):
                    continue
                for station in stations:
                    if isinstance(station, dict):
                        unique.add((str(station.get("name", "")), station.get("lat"), station.get("lng")))
        return len(unique)
    return None


def file_entry(
    path: Path,
    relative_to: Path,
    source_id: str,
    source_url: str,
    secondary_source_ids: list[str] | None = None,
) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "path": path.relative_to(relative_to).as_posix(),
        "source_id": source_id,
        "source_url": source_url,
        "sha256": sha256_file(path),
        "bytes": path.stat().st_size,
    }
    if secondary_source_ids:
        entry["secondary_source_ids"] = secondary_source_ids
    count = infer_record_count(path)
    if count is not None:
        entry["record_count"] = count
    return entry


def validate_snapshot(snapshot_dir: Path, known_source_ids: set[str]) -> list[str]:
    errors: list[str] = []
    manifest_path = snapshot_dir / "manifest.json"
    if not manifest_path.is_file():
        return [f"{snapshot_dir}: missing manifest.json"]
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return [f"{manifest_path}: invalid JSON: {exc}"]
    if manifest.get("schema_version") != 1:
        errors.append(f"{manifest_path}: schema_version must be 1")
    files = manifest.get("files")
    if not isinstance(files, list) or not files:
        errors.append(f"{manifest_path}: files must be a non-empty list")
        return errors
    seen: set[str] = set()
    for entry in files:
        if not isinstance(entry, dict):
            errors.append(f"{manifest_path}: non-object file entry")
            continue
        relative = entry.get("path")
        if not isinstance(relative, str) or relative.startswith("/") or ".." in Path(relative).parts:
            errors.append(f"{manifest_path}: unsafe path {relative!r}")
            continue
        if relative in seen:
            errors.append(f"{manifest_path}: duplicate path {relative}")
        seen.add(relative)
        source_id = entry.get("source_id")
        if source_id not in known_source_ids:
            errors.append(f"{manifest_path}: unknown source_id {source_id!r}")
        secondary = entry.get("secondary_source_ids", [])
        if not isinstance(secondary, list) or any(not isinstance(value, str) for value in secondary):
            errors.append(f"{manifest_path}: secondary_source_ids must be a string list")
        else:
            for value in secondary:
                if value not in known_source_ids:
                    errors.append(f"{manifest_path}: unknown secondary_source_id {value!r}")
            if source_id in secondary or len(secondary) != len(set(secondary)):
                errors.append(f"{manifest_path}: duplicate source attribution for {relative}")
        target = snapshot_dir / relative
        if target.is_symlink():
            errors.append(f"{target}: symlinks are forbidden")
            continue
        if not target.is_file():
            errors.append(f"{target}: file missing")
            continue
        actual = sha256_file(target)
        if entry.get("sha256") != actual:
            errors.append(f"{target}: sha256 mismatch")
        if entry.get("bytes") != target.stat().st_size:
            errors.append(f"{target}: byte count mismatch")
    actual_files = {
        item.relative_to(snapshot_dir).as_posix()
        for item in snapshot_dir.rglob("*")
        if item.is_file() and item.name != "manifest.json"
    }
    unlisted = sorted(actual_files - seen)
    if unlisted:
        errors.append(f"{manifest_path}: unlisted files: {', '.join(unlisted)}")
    return errors
