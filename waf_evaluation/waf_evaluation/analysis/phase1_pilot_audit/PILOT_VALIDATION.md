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
| Mean latency | 7.343 ms |
| Median latency | 6.518 ms |
| p95 latency | 12.375 ms |
| Sustained throughput | about 290 probes/s |

GET and POST produced the same Phase 1 block counts: 5,776 blocked and 724
bypass candidates for each method.

## Audit result

One SQLi control request was sent before the pilot to verify the audit setup.
The exported named volume therefore contains 13,001 transaction JSON entries
for 13,000 pilot probes plus one control, and one concurrent index file.

| Metric | Value |
|---|---:|
| Raw directory files | 13,002 |
| Raw directory bytes, including index | 56,511,487 |
| Parsed transaction bytes, excluding index | 51,783,192 |
| Transactions with probe index | 13,001 / 13,001 |
| Transactions with CRS rule IDs | 13,001 / 13,001 |
| JSON parse errors | 0 |
| Pilot probe rows joined to audit | 13,000 / 13,000 |
| ZIP archive bytes | 22,626,209 |

`RelevantOnly` still logged essentially every generated SQLi request in this
pilot. It therefore reduces clean traffic but must not be assumed to make the
full audit small.

## Full storage projection

Full canonical scope: 827,400 planned records. URL preflight skips 1,501 GET
records after encoding, so at most 825,899 HTTP requests are sent.

| Projection | Bytes | Approximate |
|---|---:|---:|
| Raw audit at observed rate | 3,590,213,892 | 3.34 GiB |
| Probe CSV | 225,511,816 | 215.1 MiB |
| Working total | 3,815,725,708 | 3.55 GiB |
| Compressed audit archive | 1,437,458,722 | 1.34 GiB |

Free space reported for the target drive during the pilot was 119,648,006,144
bytes, so the projected working set fits with substantial headroom.

## Environment findings

- Docker Desktop cannot reliably bind-mount Google Drive's virtual `H:` drive:
  mounts appear in the container but their contents are empty or changes are
  not reflected back to the host.
- The campaign runner must therefore run on the Windows host through
  `http://localhost:18080/`.
- Audit data is written to Docker named volume `gan-waf_waf_audit`, exported
  after stopping WAF, parsed on local storage, then copied to Google Drive as
  CSV/JSON/ZIP artifacts.
- The raw audit directory is not deleted automatically.

This first pilot used a numeric Host header and consequently triggered CRS rule
920350 on all requests. It is retained as a diagnostic pilot, but the canonical
campaign must use `http://localhost:18080/` so the protocol-enforcement rule
does not confound SQLi anomaly scores.

## Interpretation

A bypass candidate is a request that was not blocked by the WAF. It is not
proof of SQL injection success because the protected backend is an inert echo
service. Payload structure/validity metrics must be consulted before treating a
bypass as an evasive SQLi candidate.
