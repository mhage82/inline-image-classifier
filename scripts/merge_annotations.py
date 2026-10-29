"""Rebuild the master JSON from raw website submissions (standard library only)."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def merge(raw_dir, output):
    raw_dir, output = Path(raw_dir).resolve(), Path(output).resolve()
    if not raw_dir.is_dir():
        raise ValueError(f"Raw directory does not exist: {raw_dir}")
    if output == raw_dir or raw_dir in output.parents:
        raise ValueError("Keep the master JSON outside the raw directory.")
    submissions, annotations, seen = [], [], {}
    for path in sorted(raw_dir.rglob("*.json")):
        relative = path.relative_to(raw_dir).as_posix()
        try:
            document = json.loads(path.read_text(encoding="utf-8-sig"))
            if not isinstance(document, dict) or document.get("schema_version") != 1:
                raise ValueError("Expected a schema_version 1 submission object")
            for field in ("submission_id", "dataset_id", "group_id", "group_version", "annotator_id", "guidelines_version", "submitted_at"):
                if not isinstance(document.get(field), str) or not document[field].strip():
                    raise ValueError(f"Missing or invalid {field}")
            rows = document.get("annotations")
            if not isinstance(rows, dict) or not rows:
                raise ValueError("Expected nonempty annotations object")
            for key, row in rows.items():
                if not isinstance(row, dict) or row.get("image_id") != key:
                    raise ValueError(f"Image identity mismatch: {key}")
                if row.get("status") != "annotated" or not isinstance(row.get("filename"), str) or not row["filename"]:
                    raise ValueError(f"Incomplete annotation: {key}")
                labels = row.get("labels")
                if not isinstance(labels, list) or not all(isinstance(label, str) and label for label in labels) or len(labels) != len(set(labels)):
                    raise ValueError(f"Invalid labels: {key}")
                judgment = row.get("artifact_judgment")
                if judgment not in ("present", "none", "uncertain") or (judgment == "present") != bool(labels):
                    raise ValueError(f"Inconsistent artifact judgment: {key}")
            digest = hashlib.sha256(json.dumps(document, sort_keys=True, allow_nan=False).encode()).hexdigest()
            submission_id = document["submission_id"]
            if submission_id in seen:
                previous, metadata = seen[submission_id]
                if previous != digest:
                    raise ValueError(f"Conflicting copies of submission {submission_id}")
                metadata["source_files"].append(relative)
                continue
            metadata = {key: value for key, value in document.items() if key != "annotations"}
            metadata["source_files"] = [relative]
            metadata["annotation_count"] = len(rows)
            submissions.append(metadata)
            seen[submission_id] = (digest, metadata)
            context = {key: document[key] for key in ("submission_id", "dataset_id", "group_id", "group_version", "annotator_id", "guidelines_version", "submitted_at")}
            for key in sorted(rows):
                # Nest the original answer so future answer fields cannot overwrite provenance.
                annotations.append({**context, "annotation": rows[key]})
        except (ValueError, TypeError) as error:
            raise ValueError(f"{relative}: {error}") from error
    counts = Counter(row["annotation"]["image_id"] for row in annotations)
    master = {
        "schema_version": 1,
        "summary": {
            "raw_file_count": sum(len(s["source_files"]) for s in submissions),
            "submission_count": len(submissions),
            "annotation_count": len(annotations),
            "unique_image_count": len(counts),
            "images_with_multiple_annotations": sum(n > 1 for n in counts.values()),
            "submissions_per_dataset": dict(sorted(Counter(s["dataset_id"] for s in submissions).items())),
        },
        "submissions": submissions,
        "annotations": annotations,
    }
    text = json.dumps(master, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
    output.parent.mkdir(parents=True, exist_ok=True)
    if not output.exists() or output.read_text(encoding="utf-8") != text:
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="\n", dir=output.parent, delete=False) as handle:
                temporary = Path(handle.name)
                handle.write(text)
            temporary.replace(output)
        finally:
            if temporary and temporary.exists():
                temporary.unlink()
    return master


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-dir", type=Path, default=ROOT / "data/annotations/raw")
    parser.add_argument("--output", type=Path, default=ROOT / "data/annotations/master.json")
    args = parser.parse_args()
    try:
        master = merge(args.raw_dir, args.output)
    except (OSError, ValueError) as error:
        parser.exit(1, f"Cannot merge annotations: {error}\n")
    print(json.dumps(master["summary"], indent=2))


if __name__ == "__main__":
    main()
