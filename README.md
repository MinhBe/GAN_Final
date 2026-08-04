
# GAN for SQLi — unified research repository

This staging repository consolidates the canonical code, historical code
snapshots, notebooks, model artifacts and experiment results previously spread
across `H:\My Drive\GAN`.

## Migration snapshot

- Source files surveyed: **12,760**
- Files eligible under 95,000,000 bytes: **12,758**
- Files excluded by the 95 MB policy: **2**
- Final unified worktree files: **12,784**
- Final inventory rows: **12,783** (the inventory excludes itself)
- Detected experimental run directories: **1082**
- Secret-scan candidates requiring review: **0**
- Files containing environment-specific paths: **1132**
- Git LFS-tracked paths: **3,531**
- Unique local Git LFS objects: **1,729** (**2,777,527,511 bytes**)

## Source namespaces

| Namespace | Files | Size |
| --- | --- | --- |
| GAN_SQLi | 4201 | 171.3 MiB |
| GAN_SQLi_Colab | 4784 | 2498.0 MiB |
| GAN_SQLi_Colab_run_info_copy_20260714 | 2888 | 125.3 MiB |
| GAN_for_SQLi_canonical | 700 | 361.2 MiB |
| root_archives | 4 | 125.6 MiB |
| root_result_exports | 187 | 56.3 MiB |

## Canonical research design

The canonical implementation is the former `GAN_for_SQLi` tree. It defines
Phase 1, Phase 2A, Phase 2B, Phase 3 and final comparison across SMOTE,
Vanilla GAN, CTGAN, SeqGAN cơ sở and SeqGAN cải tiến. The original detailed
README is preserved at
[`docs/ORIGINAL_GAN_FOR_SQLi_README.md`](docs/ORIGINAL_GAN_FOR_SQLi_README.md).
That preserved file is historical evidence; the current operational README
remains in the canonical source tree and records the corrections below.

## How the experiments were actually run

The experiment history must not be interpreted as one uninterrupted full run.
Execution was staged so that code and training behavior could be checked before
expensive jobs were launched:

| Profile | Generated samples | Main training budget |
| --- | ---: | --- |
| Smoke | 64 | GAN 2 epochs; CTGAN 2; SeqGAN G-pretrain 1, adversarial max 1, rollout 2 |
| Mini | 200 | GAN 15; CTGAN 25; SeqGAN G-pretrain 15, adversarial max 6, rollout 3 |
| Medium SeqGAN | 500 | G-pretrain 60/80, D-pretrain `30 x 3`, adversarial max 60, rollout 8 |
| Full | 2,000 | GAN 100; CTGAN 300; SeqGAN G-pretrain 120/160, D-pretrain `50 x 3`, adversarial max 200, rollout 16 |
| B6X resume | 2,000 | Full schedule, batch 384, checkpoint every 10 epochs, up to 13 resumed jobs in parallel |

Smoke, mini and medium results are diagnostic evidence and are not substituted
for final metrics. Full means the final dataset size and hyperparameter budget;
it does **not** mean that every SeqGAN run must consume all 200 adversarial
epochs.

### Intentional early stopping is not a missing scenario

SeqGAN cải tiến monitors `discriminator_reward_mean`. The default runtime stops
after 3 consecutive adversarial epochs below `0.05` and records
`stop_reason=vanishing_reward`. In console output these values can appear as a
repeated `0.000`/`0.0000`. Continuing such a run was judged unlikely to improve
the model, so it was intentionally stopped and retained as an experimental
result.

Result audits must therefore report `planned_epochs`, `actual_epochs` and
`stop_reason` from `training_metadata.json` and `logs/epoch_metrics.csv`.
Checkpoint filenames alone do not prove the current epoch. A run that used the
full configuration and then triggered this rule is a completed early-terminal
full run, not an omitted family/scenario/ratio/variant.

Phase 2A's historical `1:20` preflight was infeasible for all six scenarios.
The current canonical configuration uses `1:50` without replacement. This data
capacity decision is separate from SeqGAN's reward-based early stopping.

## Final-only WAF campaign

The implemented firewall campaign is deliberately limited to generated data
whose archive entry matches:

```text
result/final/**/generated_payloads.csv
```

Phase 1, 2A, 2B, 3, smoke, mini, medium, checkpoints and B6X recovery outputs
are excluded. The six Final archives contain 96 source CSV files:

```text
4 models x 3 ratios (R100/R200/R500) x 8 frozen family-scenario cells
```

