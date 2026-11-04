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
