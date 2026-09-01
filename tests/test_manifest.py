import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from worldmodel_data.manifest import file_entry, validate_snapshot


class ManifestTests(unittest.TestCase):
    def test_file_entry_and_validation_detect_tampering(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data = root / "rows.json"
            data.write_text(json.dumps({"records": [{"id": 1}]}), encoding="utf-8")
            entry = file_entry(data, root, "source-a", "https://example.test/source")
            (root / "manifest.json").write_text(
                json.dumps({"schema_version": 1, "files": [entry]}), encoding="utf-8"
            )
            self.assertEqual(validate_snapshot(root, {"source-a"}), [])
            data.write_text("tampered", encoding="utf-8")
            self.assertTrue(any("sha256 mismatch" in item for item in validate_snapshot(root, {"source-a"})))

    def test_manifest_rejects_parent_path(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            payload = {
                "schema_version": 1,
                "files": [{
                    "path": "../secret",
                    "source_id": "source-a",
                    "source_url": "https://example.test",
                    "sha256": hashlib.sha256(b"").hexdigest(),
                    "bytes": 0,
                }],
            }
            (root / "manifest.json").write_text(json.dumps(payload), encoding="utf-8")
            self.assertTrue(any("unsafe path" in item for item in validate_snapshot(root, {"source-a"})))

    def test_manifest_validates_secondary_sources_and_unlisted_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data = root / "rows.json"
            data.write_text("[]", encoding="utf-8")
            entry = file_entry(
                data,
                root,
                "source-a",
                "https://example.test/source-a",
                ["source-b"],
            )
            (root / "manifest.json").write_text(
                json.dumps({"schema_version": 1, "files": [entry]}), encoding="utf-8"
            )
            self.assertEqual(validate_snapshot(root, {"source-a", "source-b"}), [])
            (root / "unlisted.csv").write_text("secret", encoding="utf-8")
            errors = validate_snapshot(root, {"source-a", "source-b"})
            self.assertTrue(any("unlisted files" in item for item in errors))
            self.assertTrue(any("unlisted.csv" in item for item in errors))


if __name__ == "__main__":
    unittest.main()
