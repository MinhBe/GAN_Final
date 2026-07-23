from __future__ import annotations

import argparse
import csv
import ipaddress
import json
import math
import random
import statistics
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

SEED = 88


class NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, request, file_pointer, code, message, headers, new_url):
        return None


def validate_target(target_url: str, allow_remote: bool = False) -> str:
    parsed = urlsplit(str(target_url))
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("Target URL must use http or https")
    if not parsed.hostname:
        raise ValueError("Target URL must include a hostname")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("Target URL must not include credentials")
    if parsed.fragment:
        raise ValueError("Target URL must not include a fragment")
    try:
        parsed.port
    except ValueError as exc:
        raise ValueError("Target URL contains an invalid port") from exc
    if allow_remote:
        return target_url
    hostname = parsed.hostname.lower()
    if hostname == "localhost":
        return target_url
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError as exc:
        raise ValueError("Non-loopback target rejected; pass --allow-remote to override") from exc
    if not address.is_loopback:
        raise ValueError("Non-loopback target rejected; pass --allow-remote to override")
    return target_url


def load_payloads(path: Path, column: str = "payload") -> list[tuple[int, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames or column not in reader.fieldnames:
            raise ValueError(f"Input CSV must contain column {column!r}")
        return [(index, row.get(column) or "") for index, row in enumerate(reader)]


def select_payloads(
    payloads: list[tuple[int, str]],
    seed: int = SEED,
    max_payloads: int | None = None,
) -> list[tuple[int, str]]:
    if seed != SEED:
        raise ValueError(f"WAF evaluation seed must be {SEED}")
    if max_payloads is not None and max_payloads < 0:
        raise ValueError("max_payloads must not be negative")
    selected = list(payloads)
    random.Random(seed).shuffle(selected)
    if max_payloads is not None:
        selected = selected[:max_payloads]
    return selected


def build_probe_request(target_url: str, payload: str, method: str, parameter: str) -> Request:
    normalized_method = method.upper()
    headers = {
        "Accept": "application/json",
        "User-Agent": "GAN-SQLi-WAF-Evaluator/1.0",
        "X-WAF-Evaluation": "1",
    }
    if normalized_method == "GET":
        parsed = urlsplit(target_url)
        query = parse_qsl(parsed.query, keep_blank_values=True)
        query.append((parameter, payload))
        url = urlunsplit((parsed.scheme, parsed.netloc, parsed.path or "/", urlencode(query), ""))
        return Request(url, headers=headers, method="GET")
    if normalized_method == "POST":
        body = urlencode({parameter: payload}).encode("utf-8")
        headers["Content-Type"] = "application/x-www-form-urlencoded; charset=utf-8"
        return Request(target_url, data=body, headers=headers, method="POST")
    raise ValueError(f"Unsupported probe method {method!r}")


def _call_opener(opener, request: Request, timeout: float):
    if hasattr(opener, "open"):
        return opener.open(request, timeout=timeout)
    return opener(request, timeout=timeout)


def send_probe(
    request: Request,
    timeout: float,
    blocked_statuses: set[int],
    opener,
) -> dict[str, object]:
    started = perf_counter()
    status: int | None = None
    error = ""
    try:
        with _call_opener(opener, request, timeout) as response:
            raw_status = getattr(response, "status", None)
            status = int(raw_status if raw_status is not None else response.getcode())
            response.read(4096)
    except HTTPError as exc:
        status = int(exc.code)
        error = f"HTTP {exc.code}"
        try:
            exc.read(4096)
        except Exception:
            pass
    except (URLError, TimeoutError, OSError) as exc:
        error = str(exc.reason) if isinstance(exc, URLError) else str(exc)
    latency_ms = (perf_counter() - started) * 1000.0
    return {
        "status": status,
        "blocked": status in blocked_statuses if status is not None else False,
        "latency_ms": round(latency_ms, 3),
        "error": error,
    }


def summarize(
    records: list[dict[str, object]],
    input_payload_count: int,
    selected_payload_count: int,
    target_url: str,
    seed: int,
    blocked_statuses: set[int],
    started_at: str,
    finished_at: str,
) -> dict[str, object]:
    blocked_count = sum(bool(row["blocked"]) for row in records)
    error_count = sum(bool(row["error"]) and row["status"] is None for row in records)
    status_counts = Counter("network_error" if row["status"] is None else str(row["status"]) for row in records)
    method_summary: dict[str, dict[str, object]] = {}
    for method in sorted({str(row["method"]) for row in records}):
        rows = [row for row in records if row["method"] == method]
        method_blocked = sum(bool(row["blocked"]) for row in rows)
        method_summary[method] = {
            "probes": len(rows),
            "blocked": method_blocked,
            "blocked_rate": method_blocked / len(rows) if rows else 0.0,
        }
    latencies = sorted(float(row["latency_ms"]) for row in records)
    p95_index = max(0, math.ceil(len(latencies) * 0.95) - 1) if latencies else 0
    return {
        "schema_version": 1,
        "seed": seed,
        "target_url": target_url,
        "blocked_statuses": sorted(blocked_statuses),
        "input_payload_count": input_payload_count,
        "selected_payload_count": selected_payload_count,
        "probe_count": len(records),
        "blocked_count": blocked_count,
        "blocked_rate": blocked_count / len(records) if records else 0.0,
        "network_error_count": error_count,
        "status_counts": dict(sorted(status_counts.items())),
        "by_method": method_summary,
        "latency_ms": {
            "mean": statistics.fmean(latencies) if latencies else 0.0,
            "median": statistics.median(latencies) if latencies else 0.0,
            "p95": latencies[p95_index] if latencies else 0.0,
        },
        "started_at": started_at,
        "finished_at": finished_at,
    }


def write_results(records: list[dict[str, object]], summary: dict[str, object], out_dir: Path) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / "waf_probe_results.csv"
    json_path = out_dir / "waf_summary.json"
    fields = [
        "probe_index",
        "source_row",
        "method",
        "payload",
        "url",
        "status",
        "blocked",
        "latency_ms",
        "error",
    ]
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(records)
    json_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return csv_path, json_path


def evaluate(
    input_csv: Path,
    target_url: str,
    out_dir: Path,
    methods: list[str] | tuple[str, ...] = ("GET", "POST"),
    parameter: str = "payload",
    timeout: float = 5.0,
    blocked_statuses: set[int] | None = None,
    seed: int = SEED,
    max_payloads: int | None = None,
    allow_remote: bool = False,
    opener=None,
) -> tuple[list[dict[str, object]], dict[str, object]]:
    target_url = validate_target(target_url, allow_remote=allow_remote)
    if timeout <= 0:
        raise ValueError("timeout must be positive")
    if not parameter:
        raise ValueError("parameter must not be empty")
    normalized_methods = list(dict.fromkeys(str(method).upper() for method in methods))
    if not normalized_methods or any(method not in {"GET", "POST"} for method in normalized_methods):
        raise ValueError("methods must contain GET, POST, or both")
    effective_blocked_statuses = set(blocked_statuses or {403})
    if any(status < 100 or status > 599 for status in effective_blocked_statuses):
        raise ValueError("blocked statuses must be valid HTTP status codes")
    payloads = load_payloads(input_csv)
    selected = select_payloads(payloads, seed=seed, max_payloads=max_payloads)
    effective_opener = opener or build_opener(NoRedirectHandler())
    started_at = datetime.now(timezone.utc).isoformat()
    records: list[dict[str, object]] = []
    for source_row, payload in selected:
        for method in normalized_methods:
            request = build_probe_request(target_url, payload, method, parameter)
            result = send_probe(request, timeout, effective_blocked_statuses, effective_opener)
            records.append(
                {
                    "probe_index": len(records),
                    "source_row": source_row,
                    "method": method,
                    "payload": payload,
                    "url": request.full_url,
                    **result,
                }
            )
    finished_at = datetime.now(timezone.utc).isoformat()
    summary = summarize(
        records,
        input_payload_count=len(payloads),
        selected_payload_count=len(selected),
        target_url=target_url,
        seed=seed,
        blocked_statuses=effective_blocked_statuses,
        started_at=started_at,
        finished_at=finished_at,
    )
    write_results(records, summary, out_dir)
    return records, summary


def parse_statuses(value: str) -> set[int]:
    try:
        return {int(item.strip()) for item in value.split(",") if item.strip()}
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Blocked statuses must be comma-separated integers") from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--target-url", default="http://127.0.0.1:8080/")
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--methods", nargs="+", choices=["GET", "POST"], default=["GET", "POST"])
    parser.add_argument("--parameter", default="payload")
    parser.add_argument("--timeout", type=float, default=5.0)
    parser.add_argument("--blocked-statuses", type=parse_statuses, default={403})
    parser.add_argument("--seed", type=int, choices=[SEED], default=SEED)
    parser.add_argument("--max-payloads", type=int, default=None)
    parser.add_argument("--allow-remote", action="store_true")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    _, summary = evaluate(
        input_csv=args.input,
        target_url=args.target_url,
        out_dir=args.out_dir,
        methods=args.methods,
        parameter=args.parameter,
        timeout=args.timeout,
        blocked_statuses=args.blocked_statuses,
        seed=args.seed,
        max_payloads=args.max_payloads,
        allow_remote=args.allow_remote,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
