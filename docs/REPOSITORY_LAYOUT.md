
# Repository layout

```text
.
├── common/                  # Canonical shared research code
├── configs/                 # Canonical experiment configuration
├── data/                    # Canonical prepared/source data
├── docker/                  # WAF evaluation environment
├── export/                  # Export and evaluation utilities
├── models/                  # Canonical model implementations
├── scripts/                 # Canonical orchestration scripts
├── tests/                   # Canonical tests
├── result*/                 # Canonical/current result trees preserved as-is
├── legacy/
│   ├── source_trees/        # Earlier code/result snapshots, namespaced
│   ├── root_result/         # Standalone Drive result exports
│   └── root_files/          # Eligible root ZIP snapshots
├── provenance/              # Source-to-target maps and machine inventories
├── docs/                    # Human-readable migration/result documentation
└── reports/                 # Future consolidated analytical reports
```

The canonical code is copied from `GAN_for_SQLi`. Earlier trees are not merged
line-by-line into canonical code; they remain immutable under `legacy/` until
their unique patches are reviewed and promoted through normal commits.
