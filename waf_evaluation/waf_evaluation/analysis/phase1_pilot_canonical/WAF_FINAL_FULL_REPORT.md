# WAF evaluation

## Scope

- Input selection: canonical source manifest generated from `run_index.csv`.
- Source CSV files: 4.
- Generated payload rows: 6,500; duplicates and empty rows preserved.
- Planned probes/records: 13,000.
- HTTP requests actually sent: 13,000.
- WAF image: `owasp/modsecurity-crs@sha256:a7d2e948d26ec310a127b261e4b9010ff2467b9f5f7eaed4921450bb7865ba08`.
- Rule engine and blocking were enabled at CRS paranoia level 1; verbose container audit logging was disabled.

## Overall

- Blocked: 11,552 (88.86%).
- Passed WAF / bypass candidates: 1,448 (11.14%).
- Malformed/rejected requests: 0.
- Network errors: 0.
- GET probes skipped before sending because URL was too long: 0.
- Latency: mean 10.120 ms, median 6.666 ms, p95 13.346 ms.

An HTTP 200 row is a WAF bypass candidate, not proof that the payload
successfully exploited a database. The backend is an inert local echo service.

Block and bypass rates exclude malformed requests, network errors, and
GET probes skipped before sending.

## By campaign

| campaign | Probes | Sent | Blocked | Bypassed | Malformed | Skipped GET | Block rate |
|---|---:|---:|---:|---:|---:|---:|---:|
| phase1_survey | 13,000 | 13,000 | 11,552 | 1,448 | 0 | 0 | 88.86% |

## By method

| method | Probes | Sent | Blocked | Bypassed | Malformed | Skipped GET | Block rate |
|---|---:|---:|---:|---:|---:|---:|---:|
| ctgan | 4,000 | 4,000 | 3,794 | 206 | 0 | 0 | 94.85% |
| gan | 4,000 | 4,000 | 3,684 | 316 | 0 | 0 | 92.10% |
| seqgan_master | 1,000 | 1,000 | 298 | 702 | 0 | 0 | 29.80% |
| smote | 4,000 | 4,000 | 3,776 | 224 | 0 | 0 | 94.40% |

## By family

| family | Probes | Sent | Blocked | Bypassed | Malformed | Skipped GET | Block rate |
|---|---:|---:|---:|---:|---:|---:|---:|
| all | 13,000 | 13,000 | 11,552 | 1,448 | 0 | 0 | 88.86% |

## By ratio

| ratio | Probes | Sent | Blocked | Bypassed | Malformed | Skipped GET | Block rate |
|---|---:|---:|---:|---:|---:|---:|---:|
| Rfull | 13,000 | 13,000 | 11,552 | 1,448 | 0 | 0 | 88.86% |

## By HTTP method

| http_method | Probes | Sent | Blocked | Bypassed | Malformed | Skipped GET | Block rate |
|---|---:|---:|---:|---:|---:|---:|---:|
| GET | 6,500 | 6,500 | 5,776 | 724 | 0 | 0 | 88.86% |
| POST | 6,500 | 6,500 | 5,776 | 724 | 0 | 0 | 88.86% |

## Ten lowest blocking runs

| Campaign | Method | Family | Scenario | Ratio | Variant | Block rate |
|---|---|---|---|---|---|---:|
| phase1_survey | seqgan_master | all | RAW | Rfull | BASE | 29.80% |
| phase1_survey | gan | all | RAW | Rfull | BASE | 92.10% |
| phase1_survey | smote | all | RAW | Rfull | BASE | 94.40% |
| phase1_survey | ctgan | all | RAW | Rfull | BASE | 94.85% |

## Artifacts

- `waf_probe_results.csv`: one row per HTTP probe.
- `waf_summary.json`: campaign-level status and latency.
- `waf_analysis.json`: machine-readable analysis.
- `waf_breakdown_by_run.csv`: canonical run key dimensions, GET and POST combined.
- `waf_breakdown_by_run_http.csv`: canonical run key dimensions split by GET/POST.
- Probe result SHA-256: `0be260dd90c186142ba7142184ba36d3d71ff129fec0b741d30d501cd0a8b70b`.
