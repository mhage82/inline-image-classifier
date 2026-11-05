# Annotation integration

Website submissions arrive in `data/annotations/raw/`. These are the original
records; the merge script never edits them. Run from the repository root:

```sh
python scripts/merge_annotations.py
python -m unittest discover -s tests -p 'test_merge_annotations.py'
```

No packages or extra tokens are needed. The output is
`data/annotations/master.json`, rebuilt from every raw JSON (including nested
folders). Rebuilding reflects additions, edits, and removals without appending
duplicates. Identical submission IDs with identical contents count once;
conflicting copies or malformed submissions fail without replacing the master.

## Master format

- `summary`: submission, annotation, unique-image, and overlapping-image counts,
  plus submission counts per dataset.
- `submissions`: original submission metadata (including original submission
  timestamps and any answer digest), source filenames, and annotation counts.
- `annotations`: one entry per submitted answer. Each entry includes submission,
  dataset, group, group version, annotator, guideline version, and submission time.
  Its `annotation` field contains the unchanged original image answer, including
  the original filename, labels, timing, and display provenance when available.

Overlapping images keep all submitted judgments. No voting, accept/reject
decisions, or training split is applied. Use `image_id` rather than filenames to
identify the same image. Old datasets remain identifiable by `dataset_id`; to
exclude retired submissions, move them outside `raw/` (for example to
`data/annotations/archive/`). The script does not guess which dataset is current.
Output is deterministic; rerunning with unchanged inputs creates no new commit.

## GitHub automation

`.github/workflows/merge-annotations.yml` runs on pushes to `main` affecting raw
JSON files, the merge script, its tests, or the workflow. It can also be run from
Actions > Build master annotations > Run workflow. It tests the merger, rebuilds
the master, and commits only the master JSON using the built-in `GITHUB_TOKEN`.
The website's personal access token stays in Vercel; no extra repository secret
is needed for this workflow.

Runs are serialized. If another submission arrives during a push, the workflow
fetches the latest branch and regenerates before retrying (up to five attempts).
Its own master-only commit is outside the trigger paths. All hard resets occur
only in the disposable Actions checkout, never in your local repository.

Commit and push the script, tests, workflow, documentation, and generated master
to activate it. The initial workflow push also triggers a rebuild. GitHub Actions
must be enabled. Repository/organization policies and branch protection must
permit the Actions token to push to `main`; if they prohibit it, adjust that
policy or use a pull-request publishing workflow instead. A failed workflow is
visible under the repository's Actions tab; raw submissions remain untouched.


## Older student exports

`scripts/import_student_exports.py` matches older browser exports by original
`image_id` against a selected dataset in the master. It never matches by filename.
It keeps the old dataset/group context and each answer, replaces `filename` with
the current filename, and records `original_filename` and import provenance.
The export time is used as `submitted_at`, explicitly identified as export time,
since these exports do not have a server submission timestamp.

Original bytes are archived under `data/annotations/archive/student_exports/`.
Normalized submissions are saved under `data/annotations/raw/student_exports/`,
so the normal merge workflow retains them on future runs. Imported submission
IDs are deterministic; repeating the same import does not duplicate answers.
The importer excludes Subas Subedi by export filename or annotator name by
default. This exclusion applies to importing exports; existing raw submissions
are preserved. An import audit is written to
`data/annotations/reports/student_export_import.json`.

Run a preview, then repeat with `--apply` to write:

```sh
python scripts/import_student_exports.py --source PATH_TO_EXPORTS --reference-dataset study-f910f839701b6cf92926
```

The current import added 271 answers from six exports covering 111 images.
All 111 original image hashes were verified against the current source files.
All 271 answers required updated filenames. Fifteen Subas export files were
excluded, and all existing master answers were retained. These are separate
judgments for agreement/review; no older judgment overrides a newer one.


## One record per image and binary targets

Run `python scripts/process_annotations.py` after merging. The GitHub workflow
now runs it after each merge and commits its generated outputs too.

- `data/annotations/processed/images.json`: exactly one record for each image in
  the configured reference dataset, including all original answers and votes.
- `data/annotations/processed/labels.csv`: image ID, current filename, binary
  target, resolution status, and distinct annotator count.
- `data/annotations/reports/processing_summary.json`: counts and evidence quality.
- `data/annotations/reports/review_queue.csv`: unresolved binary decisions.

