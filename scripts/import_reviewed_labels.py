"""Import final binary/dropped labels from an Excel workbook, matched by image ID."""
import argparse
import hashlib
import json
from pathlib import Path
import posixpath
import sys
from xml.etree import ElementTree as ET
from zipfile import ZipFile
from decimal import Decimal, InvalidOperation

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.merge_annotations import merge

NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}


def read_workbook(path):
    with ZipFile(path) as archive:
        strings = []
        if "xl/sharedStrings.xml" in archive.namelist():
            strings = ["".join(t.text or "" for t in node.findall(".//m:t", NS))
                       for node in ET.fromstring(archive.read("xl/sharedStrings.xml")).findall("m:si", NS)]
        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        sheet = next((s for s in workbook.findall("m:sheets/m:sheet", NS) if s.get("name") == "labels"), None)
        if sheet is None:
            raise ValueError("Workbook must have a labels sheet")
        rel_id = sheet.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")
        rels = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        target = next(r.get("Target") for r in rels if r.get("Id") == rel_id)
        sheet_path = target.lstrip("/") if target.startswith("/") else posixpath.normpath("xl/" + target)
        rows = ET.fromstring(archive.read(sheet_path)).findall("m:sheetData/m:row", NS)
        def text(cell):
            if cell.get("t") == "s":
                return strings[int(cell.findtext("m:v", namespaces=NS))]
            if cell.get("t") == "inlineStr":
                return "".join(t.text or "" for t in cell.findall(".//m:t", NS))
            if cell.find("m:f", NS) is not None:
                raise ValueError("Formula in reviewed fields; save explicit reviewed values first")
            return cell.findtext("m:v", default="", namespaces=NS)
        headers = {"".join(filter(str.isalpha, c.get("r"))): text(c) for c in rows[0]}
        required = {"image_id", "filename", "artifact_present", "resolution_status"}
        if not required <= set(headers.values()):
            raise ValueError("Workbook missing required columns")
        output = []
        for row in rows[1:]:
            values = {headers.get("".join(filter(str.isalpha, c.get("r")))): text(c)
                      for c in row if headers.get("".join(filter(str.isalpha, c.get("r")))) in required}
            if not values.get("image_id"):
                continue
            dropped = values.get("resolution_status", "").strip().casefold() == "dropped"
            if dropped:
                label = "dropped"
            else:
                try:
                    number = Decimal(values.get("artifact_present", ""))
                    if number not in (0, 1):
                        raise ValueError()
                    label = int(number)
                except (InvalidOperation, ValueError):
                    raise ValueError(f"Missing/invalid reviewed label at row {row.get('r')}") from None
            output.append({"source_row": int(row.get("r")), "resolution_status": values["resolution_status"],
                           "annotation": {"image_id": values["image_id"], "filename": values["filename"],
                                          "labels": [label], "artifact_present": None if dropped else label,
                                          "status": "dropped" if dropped else "reviewed"}})
        return output


def run(workbook, repo=ROOT):
    workbook, repo = Path(workbook), Path(repo)
    base = repo / "data/annotations"
    records = read_workbook(workbook)
    master = json.loads((base / "master.json").read_text(encoding="utf-8-sig"))
    config = json.loads((base / "processing_config.json").read_text(encoding="utf-8-sig"))
    current = {r["annotation"]["image_id"]: r["annotation"]["filename"] for r in master["annotations"]
               if r["dataset_id"] == config["reference_dataset_id"]}
    ids = [r["annotation"]["image_id"] for r in records]
    if len(ids) != len(set(ids)) or set(ids) != set(current):
        raise ValueError("Workbook IDs must uniquely cover the current image collection")
    for record in records:
        row = record["annotation"]
        if row["filename"] != current[row["image_id"]]:
            raise ValueError(f"Current filename does not match workbook: {row['image_id']}")
    document = {"schema_version": 1, "source": {
        "workbook": workbook.name, "sheet": "labels",
        "sha256": hashlib.sha256(workbook.read_bytes()).hexdigest(),
        "reference_dataset_id": config["reference_dataset_id"],
        "label_meaning": {"0": "no listed artifact", "1": "artifact present", "dropped": "exclude from dataset"},
    }, "reviewed_annotations": sorted(records, key=lambda r: r["annotation"]["image_id"])}
    target = base / "reviewed_labels.json"
    temporary = target.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(document, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(target)
    return merge(base / "raw", base / "master.json")["summary"]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("workbook", type=Path)
    parser.add_argument("--repo", type=Path, default=ROOT)
    args = parser.parse_args()
    try:
        print(json.dumps(run(args.workbook, args.repo), indent=2))
    except (OSError, ValueError) as error:
        parser.exit(1, f"Cannot import reviewed labels: {error}\n")
