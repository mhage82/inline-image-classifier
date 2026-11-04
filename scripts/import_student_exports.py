"""Import older browser exports by original image ID, preserving their provenance."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts.merge_annotations import merge


def plan_import(source, master, reference_dataset, excluded=("Subas Subedi",)):
    reference = {}
    for entry in master["annotations"]:
        if entry["dataset_id"] != reference_dataset:
            continue
        row = entry["annotation"]
        key, name = row["image_id"], row["filename"]
        if key in reference and reference[key] != name:
            raise ValueError(f"Conflicting current filenames for {key}")
        reference[key] = name
    if not reference:
        raise ValueError("No reference images for the selected dataset")
    plans, skipped = [], []
    for path in sorted(Path(source).rglob("*.json")):
        raw = path.read_bytes()
        document = json.loads(raw.decode("utf-8-sig"))
        identity = path.name + " " + str(document.get("annotator_id", ""))
        if any(name.casefold() in identity.casefold() for name in excluded):
            skipped.append(path.name)
            continue
        for field in ("dataset_id", "group_id", "guidelines_version", "annotator_id", "exported_at"):
            if not isinstance(document.get(field), str) or not document[field].strip():
                raise ValueError(f"{path.name}: Missing {field}")
        rows = document.get("annotations")
        if not isinstance(rows, dict) or not rows:
            raise ValueError(f"{path.name}: Missing annotations")
        normalized = copy.deepcopy(document)
        # Derive a repeatable ID from original export content, never from its filename.
        canonical = json.dumps(document, sort_keys=True, allow_nan=False)
        digest = hashlib.sha256(raw).hexdigest()
        import_id = str(uuid.uuid5(uuid.NAMESPACE_URL, "annotation-browser-export:" + canonical))
        normalized["submission_id"] = import_id
        normalized["group_version"] = document.get("group_version") or "legacy-" + hashlib.sha256(
            json.dumps({"dataset": document["dataset_id"], "group": document["group_id"], "images": sorted(rows)}, sort_keys=True).encode()
        ).hexdigest()[:20]
        # Export time is known; a server submission time is not. Record the distinction.
        normalized["submitted_at"] = document["exported_at"]
        normalized["import_provenance"] = {
            "kind": "legacy_browser_export", "source_file": path.name,
            "source_sha256": digest,
            "original_submission_id": document.get("submission_id"),
            "reference_dataset_id": reference_dataset,
            "matching_method": "original_image_id_sha256",
            "submitted_at_basis": "original_exported_at; no server submission timestamp available",
        }
        changed = 0
        for key, row in normalized["annotations"].items():
            if not isinstance(row, dict) or row.get("image_id") != key:
                raise ValueError(f"{path.name}: Invalid image identity {key}")
            if key not in reference:
                raise ValueError(f"{path.name}: Image not found in reference dataset: {key}")
            if not isinstance(row.get("filename"), str) or not row["filename"]:
                raise ValueError(f"{path.name}: Missing original filename: {key}")
            row["original_filename"] = row["filename"]
            row["filename"] = reference[key]
            changed += row["original_filename"] != row["filename"]
        plans.append({"path": path, "raw_bytes": raw, "document": normalized,
                      "target": "student-export-" + import_id + ".json",
                      "renamed_answers": changed})
    return plans, skipped


def import_exports(source, repo, reference_dataset, excluded=("Subas Subedi",), apply=False):
    repo = Path(repo).resolve()
    master_path = repo / "data/annotations/master.json"
    master = json.loads(master_path.read_text(encoding="utf-8-sig"))
    plans, skipped = plan_import(source, master, reference_dataset, excluded)
    raw_dir = repo / "data/annotations/raw/student_exports"
    archive_dir = repo / "data/annotations/archive/student_exports"
    report_path = repo / "data/annotations/reports/student_export_import.json"
    # Fully validate the proposed master in isolation before writing repository files.
    import tempfile
    import shutil
    with tempfile.TemporaryDirectory() as tmp:
        stage = Path(tmp)
        shutil.copytree(repo / "data/annotations/raw", stage / "raw")
        staged_imports = stage / "raw/student_exports"
        staged_imports.mkdir(exist_ok=True)
        for plan in plans:
            target = staged_imports / plan["target"]
            text = json.dumps(plan["document"], indent=2, ensure_ascii=False, allow_nan=False) + "\n"
            if target.exists() and json.loads(target.read_text(encoding="utf-8-sig")) != plan["document"]:
                raise ValueError(f"Refusing to overwrite conflicting import {target.name}")
            archive = archive_dir / plan["target"]
            if archive.exists() and archive.read_bytes() != plan["raw_bytes"]:
                raise ValueError(f"Refusing to overwrite conflicting archive {archive.name}")
            target.write_text(text, encoding="utf-8")
        proposed = merge(stage / "raw", stage / "master.json")
    report = {
        "reference_dataset_id": reference_dataset, "excluded_annotators": list(excluded),
        "excluded_files": skipped, "imported_export_count": len(plans),
        "imported_answer_count": sum(len(p["document"]["annotations"]) for p in plans),
        "matched_unique_image_count": len({k for p in plans for k in p["document"]["annotations"]}),
        "renamed_answer_count": sum(p["renamed_answers"] for p in plans),
        "unmatched_image_count": 0,
        "imports": [{"source_file": p["path"].name, "normalized_file": p["target"],
                     "source_sha256": p["document"]["import_provenance"]["source_sha256"],
                     "annotator_id": p["document"]["annotator_id"],
                     "answer_count": len(p["document"]["annotations"])} for p in plans],
        "master_summary": proposed["summary"],
        "existing_annotations_policy": "preserved; separate student judgments appended",
    }
    if apply:
        raw_dir.mkdir(parents=True, exist_ok=True)
        archive_dir.mkdir(parents=True, exist_ok=True)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        for p in plans:
            (archive_dir / p["target"]).write_bytes(p["raw_bytes"])
            (raw_dir / p["target"]).write_text(json.dumps(p["document"], indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
        merge(repo / "data/annotations/raw", master_path)
        report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--repo", type=Path, default=ROOT)
    parser.add_argument("--reference-dataset", required=True)
    parser.add_argument("--exclude-annotator", action="append", default=["Subas Subedi"])
    parser.add_argument("--apply", action="store_true", help="Write imports and rebuild master; otherwise only validate and report")
    args = parser.parse_args()
    try:
        result = import_exports(args.source, args.repo, args.reference_dataset, args.exclude_annotator, args.apply)
    except (OSError, ValueError) as error:
        parser.exit(1, f"Cannot import student exports: {error}\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    # Support both python scripts/import_student_exports.py and python -m scripts.import_student_exports.
    main()
