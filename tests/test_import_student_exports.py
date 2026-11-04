import copy
import json
from pathlib import Path
import tempfile
import unittest

from scripts.import_student_exports import import_exports, plan_import
from scripts.merge_annotations import merge


def exported():
    return {"schema_version": 1, "dataset_id": "old-dataset", "group_id": "group-01",
            "guidelines_version": "2.0", "annotator_id": "Older student",
            "exported_at": "2026-10-17T00:00:00Z", "annotations": {
                "img-stable": {"image_id": "img-stable", "filename": "image_0003.jpg",
                               "labels": ["lens_contamination"], "artifact_judgment": "present",
                               "status": "annotated"}}}


class ImportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "source"
        self.source.mkdir()
        self.repo = self.root / "repo"
        self.raw = self.repo / "data/annotations/raw"
        self.raw.mkdir(parents=True)
        existing = exported()
        existing.update(submission_id="existing", group_version="current-version", dataset_id="current",
                        submitted_at="2026-10-30T00:00:00Z", annotator_id="Subas Subedi")
        existing["annotations"]["img-stable"]["filename"] = "image_0953.jpeg"
        (self.raw / "existing.json").write_text(json.dumps(existing))
        self.master_path = self.repo / "data/annotations/master.json"
        self.master = merge(self.raw, self.master_path)
        self.original = exported()
        (self.source / "older-student.json").write_text(json.dumps(self.original))

    def test_match_by_id_preserves_labels_old_context_and_original_filename(self):
        plans, skipped = plan_import(self.source, self.master, "current")
        row = plans[0]["document"]["annotations"]["img-stable"]
        self.assertEqual(row["filename"], "image_0953.jpeg")
        self.assertEqual(row["original_filename"], "image_0003.jpg")
        self.assertEqual(row["labels"], ["lens_contamination"])
        self.assertEqual(plans[0]["document"]["dataset_id"], "old-dataset")
        self.assertEqual(skipped, [])

    def test_excluded_by_filename_or_annotator_no_existing_answers_removed(self):
        bad = copy.deepcopy(self.original)
        bad["annotator_id"] = "SUBAS SUBEDI"
        (self.source / "exclude-by-name.json").write_text(json.dumps(bad))
        (self.source / "Subas Subedi_backup.json").write_text(json.dumps(self.original))
        result = import_exports(self.source, self.repo, "current", apply=True)
        self.assertEqual(len(result["excluded_files"]), 2)
        current = json.loads(self.master_path.read_text())
        self.assertEqual(current["summary"]["annotation_count"], 2)
        self.assertIn(self.master["annotations"][0], current["annotations"])

    def test_unmatched_id_fails_even_when_filename_matches(self):
        bad = copy.deepcopy(self.original)
        row = bad["annotations"].pop("img-stable")
        row.update(image_id="img-different", filename="image_0953.jpeg")
        bad["annotations"]["img-different"] = row
        (self.source / "older-student.json").write_text(json.dumps(bad))
        before = self.master_path.read_bytes()
        with self.assertRaisesRegex(ValueError, "Image not found"):
            import_exports(self.source, self.repo, "current", apply=True)
        self.assertEqual(self.master_path.read_bytes(), before)

    def test_apply_is_repeatable_and_archive_is_exact(self):
        before = (self.raw / "existing.json").read_bytes()
        import_exports(self.source, self.repo, "current", apply=True)
        first = self.master_path.read_bytes()
        import_exports(self.source, self.repo, "current", apply=True)
        self.assertEqual(first, self.master_path.read_bytes())
        self.assertEqual((self.raw / "existing.json").read_bytes(), before)
        archive = list((self.repo / "data/annotations/archive/student_exports").glob("*.json"))
        self.assertEqual(len(archive), 1)
        self.assertEqual(archive[0].read_bytes(), (self.source / "older-student.json").read_bytes())

    def test_dry_run_does_not_write(self):
        before = self.master_path.read_bytes()
        result = import_exports(self.source, self.repo, "current")
        self.assertEqual(result["imported_answer_count"], 1)
        self.assertEqual(self.master_path.read_bytes(), before)
        self.assertFalse((self.raw / "student_exports").exists())


if __name__ == "__main__":
    unittest.main()
