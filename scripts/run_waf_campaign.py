from __future__ import annotations

import argparse
import csv
import hashlib
import http.client
import json
import math
import random
import statistics
import threading
from collections import Counter, deque
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

try:
    from scripts.evaluate_waf import SEED, load_payloads, validate_target
except ModuleNotFoundError:
    from evaluate_waf import SEED, load_payloads, validate_target


RESULT_FIELDS = [
    "probe_index",
    "source_row",
    "method",
    "payload",
    "url",
    "status",
    "blocked",
    "latency_ms",
    "attempts",
    "error",
]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class PersistentHttpProbe:
    def __init__(
        self,
        target_url: str,
        parameter: str,
        timeout: float,
        blocked_statuses: set[int],
        retries: int,
    ) -> None:
        parsed = urlsplit(target_url)
        self.parsed = parsed
        self.parameter = parameter
        self.timeout = timeout
        self.blocked_statuses = blocked_statuses
        self.retries = retries
        self.connection: http.client.HTTPConnection | http.client.HTTPSConnection | None = None

    def _connection(self):
        if self.connection is None:
            host = self.parsed.hostname or ""
            port = self.parsed.port
            connection_class = (
                http.client.HTTPSConnection
                if self.parsed.scheme == "https"
                else http.client.HTTPConnection
            )
            self.connection = connection_class(host, port=port, timeout=self.timeout)
        return self.connection

    def _close(self) -> None:
        if self.connection is not None:
            try:
                self.connection.close()
            finally:
                self.connection = None

    def request(self, payload: str, method: str) -> dict[str, object]:
        normalized_method = method.upper()
        headers = {
            "Accept": "application/json",
            "User-Agent": "GAN-SQLi-WAF-Campaign/1.0",
            "X-WAF-Evaluation": "1",
            "Connection": "keep-alive",
        }
        base_path = self.parsed.path or "/"
        if normalized_method == "GET":
            query = parse_qsl(self.parsed.query, keep_blank_values=True)
            query.append((self.parameter, payload))
            encoded_query = urlencode(query)
            request_path = urlunsplit(("", "", base_path, encoded_query, ""))
            record_url = urlunsplit(
                (
                    self.parsed.scheme,
                    self.parsed.netloc,
                    base_path,
                    encoded_query,
                    "",
                )
            )
            body = None
        elif normalized_method == "POST":
            request_path = urlunsplit(("", "", base_path, self.parsed.query, ""))
            body = urlencode({self.parameter: payload}).encode("utf-8")
            headers["Content-Type"] = "application/x-www-form-urlencoded; charset=utf-8"
            headers["Content-Length"] = str(len(body))
            record_url = urlunsplit(
                (
                    self.parsed.scheme,
                    self.parsed.netloc,
                    base_path,
                    self.parsed.query,
                    "",
                )
            )
        else:
            raise ValueError(f"Unsupported method: {method}")

        started = perf_counter()
        error = ""
        status: int | None = None
        attempts = 0
        for attempt in range(self.retries + 1):
            attempts = attempt + 1
            try:
                connection = self._connection()
                connection.request(normalized_method, request_path, body=body, headers=headers)
                response = connection.getresponse()
                status = int(response.status)
                response.read()
                error = ""
                break
            except (OSError, TimeoutError, http.client.HTTPException) as exc:
                error = str(exc)
                self._close()
        latency_ms = (perf_counter() - started) * 1000.0
        return {
            "url": record_url,
            "status": status,
            "blocked": status in self.blocked_statuses if status is not None else False,
            "latency_ms": round(latency_ms, 3),
            "attempts": attempts,
            "error": error,
        }


def load_completed(csv_path: Path) -> int:
    if not csv_path.exists():
        return 0
    completed = 0
    with csv_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != RESULT_FIELDS:
            raise ValueError(
                f"Existing result schema does not match campaign schema: {reader.fieldnames}"
            )
        for completed, row in enumerate(reader, start=1):
            expected = completed - 1
            if int(row["probe_index"]) != expected:
                raise ValueError(
                    f"Existing result is not a contiguous prefix at probe {expected}"
                )
    return completed


