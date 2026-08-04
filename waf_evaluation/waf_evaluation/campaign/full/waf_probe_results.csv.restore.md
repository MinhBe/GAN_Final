# Restore `waf_probe_results.csv`

The full campaign is committed as three independently valid CSV files, each
below 90 MiB:

- `waf_probe_results.part001.csv`
- `waf_probe_results.part002.csv`
- `waf_probe_results.part003.csv`

Each part repeats the same 13-column header. Together they contain 827,400
logical data rows in their original order. Verify their sizes, row counts and
SHA-256 values against `waf_probe_results.parts.json`.

To reconstruct the byte-identical original, write part 1 in full, then append
parts 2 and 3 without their first header record. The reconstructed file must
have SHA-256:

```text
1e2472a9bbba53ee33b1084fea1a8deda9fb0f59168b943b7d5cdca959790cc7
```

A lossless ZIP copy is also retained as
`waf_probe_results.csv.zip.part001`. Its checksums are recorded in
`waf_probe_results.csv.zip.sha256`. It can be restored on Windows with:

```bat
copy /b waf_probe_results.csv.zip.part001 waf_probe_results.csv.zip
tar -xf waf_probe_results.csv.zip
```