The deterministic aggregation produces one payload-only input file:
[`result/waf/final_full/input/generated_payloads_final_full.csv`](result/waf/final_full/input/generated_payloads_final_full.csv).
It contains 192,000 rows, including 168,283 duplicate rows and 8 empty rows;
none are removed. Its SHA-256 is
`9444a386719235053f773567f03267beb2f8a8d6d0b10f25702e8504482e14d1`.
Source paths, hashes and contiguous row ranges are stored separately in the
source manifest.

Every payload was sent once by `GET` and once by form-encoded `POST` through a
loopback-only ModSecurity/OWASP CRS container. The campaign used CRS 4.25.1,
paranoia level 1, anomaly threshold 5 and seed 88. The exact image digest is:

```text
owasp/modsecurity-crs@sha256:a7d2e948d26ec310a127b261e4b9010ff2467b9f5f7eaed4921450bb7865ba08
```

| Result | Count | Rate |
|---|---:|---:|
| HTTP probes | 384,000 | 100% |
| Blocked (`403`) | 293,840 | 76.52% |
| Passed WAF (`200`) | 90,160 | 23.48% |
| Network errors | 0 | 0% |

| Generator | Probes | Blocked | Passed | Block rate |
|---|---:|---:|---:|---:|
| CTGAN | 96,000 | 95,762 | 238 | 99.75% |
| Vanilla GAN | 96,000 | 95,954 | 46 | 99.95% |
| SeqGAN cơ sở | 96,000 | 6,462 | 89,538 | 6.73% |
| SMOTE | 96,000 | 95,662 | 338 | 99.65% |

An HTTP 200 response is a **WAF bypass candidate**, not proof of successful SQL
injection. The protected backend is an inert local echo service and does not
execute payloads against a database. SeqGAN cơ sở's low block rate must
therefore be interpreted together with SQL structural validity and collapse
metrics; malformed or non-SQL output can also avoid CRS signatures.

Reproducible commands:

```powershell
python scripts/aggregate_waf_input.py `
  --source "result 2/result-20260716T102326Z-1-001.zip" `
  --source "result 2/result-20260716T102410Z-1-001.zip" `
  --source "result 2/result-20260716T102425Z-1-001.zip" `
  --source "result 2/result-20260716T102441Z-1-001.zip" `
  --source "result 2/result-20260716T102317Z-1-001.zip" `
  --source "result 2/result-20260716T102308Z-1-001.zip" `
  --output result/waf/final_full/input/generated_payloads_final_full.csv `
  --expected-files 96 --expected-rows-per-file 2000

$env:WAF_PORT = "18080"
docker compose -p gan-final-waf -f docker/docker-compose.yml up -d --build

python scripts/run_waf_campaign.py `
  --input result/waf/final_full/input/generated_payloads_final_full.csv `
  --target-url http://127.0.0.1:18080/ `
  --out-dir result/waf/final_full/evaluation_full `
  --methods GET POST --workers 16 --retries 2 --checkpoint-every 5000

# The committed full-campaign results are split into three valid CSV files.
# Reconstruct waf_probe_results.csv first as described in:
# waf_evaluation/waf_evaluation/campaign/full/waf_probe_results.csv.restore.md
python scripts/summarize_waf_results.py `
  --results result/waf/final_full/evaluation_full/waf_probe_results.csv `
  --source-manifest result/waf/final_full/input/generated_payloads_final_full_sources.csv `
  --campaign-summary result/waf/final_full/evaluation_full/waf_summary.json `
  --out-dir result/waf/final_full/analysis `
  --waf-image "owasp/modsecurity-crs@sha256:a7d2e948d26ec310a127b261e4b9010ff2467b9f5f7eaed4921450bb7865ba08"
```

See the full report at
[`result/waf/final_full/analysis/WAF_FINAL_FULL_REPORT.md`](result/waf/final_full/analysis/WAF_FINAL_FULL_REPORT.md).

## Start here

- [Repository layout](docs/REPOSITORY_LAYOUT.md)
- [Results catalog](docs/RESULTS_CATALOG.md)
- [Migration and publication plan](docs/MIGRATION_PLAN.md)
- [Provenance records](provenance/README.md)
- [License status](LICENSE_STATUS.md)
- [Security policy](SECURITY.md)

## Publication status

This is a complete, validated local Git/LFS repository, but it has not been
pushed to GitHub. The credential-pattern scan has no candidates. Public
release remains blocked until the project license and dataset/generated-data
redistribution rights are explicitly resolved; a GitHub remote must also be
selected. Keep the first remote private until those publication gates pass.