The task is artifact presence: 1 = at least one of the five categories present,
0 = explicitly no listed artifact, and null/blank = unresolved. This does not
mean usable/unusable or accept/reject. Never treat blank targets as zero.

`processing_config.json` selects the current dataset and manual-review policy.
Only its image IDs and current filenames define the processed collection.
Older datasets' answers contribute when they match those IDs. Names are never
used as image identities. Annotator names are compared with whitespace trimmed
and case folded; aliases such as student01 and student-01 are not assumed to be
the same person. Same-person repeated answers across groups count as one vote.
Conflicting answers from the same person become an uncertain vote.

Under the selected review policy, every person's binary answer must be certain
and agree to assign a provisional target automatically. Otherwise the image is
queued for manual review. Images with one person are explicitly marked
`single_annotator`, not multi-person consensus. All existing contributors,
including group members already in the master, remain visible. Five-category
`label_flags` are conservative consensus values and can be null even when the
binary target agrees. No category majority votes are silently inferred.

### Record manual decisions

Copy `review_queue.csv` to a separate working CSV outside the generated reports
folder before editing: generated reports are replaced on every run. For each
reviewed image, fill in `artifact_present` (0 or 1), `reviewer`, and `review_note`.
Leave targets blank for images still awaiting review. Then run:

```sh
python scripts/process_annotations.py --decisions-csv PATH_TO_REVIEWED_CSV
```

This validates decisions, records them in `data/annotations/adjudications.json`,
and rebuilds outputs. Commit that file along with generated outputs. Future
workflow runs retain these explicit decisions. Do not edit processed JSON or
labels.csv directly; changes there will be replaced on rebuild. Original
student answers and master.json are never modified by the processor.

This step does not create train/test splits, compute chance-corrected agreement,
or upload to Kaggle. Finalize reviews and inspect class counts before choosing
the competition metric and splitting images by unique image ID.


### Annotator choices for agreement

`processed/labels.csv` includes choices for every image, including consensus,
review-required, single-annotator, and adjudicated rows. `reviewer_choices` is a
human-readable list of annotator names and binary choices. `annotator_votes`
contains JSON with each person's binary choice and five-category flags. Columns
named `annotator::<name>::artifact_present` form an image-by-annotator matrix.
Values are 1 (artifact), 0 (none), or blank (missing/uncertain/conflicting).
The readable choices and JSON distinguish abstention from no answer.

`processed/annotator_votes.csv` has one row per image and distinct annotator,
with binary and category choices, vote_status, and the original answer count.
Repeated answers from one person are combined by the existing processing policy.
Use this table or the annotator columns for agreement, not the final artifact
target. Category agreement may differ even when binary judgments agree.
Manual adjudication changes the final target, never the individual votes.

For agreement calculations, retain both consensus and review-required images;
filtering only one group would bias the result. Missing/uncertain/conflicting
ratings must not be converted to zero. Only compare people on shared images.
Do not feed reviewer columns or final labels to the image classifier as inputs.
These exports prepare the ratings; they do not compute an agreement score.


### Reviewed Excel labels in the master

`data/annotations/reviewed_labels.json` is the persistent source of the final
Excel decisions. `python scripts/merge_annotations.py` automatically includes
it in master.json as `reviewed_annotations`, separate from the unchanged
individual student `annotations`. Reviewed entries use `annotation.labels`
containing exactly one value: numeric 0, numeric 1, or string "dropped". Original
student entries continue to use artifact-category labels. Use the reviewed
layer for final targets and original votes for agreement. Never mix these two
label vocabularies when computing agreement.

The reviewed layer records workbook filename, SHA-256, worksheet, source row,
current filename, and the workbook resolution status. It does not invent an
individual reviewer identity. Import again after editing Excel with:

```sh
python scripts/import_reviewed_labels.py "data/annotations/processed/Reviewed_labels_updated.xlsx"
python scripts/process_annotations.py
```

The import requires every current image ID exactly once, matching current
filenames, and a valid 0/1 label for every non-dropped image. Dropped status
takes precedence over the sheet's N/A target. The selected workbook takes
precedence over earlier adjudications for final targets. Processed records
retain all images, but dropped records have resolution_status=dropped and a
blank artifact_present; always filter them out before training or splitting.
They are excluded from the review queue. Only actual unresolved images enter
that queue. Individual votes remain untouched in all outputs.

The workflow watches reviewed_labels.json and retains the reviewed layer on
every rebuild. It does not silently reimport an edited workbook; run the
import command and commit reviewed_labels.json after workbook changes.
