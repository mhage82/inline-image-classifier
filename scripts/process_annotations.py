"""Create one record per image, a binary target, and a review queue."""
import argparse
from collections import Counter, defaultdict
import csv
import io
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LABELS = ("physical_obstruction", "exposure_fault", "lens_contamination",
          "optical_motion_blur", "lens_fog_condensation")


def write_text(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists() or path.read_text(encoding="utf-8") != text:
        temporary = path.with_name(path.name + ".tmp")
        temporary.write_text(text, encoding="utf-8", newline="\n")
        temporary.replace(path)


def csv_text(fields, rows):
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue()


def process(master, config, adjudications=None):
    policy = config.get("disagreement_policy", "review")
    if policy not in ("review", "majority"):
        raise ValueError("disagreement_policy must be review or majority")
    reference = config["reference_dataset_id"]
    adjudications = adjudications or {}
    names = {}
    by_image = defaultdict(list)
    for entry in master["annotations"]:
        row = entry["annotation"]
        if row["status"] != "annotated" or set(row["labels"]) - set(LABELS):
            raise ValueError(f"Invalid answer for {row['image_id']}")
        judgment = row["artifact_judgment"]
        if judgment not in ("present", "none", "uncertain") or (judgment == "present") != bool(row["labels"]):
            raise ValueError(f"Inconsistent answer for {row['image_id']}")
        by_image[row["image_id"]].append(entry)
        if entry["dataset_id"] == reference:
            previous = names.setdefault(row["image_id"], row["filename"])
            if previous != row["filename"]:
                raise ValueError(f"Conflicting reference filenames: {row['image_id']}")
    if not names:
        raise ValueError("Reference dataset not found in master")
    if set(adjudications) - set(names):
        raise ValueError("Adjudications contain images outside the reference dataset")
    workbook_decisions = {r["annotation"]["image_id"]: r for r in master.get("reviewed_annotations", [])}
    images, review = [], []
    for image_id, filename in sorted(names.items()):
        entries = sorted(by_image[image_id], key=lambda e: (e["annotator_id"].casefold(), e["submission_id"]))
        people = defaultdict(list)
        for entry in entries:
            people[entry["annotator_id"].strip().casefold()].append(entry)
        voters = []
        for identity, answers in sorted(people.items()):
            binary = set()
            flags = {label: set() for label in LABELS}
            for entry in answers:
                row = entry["annotation"]
                value = {"present": 1, "none": 0, "uncertain": None}[row["artifact_judgment"]]
                binary.add(value)
                for label in LABELS:
                    flags[label].add(None if value is None else int(label in row["labels"]))
            voters.append({
                "annotator_id": answers[0]["annotator_id"], "answer_count": len(answers),
                "artifact_present": next(iter(binary)) if len(binary) == 1 else None,
                "has_conflicting_binary_answers": len(binary) > 1,
                "label_flags": {k: next(iter(v)) if len(v) == 1 else None for k, v in flags.items()},
            })
        counts = Counter(v["artifact_present"] for v in voters)
        certain = {v["artifact_present"] for v in voters}
        target = None
        if len(certain) == 1 and None not in certain:
            target = next(iter(certain))
            status = "single_annotator" if len(voters) == 1 else "consensus"
        elif policy == "majority" and max(counts[0], counts[1]) > len(voters) / 2:
            target = 1 if counts[1] > counts[0] else 0
            status = "majority"
        else:
            status = "review_required"
        final_flags = {}
        for label in LABELS:
            values = {v["label_flags"][label] for v in voters}
            final_flags[label] = next(iter(values)) if len(values) == 1 and None not in values else None
        resolution = adjudications.get(image_id)
        if resolution is not None:
            if (not isinstance(resolution, dict) or type(resolution.get("artifact_present")) is not int
                    or resolution["artifact_present"] not in (0, 1)
                    or not isinstance(resolution.get("reviewer"), str) or not resolution["reviewer"].strip()
                    or not isinstance(resolution.get("reason"), str) or not resolution["reason"].strip()):
                raise ValueError(f"Adjudication requires binary target, reviewer, and reason: {image_id}")
            target, status = resolution["artifact_present"], "adjudicated"
            if target == 0:
                final_flags = dict.fromkeys(LABELS, 0)
        workbook_review = workbook_decisions.get(image_id)
        if workbook_review:
            reviewed_label = workbook_review["annotation"]["labels"][0]
            target = None if reviewed_label == "dropped" else reviewed_label
            status = "dropped" if reviewed_label == "dropped" else "workbook_reviewed"
            if target == 0:
                final_flags = dict.fromkeys(LABELS, 0)
            if reviewed_label == "dropped":
                final_flags = dict.fromkeys(LABELS, None)
        reasons = []
        if counts[0] and counts[1]:
            reasons.append("annotators_disagree")
        if counts[None]:
            reasons.append("uncertain_or_inconsistent_annotator")
        result = {
            "image_id": image_id, "filename": filename, "artifact_present": target,
            "resolution_status": status, "distinct_annotator_count": len(voters),
            "answer_count": len(entries),
            "binary_votes": {"present": counts[1], "absent": counts[0], "uncertain_or_conflicting": counts[None]},
            "label_flags": final_flags, "review_reasons": reasons,
            "adjudication": resolution, "annotator_votes": voters, "annotations": entries,
        }
        if workbook_review:
            result["workbook_review"] = workbook_review
        images.append(result)
        if target is None and status != "dropped":
            review.append({"image_id": image_id, "filename": filename,
                           "present_votes": counts[1], "absent_votes": counts[0],
                           "uncertain_or_conflicting_votes": counts[None],
                           "annotators": "; ".join(v["annotator_id"] for v in voters),
                           "reason": "; ".join(reasons),
                           "artifact_present": "", "reviewer": "", "review_note": ""})
    summary = {
        "unique_image_count": len(images), "source_annotation_count": sum(r["answer_count"] for r in images),
        "artifact_present": sum(r["artifact_present"] == 1 for r in images),
        "artifact_absent": sum(r["artifact_present"] == 0 for r in images),
        "review_required": len(review),
        "dropped_image_count": sum(r["resolution_status"] == "dropped" for r in images),
        "single_annotator_images": sum(r["distinct_annotator_count"] == 1 for r in images),
        "multiple_annotator_images": sum(r["distinct_annotator_count"] > 1 for r in images),
        "resolution_status_counts": dict(sorted(Counter(r["resolution_status"] for r in images).items())),
        "repeated_answers_beyond_one_per_annotator": sum(r["answer_count"] - r["distinct_annotator_count"] for r in images),
        "category_disagreement_or_uncertainty_images": sum(any(v is None for v in r["label_flags"].values()) for r in images),
        "source_images_outside_reference_dataset": len(set(by_image) - set(names)),
    }
    return {"schema_version": 1, "processing_policy": config, "summary": summary, "images": images}, review


def read_decisions(path, existing):
    decisions = dict(existing)
    seen = set()
    with Path(path).open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not {"image_id", "artifact_present", "reviewer", "review_note"} <= set(reader.fieldnames or []):
            raise ValueError("Decision CSV must contain image_id, artifact_present, reviewer, review_note")
        for row in reader:
            value = (row.get("artifact_present") or "").strip()
            if not value:
                continue
            key = row["image_id"].strip()
            if key in seen or value not in ("0", "1"):
                raise ValueError(f"Duplicate decision or invalid binary value: {key}")
            seen.add(key)
            decisions[key] = {"artifact_present": int(value), "reviewer": row["reviewer"].strip(),
                              "reason": row["review_note"].strip()}
    return decisions


def agreement_tables(images):
    # One column per distinct person; missing/uncertain choices stay blank.
    identities = {}
    for image in images:
        for vote in image["annotator_votes"]:
            identities.setdefault(vote["annotator_id"].strip().casefold(), vote["annotator_id"].strip())
    columns = {key: "annotator::" + identities[key] + "::artifact_present" for key in sorted(identities)}
    base = ["image_id", "filename", "artifact_present", "resolution_status", "distinct_annotator_count"]
    fields = base + ["reviewer_choices", "annotator_votes"] + list(columns.values())
    rows, long_rows = [], []
    for image in images:
        row = {key: image[key] for key in base}
        choices = []
        for vote in image["annotator_votes"]:
            key = vote["annotator_id"].strip().casefold()
            value = vote["artifact_present"]
            description = str(value) if value is not None else ("conflicting" if vote["has_conflicting_binary_answers"] else "uncertain")
            choices.append(identities[key] + ": " + description)
            row[columns[key]] = value
            long_rows.append({"image_id": image["image_id"], "filename": image["filename"],
                             "annotator_id": identities[key], "artifact_present": value,
                             "vote_status": description if value is None else "certain",
                             "answer_count": vote["answer_count"], **vote["label_flags"]})
        row["reviewer_choices"] = "; ".join(choices)
        row["annotator_votes"] = json.dumps(image["annotator_votes"], ensure_ascii=False, sort_keys=True)
        rows.append(row)
    long_fields = ["image_id", "filename", "annotator_id", "artifact_present", "vote_status", "answer_count"] + list(LABELS)
    return fields, rows, long_fields, long_rows


def run(repo, decisions_csv=None):
    repo = Path(repo)
    base = repo / "data/annotations"
    config = json.loads((base / "processing_config.json").read_text(encoding="utf-8-sig"))
    master = json.loads((base / "master.json").read_text(encoding="utf-8-sig"))
    adjudications = json.loads((base / "adjudications.json").read_text(encoding="utf-8-sig"))
    if decisions_csv:
        adjudications = read_decisions(decisions_csv, adjudications)
    output, review = process(master, config, adjudications)
    if decisions_csv:
        write_text(base / "adjudications.json", json.dumps(adjudications, indent=2, ensure_ascii=False) + "\n")
    write_text(base / "processed/images.json", json.dumps(output, indent=2, ensure_ascii=False, allow_nan=False) + "\n")
    write_text(base / "reports/processing_summary.json", json.dumps(output["summary"], indent=2) + "\n")
    write_text(base / "reports/review_queue.csv", csv_text(
        ["image_id", "filename", "present_votes", "absent_votes", "uncertain_or_conflicting_votes", "annotators", "reason", "artifact_present", "reviewer", "review_note"], review))
    fields, rows, long_fields, long_rows = agreement_tables(output["images"])
    write_text(base / "processed/labels.csv", csv_text(fields, rows))
    write_text(base / "processed/annotator_votes.csv", csv_text(long_fields, long_rows))
    return output["summary"]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=ROOT)
    parser.add_argument("--decisions-csv", type=Path, help="Import completed manual review rows; blank targets are skipped")
    args = parser.parse_args()
    try:
        print(json.dumps(run(args.repo, args.decisions_csv), indent=2))
    except (OSError, ValueError) as error:
        parser.exit(1, f"Cannot process annotations: {error}\n")
