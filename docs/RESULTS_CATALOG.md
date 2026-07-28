
# Results catalog

This catalog indexes every directory containing either `run_manifest.json` or
`generated_payloads.csv` in the unified repository.

- Detected run directories: **1082**
- Run manifests: **1069**
- Generated payload artifacts: **1033**
- Quality metrics: **1018**
- Random Forest metrics: **1018**
- Generator models: **260**
- Discriminator models: **185**

## By phase

| Phase | Detected run directories |
| --- | --- |
| phase1 | 30 |
| phase2a | 288 |
| phase2b | 544 |
| phase2b_batch6x | 13 |
| phase3 | 207 |

## By method

| Method | Detected run directories |
| --- | --- |
| CTGAN | 225 |
| SMOTE | 225 |
| SeqGAN cải tiến (`seqgan_improved`) | 220 |
| SeqGAN cơ sở (`seqgan_master`) | 184 |
| Vanilla GAN | 228 |

## Manifest status

| Manifest status | Runs |
| --- | --- |
| (blank) | 13 |
| completed | 1018 |
| running | 51 |

The machine-readable registry is
[`provenance/run_registry.csv`](../provenance/run_registry.csv). Repeated runs
are retained intentionally because this repository preserves experimental
history. Canonical selection and quality ranking must be performed from
manifests and metrics, not from directory modification time alone.