def campaign_config(
    input_csv: Path,
    target_url: str,
    methods: list[str],
    parameter: str,
    timeout: float,
    blocked_statuses: set[int],
    seed: int,
    max_payloads: int | None,
    workers: int,
    retries: int,
    input_hash: str,
    selected_payload_count: int,
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "input_csv": str(input_csv),
        "input_csv_sha256": input_hash,
        "target_url": target_url,
        "methods": methods,
        "parameter": parameter,
        "timeout": timeout,
        "blocked_statuses": sorted(blocked_statuses),
        "seed": seed,
        "max_payloads": max_payloads,
        "workers": workers,
        "retries": retries,
        "selected_payload_count": selected_payload_count,
        "total_probe_count": selected_payload_count * len(methods),
    }


def verify_resume_state(state_path: Path, expected: dict[str, object]) -> dict[str, object]:
    if not state_path.exists():
        raise ValueError("--resume requires an existing campaign_state.json")
    state = json.loads(state_path.read_text(encoding="utf-8"))
    previous = state.get("config")
    if previous != expected:
        raise ValueError("Resume config does not match existing campaign_state.json")
    return state


def save_state(
    state_path: Path,
    config: dict[str, object],
    started_at: str,
    completed_probe_count: int,
    rate: float,
) -> None:
    total = int(config["total_probe_count"])
    remaining = max(0, total - completed_probe_count)
    state = {
        "schema_version": 1,
        "config": config,
        "started_at": started_at,
        "updated_at": utc_now(),
        "completed_probe_count": completed_probe_count,
        "remaining_probe_count": remaining,
        "progress": completed_probe_count / total if total else 1.0,
        "recent_rate_probes_per_second": rate,
        "eta_seconds": remaining / rate if rate > 0 else None,
        "status": "completed" if completed_probe_count == total else "running",
    }
    state_path.write_text(
        json.dumps(state, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def summarize_results(
    result_csv: Path,
    config: dict[str, object],
    input_payload_count: int,
    started_at: str,
    finished_at: str,
) -> dict[str, object]:
    status_counts: Counter[str] = Counter()
    method_counts: dict[str, Counter[str]] = {}
    latencies: list[float] = []
    blocked_count = 0
    network_error_count = 0
    probe_count = 0
    with result_csv.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            probe_count += 1
            blocked = row["blocked"].casefold() == "true"
            blocked_count += int(blocked)
            network_error = row["status"] == ""
            network_error_count += int(network_error)
            status_key = "network_error" if network_error else row["status"]
            status_counts[status_key] += 1
            method = row["method"]
            counts = method_counts.setdefault(method, Counter())
            counts["probes"] += 1
            counts["blocked"] += int(blocked)
            counts["network_errors"] += int(network_error)
            latencies.append(float(row["latency_ms"]))
    by_method = {
        method: {
            **dict(counts),
            "eligible_requests": counts["probes"] - counts["network_errors"],
            "not_blocked": counts["probes"] - counts["network_errors"] - counts["blocked"],
            "blocked_rate": counts["blocked"] / (counts["probes"] - counts["network_errors"])
            if counts["probes"] - counts["network_errors"] else 0.0,
            "waf_not_blocked_rate": (counts["probes"] - counts["network_errors"] - counts["blocked"])
            / (counts["probes"] - counts["network_errors"])
            if counts["probes"] - counts["network_errors"] else 0.0,
        }
        for method, counts in sorted(method_counts.items())
    }
    latencies.sort()
    p95_index = max(0, math.ceil(len(latencies) * 0.95) - 1) if latencies else 0
    return {
        "schema_version": 3,
        **config,
        "input_payload_count": input_payload_count,
        "probe_count": probe_count,
        "eligible_request_count": probe_count - network_error_count,
        "blocked_count": blocked_count,
        "waf_not_blocked_count": probe_count - network_error_count - blocked_count,
        "blocked_rate": blocked_count / (probe_count - network_error_count)
        if probe_count - network_error_count else 0.0,
        "waf_not_blocked_rate": (probe_count - network_error_count - blocked_count)
        / (probe_count - network_error_count)
        if probe_count - network_error_count else 0.0,
        "rate_denominator": "eligible_requests_with_http_status",
        "network_error_count": network_error_count,
        "status_counts": dict(sorted(status_counts.items())),
        "by_method": by_method,
        "latency_ms": {
            "mean": statistics.fmean(latencies) if latencies else 0.0,
            "median": statistics.median(latencies) if latencies else 0.0,
            "p95": latencies[p95_index] if latencies else 0.0,
        },
        "started_at": started_at,
        "finished_at": finished_at,
    }


def bounded_ordered_map(executor, function, items, max_pending: int):
    iterator = iter(items)
    pending = deque()
    for _ in range(max_pending):
        try:
            pending.append(executor.submit(function, next(iterator)))
        except StopIteration:
            break
    while pending:
        future = pending.popleft()
        yield future.result()
        try:
            pending.append(executor.submit(function, next(iterator)))
        except StopIteration:
            pass


def run_campaign(
    input_csv: Path,
    target_url: str,
    out_dir: Path,
    methods: list[str],
    parameter: str,
    timeout: float,
    blocked_statuses: set[int],
    seed: int,
    max_payloads: int | None,
    workers: int,
    retries: int,
    checkpoint_every: int,
    resume: bool,
) -> dict[str, object]:
    target_url = validate_target(target_url)
    if seed != SEED:
        raise ValueError(f"WAF campaign seed must be {SEED}")
    if workers < 1:
        raise ValueError("workers must be at least 1")
    if retries < 0:
        raise ValueError("retries must not be negative")
    if checkpoint_every < 1:
        raise ValueError("checkpoint-every must be at least 1")
    normalized_methods = list(dict.fromkeys(method.upper() for method in methods))
    if not normalized_methods or any(method not in {"GET", "POST"} for method in normalized_methods):
        raise ValueError("methods must contain GET, POST, or both")

    input_csv = input_csv.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    result_csv = out_dir / "waf_probe_results.csv"
    state_path = out_dir / "campaign_state.json"
    summary_path = out_dir / "waf_summary.json"
    payloads = load_payloads(input_csv)
    selected = list(payloads)
    random.Random(seed).shuffle(selected)
    if max_payloads is not None:
        selected = selected[:max_payloads]
    input_hash = sha256_file(input_csv)
    config = campaign_config(
        input_csv=input_csv,
        target_url=target_url,
        methods=normalized_methods,
        parameter=parameter,
        timeout=timeout,
        blocked_statuses=blocked_statuses,
        seed=seed,
        max_payloads=max_payloads,
        workers=workers,
        retries=retries,
        input_hash=input_hash,
        selected_payload_count=len(selected),
    )

    if resume:
        state = verify_resume_state(state_path, config)
        started_at = str(state["started_at"])
        completed = load_completed(result_csv)
    else:
        if result_csv.exists() or state_path.exists():
            raise FileExistsError(
                f"Campaign output already exists in {out_dir}; use --resume or a new directory"
            )
        started_at = utc_now()
        completed = 0

    total_probes = int(config["total_probe_count"])
    if completed > total_probes:
        raise ValueError("Existing result contains more probes than the configured campaign")
    append = completed > 0
    thread_local = threading.local()
    probes: list[PersistentHttpProbe] = []
    probes_lock = threading.Lock()

    def execute(task: tuple[int, int, str, str]) -> dict[str, object]:
        probe_index, source_row, payload, method = task
        probe = getattr(thread_local, "probe", None)
        if probe is None:
            probe = PersistentHttpProbe(
                target_url=target_url,
                parameter=parameter,
                timeout=timeout,
                blocked_statuses=blocked_statuses,
                retries=retries,
            )
            thread_local.probe = probe
            with probes_lock:
                probes.append(probe)
        result = probe.request(payload, method)
        return {
            "probe_index": probe_index,
            "source_row": source_row,
            "method": method,
            "payload": payload,
            **result,
        }

    def remaining_tasks():
        for selected_index, (source_row, payload) in enumerate(selected):
            for method_index, method in enumerate(normalized_methods):
                probe_index = selected_index * len(normalized_methods) + method_index
                if probe_index >= completed:
                    yield probe_index, source_row, payload, method

    mode = "a" if append else "w"
    interval_started = perf_counter()
    interval_completed = 0
    last_rate = 0.0
    with result_csv.open(mode, encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=RESULT_FIELDS)
        if not append:
            writer.writeheader()
        with ThreadPoolExecutor(max_workers=workers) as executor:
            for record in bounded_ordered_map(
                executor,
                execute,
                remaining_tasks(),
                max_pending=workers * 4,
            ):
                writer.writerow(record)
                completed += 1
                interval_completed += 1
                if completed % checkpoint_every == 0 or completed == total_probes:
                    handle.flush()
                    elapsed = perf_counter() - interval_started
                    last_rate = interval_completed / elapsed if elapsed > 0 else 0.0
                    save_state(state_path, config, started_at, completed, last_rate)
                    remaining = total_probes - completed
                    eta = remaining / last_rate if last_rate > 0 else None
                    print(
                        json.dumps(
                            {
                                "completed": completed,
                                "total": total_probes,
                                "progress": round(completed / total_probes, 6),
                                "rate_probes_per_second": round(last_rate, 3),
                                "eta_seconds": round(eta, 1) if eta is not None else None,
                            }
                        ),
                        flush=True,
                    )
                    interval_started = perf_counter()
                    interval_completed = 0
        for probe in probes:
            probe._close()

    finished_at = utc_now()
    summary = summarize_results(
        result_csv=result_csv,
        config=config,
        input_payload_count=len(payloads),
        started_at=started_at,
        finished_at=finished_at,
    )
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    save_state(state_path, config, started_at, completed, last_rate)
    return summary


def parse_statuses(value: str) -> set[int]:
    try:
        result = {int(item.strip()) for item in value.split(",") if item.strip()}
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Blocked statuses must be integers") from exc
    if not result or any(status < 100 or status > 599 for status in result):
        raise argparse.ArgumentTypeError("Blocked statuses must be valid HTTP status codes")
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Resumable parallel WAF campaign for large generated-payload CSV files"
    )
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--target-url", default="http://127.0.0.1:18080/")
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--methods", nargs="+", choices=["GET", "POST"], default=["GET", "POST"])
    parser.add_argument("--parameter", default="payload")
    parser.add_argument("--timeout", type=float, default=5.0)
    parser.add_argument("--blocked-statuses", type=parse_statuses, default={403})
    parser.add_argument("--seed", type=int, choices=[SEED], default=SEED)
    parser.add_argument("--max-payloads", type=int)
    parser.add_argument("--workers", type=int, default=16)
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument("--checkpoint-every", type=int, default=1000)
    parser.add_argument("--resume", action="store_true")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    summary = run_campaign(
        input_csv=args.input,
        target_url=args.target_url,
        out_dir=args.out_dir,
        methods=args.methods,
        parameter=args.parameter,
        timeout=args.timeout,
        blocked_statuses=args.blocked_statuses,
        seed=args.seed,
        max_payloads=args.max_payloads,
        workers=args.workers,
        retries=args.retries,
        checkpoint_every=args.checkpoint_every,
        resume=args.resume,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
