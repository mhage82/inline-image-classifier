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
