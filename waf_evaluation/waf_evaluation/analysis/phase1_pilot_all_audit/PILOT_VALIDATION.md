# Phase 1 Docker WAF pilot validation

Date: 2026-07-21  
Scope: `phase1_survey`, 4 completed runs, 6,500 payload rows  
WAF: `owasp/modsecurity-crs@sha256:a7d2e948d26ec310a127b261e4b9010ff2467b9f5f7eaed4921450bb7865ba08`

## Campaign result

| Metric | Value |
|---|---:|
| Planned probe records | 13,000 |
| HTTP requests sent | 13,000 |
| Blocked | 11,552 (88.8615%) |
| Bypass candidates | 1,448 (11.1385%) |
| Malformed requests | 0 |
| Network errors | 0 |
| Skipped GET-too-long | 0 |
| Mean latency | 10.605 ms |
| Median latency | 7.146 ms |
| p95 latency | 13.697 ms |
| End-to-end throughput | about 247 probes/s |

GET and POST produced the same Phase 1 block counts: 5,776 blocked and 724
bypass candidates for each method.

## Audit result

The canonical all-audit pilot retained relevant `200`, `403`, and `5xx`
transactions. The exported named volume contains 13,004 transaction JSON
entries: 13,000 pilot probes plus four health checks, and one concurrent index
file.

| Metric | Value |
|---|---:|
| Raw directory files | 13,005 |
| Raw directory bytes, including index | 47,773,388 |
| Parsed transaction bytes, excluding index | 43,044,609 |
| Transactions with probe index | 13,000 / 13,004 |
| Pilot probes with an audit transaction | 13,000 / 13,000 |
| Pilot probes with matched CRS rule IDs | 11,552 / 13,000 |
| JSON parse errors | 0 |
| Pilot probe rows joined to audit | 13,000 / 13,000 |
| ZIP archive bytes | 20,134,595 |

All 11,552 blocked probes have rule IDs. The 1,448 bypass candidates are still
retained as audit transactions but have no matched blocking rule, as expected.
CRS rule `920350` occurred zero times, confirming that the canonical
`localhost` target removed the numeric-Host confounder.

## Full storage projection

Full canonical scope: 827,400 planned records. URL preflight skips 1,501 GET
records after encoding, so at most 825,899 HTTP requests are sent.

| Projection | Bytes | Approximate |
|---|---:|---:|
| Raw audit at observed rate | 3,035,076,414 | 2.83 GiB |
| Probe CSV | 225,559,232 | 215.1 MiB |
| Working total | 3,260,635,646 | 3.04 GiB |
| Compressed audit archive | 1,279,164,760 | 1.19 GiB |

Free space reported for the target drive during the pilot was 119,540,867,072
bytes, so the projected working set fits with substantial headroom.

## Environment findings

- Docker Desktop cannot reliably bind-mount Google Drive's virtual `H:` drive:
  mounts appear in the container but their contents are empty or changes are
  not reflected back to the host.
- The campaign runner must therefore run on the Windows host through
  `http://localhost:18080/`.
- Audit data is written to a Docker named volume, exported after stopping WAF,
  parsed on local storage, then copied to Google Drive as CSV/JSON/ZIP
  artifacts.
- The raw audit directory is not deleted automatically.
- The canonical pilot used `http://localhost:18080/`; an earlier numeric-Host
  diagnostic pilot remains separately archived and must not be used for the
  final academic comparison.

## Interpretation

A bypass candidate is a request that was not blocked by the WAF. It is not
proof of SQL injection success because the protected backend is an inert echo
service. Payload structure/validity metrics must be consulted before treating a
bypass as an evasive SQLi candidate.
