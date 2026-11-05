import copy
from pathlib import Path
import tempfile
import unittest

from scripts.process_annotations import process, read_decisions, agreement_tables, csv_text
import csv
import io
import json


def answer(person, judgment="present", labels=None, submission="one"):
    if labels is None:
        labels = ["lens_contamination"] if judgment == "present" else []
    return {"annotator_id": person, "submission_id": submission, "dataset_id": "current",
            "annotation": {"image_id": "img-one", "filename": "image_0010.jpg",
                           "labels": labels, "artifact_judgment": judgment, "status": "annotated"}}


class ProcessingTests(unittest.TestCase):
    config = {"reference_dataset_id": "current", "disagreement_policy": "review"}

    def result(self, entries, **kwargs):
        return process({"annotations": entries}, self.config, **kwargs)

    def test_repeated_annotator_answers_do_not_outvote_other_person(self):
        entries = [answer("Person A", submission=str(i)) for i in range(26)] + [answer("Person B", "none")]
        output, queue = self.result(entries)
        row = output["images"][0]
        self.assertEqual(row["binary_votes"], {"present": 1, "absent": 1, "uncertain_or_conflicting": 0})
        self.assertIsNone(row["artifact_present"])
        self.assertEqual(len(queue), 1)
        self.assertEqual(row["answer_count"], 27)
        self.assertEqual(output["summary"]["repeated_answers_beyond_one_per_annotator"], 25)

    def test_same_person_conflict_and_uncertainty_not_negative(self):
        entries = [answer("A"), answer(" a ", "none", submission="two"), answer("B", "uncertain")]
        output, _ = self.result(entries)
        row = output["images"][0]
        self.assertEqual(row["distinct_annotator_count"], 2)
        self.assertEqual(row["binary_votes"]["uncertain_or_conflicting"], 2)
        self.assertIsNone(row["artifact_present"])

    def test_different_artifact_types_can_agree_on_binary_label(self):
        output, queue = self.result([answer("A"), answer("B", labels=["exposure_fault"])])
        row = output["images"][0]
        self.assertEqual(row["artifact_present"], 1)
        self.assertEqual(row["resolution_status"], "consensus")
        self.assertIsNone(row["label_flags"]["exposure_fault"])
        self.assertEqual(queue, [])

    def test_single_person_evidence_and_source_answers_preserved(self):
        entries = [answer("A", "none")]
        before = copy.deepcopy(entries)
        output, _ = self.result(entries)
        self.assertEqual(entries, before)
        self.assertEqual(output["images"][0]["annotations"], before)
        self.assertEqual(output["images"][0]["resolution_status"], "single_annotator")
        self.assertEqual(output["images"][0]["artifact_present"], 0)

    def test_majority_is_optional_distinct_person_majority(self):
        entries = [answer("A"), answer("B"), answer("C", "none")]
        output, _ = self.result(entries)
        self.assertIsNone(output["images"][0]["artifact_present"])
        output, _ = process({"annotations": entries}, {**self.config, "disagreement_policy": "majority"})
        self.assertEqual(output["images"][0]["artifact_present"], 1)
        self.assertEqual(output["images"][0]["resolution_status"], "majority")

    def test_adjudication_requires_provenance_and_clears_queue(self):
        entries = [answer("A"), answer("B", "none")]
        with self.assertRaises(ValueError):
            self.result(entries, adjudications={"img-one": {"artifact_present": 0}})
        output, queue = self.result(entries, adjudications={"img-one": {
            "artifact_present": 0, "reviewer": "Organizer", "reason": "Reviewed original image"}})
        self.assertEqual(output["images"][0]["resolution_status"], "adjudicated")
        self.assertEqual(output["images"][0]["artifact_present"], 0)
        self.assertEqual(queue, [])

    def test_reference_filename_preferred_over_old_name(self):
        current, old = answer("A"), answer("B")
        old.update(dataset_id="old", submission_id="old")
        old["annotation"]["filename"] = "image_0003.jpg"
        output, _ = self.result([old, current])
        self.assertEqual(output["images"][0]["filename"], "image_0010.jpg")

    def test_review_csv_accepts_decisions_skips_blank_and_rejects_duplicates(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "review.csv"
            path.write_text("image_id,artifact_present,reviewer,review_note\nimg-one,1,Reviewer,Visible droplet\nimg-two,,,\n")
            result = read_decisions(path, {})
            self.assertEqual(result, {"img-one": {"artifact_present": 1, "reviewer": "Reviewer", "reason": "Visible droplet"}})
            with path.open("a") as handle:
                handle.write("img-one,0,Reviewer,Duplicate\n")
            with self.assertRaises(ValueError):
                read_decisions(path, {})

    def test_agreement_export_preserves_disagreement_once_per_person(self):
        output, _ = self.result([answer("A"), answer("A", submission="two"), answer("B", "none")])
        fields, rows, long_fields, votes = agreement_tables(output["images"])
        row = list(csv.DictReader(io.StringIO(csv_text(fields, rows))))[0]
        self.assertEqual(row["artifact_present"], "")
        self.assertEqual(row["annotator::A::artifact_present"], "1")
        self.assertEqual(row["annotator::B::artifact_present"], "0")
        self.assertEqual(row["reviewer_choices"], "A: 1; B: 0")
        self.assertEqual(len(json.loads(row["annotator_votes"])), 2)
        self.assertEqual(len(votes), 2)
        self.assertEqual(votes[0]["answer_count"], 2)
        self.assertEqual(votes[0]["lens_contamination"], 1)

    def test_agreement_export_keeps_uncertain_missing_and_consensus(self):
        a = answer('A, "Reviewer"')
        b = answer("B", "uncertain")
        b["annotation"]["image_id"] = "img-two"
        b["annotation"]["filename"] = "other.jpg"
        output, _ = self.result([a, b])
        fields, rows, _, _ = agreement_tables(output["images"])
        decoded = list(csv.DictReader(io.StringIO(csv_text(fields, rows))))
        self.assertEqual(decoded[0]['annotator::A, "Reviewer"::artifact_present'], "1")
        self.assertEqual(decoded[0]["annotator::B::artifact_present"], "")
        self.assertEqual(decoded[1]["reviewer_choices"], "B: uncertain")
        consensus, _ = self.result([answer("A"), answer("B")])
        _, consensus_rows, _, _ = agreement_tables(consensus["images"])
        self.assertEqual(consensus_rows[0]["reviewer_choices"], "A: 1; B: 1")


if __name__ == "__main__":
    unittest.main()
