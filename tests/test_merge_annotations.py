import copy
import json
from pathlib import Path
import tempfile
import unittest

from scripts.merge_annotations import merge


def submission(identifier="one", label="physical_obstruction"):
    return {
        "schema_version": 1, "submission_id": identifier,
        "dataset_id": "current-dataset", "group_id": "group-01",
        "group_version": "version-one", "annotator_id": "student",
        "guidelines_version": "2.0", "submitted_at": "2026-10-29T00:00:00Z",
        "annotations": {"img-shared": {
            "image_id": "img-shared", "filename": "image_0001.jpg",
            "labels": [label], "artifact_judgment": "present", "status": "annotated",
            "display": {"display_sha256": "display-hash"},
        }},
    }


class MergeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.raw = self.root / "raw"
        self.raw.mkdir()
        self.output = self.root / "master.json"

    def write(self, name, value):
        (self.raw / name).write_text(json.dumps(value), encoding="utf-8")

    def test_overlap_keeps_separate_answers_and_provenance(self):
        a, b = submission(), submission("two", "lens_contamination")
        b["group_id"] = "group-02"
        b["dataset_id"] = "another-dataset"
        self.write("a.json", a)
        self.write("b.json", b)
        before = (self.raw / "a.json").read_bytes()
        result = merge(self.raw, self.output)
        self.assertEqual(result["summary"]["annotation_count"], 2)
        self.assertEqual(result["summary"]["unique_image_count"], 1)
        self.assertEqual(result["summary"]["images_with_multiple_annotations"], 1)
        self.assertEqual(result["annotations"][0]["annotation"], a["annotations"]["img-shared"])
        self.assertEqual(result["annotations"][1]["dataset_id"], "another-dataset")
        self.assertEqual((self.raw / "a.json").read_bytes(), before)
        first = self.output.read_bytes()
        timestamp = self.output.stat().st_mtime_ns
        merge(self.raw, self.output)
        self.assertEqual(self.output.read_bytes(), first)
        self.assertEqual(self.output.stat().st_mtime_ns, timestamp)

    def test_duplicate_submission_is_counted_once_conflicting_copy_fails(self):
        a = submission()
        self.write("a.json", a)
        self.write("copy.json", a)
        result = merge(self.raw, self.output)
        self.assertEqual(result["summary"]["submission_count"], 1)
        self.assertEqual(result["summary"]["raw_file_count"], 2)
        self.assertEqual(len(result["annotations"]), 1)
        bad = copy.deepcopy(a)
        bad["annotator_id"] = "different"
        self.write("copy.json", bad)
        previous = self.output.read_bytes()
        with self.assertRaisesRegex(ValueError, "Conflicting copies"):
            merge(self.raw, self.output)
        self.assertEqual(self.output.read_bytes(), previous)

    def test_rebuild_reflects_deletion(self):
        self.write("a.json", submission())
        merge(self.raw, self.output)
        (self.raw / "a.json").unlink()
        result = merge(self.raw, self.output)
        self.assertEqual(result["annotations"], [])
        self.assertEqual(result["summary"]["submission_count"], 0)

    def test_bad_input_preserves_previous_master(self):
        self.write("a.json", submission())
        merge(self.raw, self.output)
        previous = self.output.read_bytes()
        for bad in ({}, [], {**submission(), "annotations": {}},
                    {**submission(), "schema_version": 9}):
            self.write("bad.json", bad)
            with self.assertRaises(ValueError):
                merge(self.raw, self.output)
            self.assertEqual(self.output.read_bytes(), previous)
        (self.raw / "bad.json").write_text("{broken", encoding="utf-8")
        with self.assertRaises(ValueError):
            merge(self.raw, self.output)

    def test_output_cannot_be_inside_raw(self):
        with self.assertRaisesRegex(ValueError, "outside"):
            merge(self.raw, self.raw / "master.json")


if __name__ == "__main__":
    unittest.main()
