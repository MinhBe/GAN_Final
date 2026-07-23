
# Migration and publication plan

## Completed

1. Preserved `GAN_for_SQLi` as the canonical root.
2. Namespaced earlier source/result trees under `legacy/`.
3. Copied every source file below 95,000,000 bytes.
4. Excluded files at or above the threshold and recorded them in provenance.
5. Preserved the original README and `.gitignore`.
6. Generated and reconciled source, target, exclusion, artifact and run
   registries.
7. Added Git LFS rules for models, archives, serialized objects, datasets and
   legacy result CSV files.
8. Scanned text files for credential patterns and hard-coded runtime paths.
9. Parsed or opened 48 Python, 4,559 JSON, 2,802 CSV, 13 ZIP and 648 PyTorch
   checkpoint files without an unresolved artifact error.
10. Passed 51 unit tests, Docker Compose validation and core-module Python
    compilation.
11. Initialized local Git and Git LFS, committed the consolidated archive and
    passed both `git fsck --full` and `git lfs fsck`.
12. Reconciled the final target inventory against the worktree with zero
    missing or extra paths.

## Remaining before a public GitHub release

1. Select a project software license and document ownership approval.
2. Verify that the original dataset and generated SQLi payloads may legally be
   redistributed under the selected repository visibility and license.
3. Create or select a GitHub remote. Use a private repository for the first
   push while the two licensing gates remain unresolved.
4. Confirm that the GitHub account/organization has enough Git LFS quota for
   1,729 unique objects totaling 2,777,527,511 local bytes.
5. Decide whether notebook cell outputs and all historical payload/result
   snapshots are suitable for the intended audience.
6. Re-run the secret scan immediately before pushing even though the current
   scan has zero candidates.
7. Plan the initial transfer so normal Git and LFS uploads remain within the
   platform's current per-file, per-push and quota limits.
8. Clone the private remote into a clean directory, fetch all LFS objects and
   repeat the validation before changing repository visibility to public.

Hard-coded Colab, Drive and Windows paths are cataloged in
`provenance/portability_path_audit.csv`. They do not invalidate this historical
archive, but the canonical execution path should be made configurable before
claiming one-command reproducibility.

## Publication gates

| Gate | Current state | Evidence or next action |
|---|---|---|
| No unresolved secret candidate | PASS | `secret_scan_candidates.csv` has 0 rows |
| Project and dataset license approved | BLOCKED | Owner/legal decision required |
| No worktree file at or above 95 MB | PASS | Final inventory has 0 violations |
| All LFS pointers and objects resolve | PASS | `git lfs fsck` passed |
| Tests and artifact checks pass | PASS | `test_results.json` and `validation_summary.json` |
| Source and destination reconcile | PASS | 12,758 copied, 2 excluded, 0 errors |
| GitHub remote selected | BLOCKED | No remote is configured |
| Clean remote clone validated | PENDING | Possible only after the first private push |
