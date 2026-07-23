from __future__ import annotations

import argparse
import csv
import hashlib
import html
import io
import json
import math
import random
import re
import shutil
import sys
import unicodedata
import urllib.parse
import zipfile
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Sequence

import sqlparse
import yaml
from sqlparse import tokens as T


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = REPO_ROOT / "configs" / "experiment_config.yaml"
ATTACK_LABELS = {"1", "true", "attack", "malicious", "sqli", "sql injection"}
NORMAL_LABELS = {"0", "false", "normal", "benign", "clean"}
HEADER_PAYLOAD_NAMES = {"payload", "sentence"}
FAMILY_ORDER = ("error", "time", "union", "boolean")

ERROR_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE | re.DOTALL)
    for pattern in (
        r"\bextractvalue\s*\(",
        r"\bupdatexml\s*\(",
        r"\bxpath\b",
        r"\bfloor\s*\(\s*rand\s*\(",
        r"\bexp\s*\(\s*~",
        r"\bxmltype\s*\(",
        r"\butl_inaddr\s*\.\s*get_host_address\s*\(",
        r"\bctxsys\s*\.\s*drithsx\s*\.\s*sn\s*\(",
        r"\bconvert\s*\(.*?\busing\b",
        r"\bcast\s*\(.*?\bas\s+(?:int|signed|unsigned|numeric)\b",
        r"\bgroup\s+by\b.*?\bhaving\b",
    )
)
TIME_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE | re.DOTALL)
    for pattern in (
        r"\bsleep\s*(?:\(|\s)",
        r"\bbenchmark\s*\(",
        r"\bwaitfor\s+delay\b",
        r"\bpg_sleep\s*\(",
        r"\bdbms_lock\s*\.\s*sleep\s*\(",
    )
)
UNION_PATTERN = re.compile(r"\bunion\s+(?:all\s+)?select\b", re.IGNORECASE | re.DOTALL)
BOOLEAN_PATTERN = re.compile(
    r"(?:\b(?:and|or)\b|['\"]\s*\)?\s*(?:and|or)\b).*?(?:=|<>|!=|<=|>=|<|>|\blike\b|\bbetween\b|\bis\s+(?:not\s+)?null\b)",
    re.IGNORECASE | re.DOTALL,
)
BOOLEAN_COMMENT_PATTERN = re.compile(r"\b(?:and|or)\b.*?(?:--|#|/\*)", re.IGNORECASE | re.DOTALL)


@dataclass(frozen=True)
class Record:
    payload: str
    label: str
    source_line: int
    order: int
    family: str = ""


@dataclass
class ParseStats:
    source_name: str = ""
    encoding: str = ""
    delimiter: str = ","
    records_seen: int = 0
    header_rows_removed: int = 0
    invalid_label_rows_removed: int = 0
    empty_payload_rows_removed: int = 0
    normalized_duplicate_rows_removed: int = 0
    conflict_groups_removed: int = 0
    conflict_rows_removed: int = 0
    retained_rows: int = 0
    retained_normal_rows: int = 0
    retained_attack_rows: int = 0


class DatasetError(RuntimeError):
    pass


def load_config(path: Path = DEFAULT_CONFIG) -> dict:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise DatasetError(f"Invalid config: {path}")
    return data


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def reset_dir(path: Path, allowed_root: Path) -> None:
    resolved = path.resolve()
    root = allowed_root.resolve()
    if resolved == root or root not in resolved.parents:
        raise DatasetError(f"Refusing to reset path outside prepared data root: {path}")
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def normalized_payload(payload: str) -> str:
    text = unicodedata.normalize("NFKC", str(payload))
    text = text.translate(str.maketrans({"‘": "'", "’": "'", "`": "'", "“": '"', "”": '"'}))
    return re.sub(r"\s+", " ", text.casefold()).strip()


def normalize_label(value: str) -> str | None:
    text = str(value).strip().casefold()
    if text in ATTACK_LABELS:
        return "attack"
    if text in NORMAL_LABELS:
        return "normal"
    return None


def read_input_bytes(path: Path) -> tuple[bytes, str]:
    if not path.exists():
        raise DatasetError(f"Input does not exist: {path}")
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as archive:
            members = [name for name in archive.namelist() if name.lower().endswith(".csv") and not name.endswith("/")]
            if len(members) != 1:
                raise DatasetError(f"Expected one CSV in {path}, found {len(members)}")
            return archive.read(members[0]), f"{path.name}:{members[0]}"
    return path.read_bytes(), path.name


def decode_input(data: bytes) -> tuple[str, str]:
    for encoding in ("utf-8-sig", "cp1252", "latin1"):
        try:
            return data.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    raise DatasetError("Unable to decode source dataset")


def trim_trailing_empty_fields(row: list[str]) -> list[str]:
    output = list(row)
    while len(output) > 2 and not output[-1].strip():
        output.pop()
    return output


def detect_delimiter(text: str) -> str:
    sample = text[:262144]
    known = ATTACK_LABELS | NORMAL_LABELS | {"label"}
    scored: list[tuple[int, str]] = []
    for delimiter in (",", ";", "\t", "|"):
        recognized = 0
        rows = 0
        try:
            reader = csv.reader(io.StringIO(sample, newline=""), delimiter=delimiter, quotechar='"', strict=False)
            for row in reader:
                row = trim_trailing_empty_fields(row)
                rows += int(len(row) >= 2)
                if len(row) >= 2 and row[-1].strip().casefold() in known:
                    recognized += 1
                if rows >= 1000:
                    break
        except csv.Error:
            pass
        scored.append((recognized * 1000 + rows, delimiter))
    return max(scored)[1]


def parse_dataset(input_path: Path, logs_dir: Path) -> tuple[list[Record], ParseStats]:
    data, source_name = read_input_bytes(input_path)
    text, encoding = decode_input(data)
    delimiter = detect_delimiter(text)
    stats = ParseStats(source_name=source_name, encoding=encoding, delimiter=delimiter)
    candidates: list[Record] = []
    invalid: list[dict[str, object]] = []
    reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter, quotechar='"', doublequote=True, strict=False)
    while True:
        try:
            row = next(reader)
        except StopIteration:
            break
        except csv.Error as exc:
            stats.records_seen += 1
            invalid.append({"source_line": reader.line_num, "raw_label": "", "payload": "", "reason": f"csv_parse_error:{exc}"})
            stats.invalid_label_rows_removed += 1
            continue
        stats.records_seen += 1
        row = trim_trailing_empty_fields(row)
        raw_label = row[-1] if len(row) >= 2 else ""
        payload = delimiter.join(row[:-1]) if len(row) >= 2 else (row[0] if row else "")
        if payload.strip().casefold() in HEADER_PAYLOAD_NAMES and raw_label.strip().casefold() == "label":
            stats.header_rows_removed += 1
            continue
        label = normalize_label(raw_label)
        if label is None:
            stats.invalid_label_rows_removed += 1
            invalid.append({"source_line": reader.line_num, "raw_label": raw_label, "payload": payload, "reason": "unmapped_label"})
            continue
        if not payload.strip():
            stats.empty_payload_rows_removed += 1
            continue
        candidates.append(Record(payload=payload, label=label, source_line=reader.line_num, order=len(candidates)))

    groups: dict[str, list[Record]] = defaultdict(list)
    for record in candidates:
        groups[normalized_payload(record.payload)].append(record)
    conflicts: list[dict[str, object]] = []
    accepted: list[Record] = []
    for fingerprint, records in groups.items():
        labels = {record.label for record in records}
        if len(labels) > 1:
            stats.conflict_groups_removed += 1
            stats.conflict_rows_removed += len(records)
            for record in records:
                conflicts.append({"fingerprint": fingerprint, "source_line": record.source_line, "label": record.label, "payload": record.payload})
            continue
        accepted.append(records[0])
        stats.normalized_duplicate_rows_removed += len(records) - 1
    accepted.sort(key=lambda record: record.order)
    accepted = [Record(record.payload, record.label, record.source_line, index) for index, record in enumerate(accepted)]
    stats.retained_rows = len(accepted)
    stats.retained_normal_rows = sum(record.label == "normal" for record in accepted)
    stats.retained_attack_rows = sum(record.label == "attack" for record in accepted)
    logs_dir.mkdir(parents=True, exist_ok=True)
    write_dict_rows(logs_dir / "rejected_rows.csv", invalid, ("source_line", "raw_label", "payload", "reason"))
    write_dict_rows(logs_dir / "label_conflicts.csv", conflicts, ("fingerprint", "source_line", "label", "payload"))
    return accepted, stats


def is_literal(token) -> bool:
    return token.ttype is not None and (token.ttype in T.String or token.ttype in T.Number)


def parser_searchable_text(payload: str) -> str:
    statements = sqlparse.parse(payload)
    parts: list[str] = []
    for statement in statements:
        for token in statement.flatten():
            parts.append(" " * max(1, len(token.value)) if is_literal(token) else token.value)
    return "".join(parts)


def classify_family(payload: str) -> str:
    raw = normalized_payload(payload)
    decoded = raw
    for _ in range(2):
        expanded = normalized_payload(html.unescape(urllib.parse.unquote(decoded)))
        if expanded == decoded:
            break
        decoded = expanded
    joined_comments = normalized_payload(re.sub(r"/\*.*?\*/", "", decoded, flags=re.DOTALL))
    spaced_comments = normalized_payload(re.sub(r"/\*.*?\*/", " ", decoded, flags=re.DOTALL))
    try:
        searchable = parser_searchable_text(payload)
    except Exception:
        searchable = payload
    candidates = tuple(dict.fromkeys((searchable, raw, decoded, joined_comments, spaced_comments)))
    if any(pattern.search(candidate) for pattern in ERROR_PATTERNS for candidate in candidates):
        return "error"
    if any(pattern.search(candidate) for pattern in TIME_PATTERNS for candidate in candidates):
        return "time"
    if any(UNION_PATTERN.search(candidate) for candidate in candidates):
        return "union"
    if any(BOOLEAN_PATTERN.search(candidate) or BOOLEAN_COMMENT_PATTERN.search(candidate) for candidate in candidates):
        return "boolean"
    return "other"


def classify_records(records: Sequence[Record], audit_path: Path) -> dict[str, list[Record]]:
    pools = {family: [] for family in (*FAMILY_ORDER, "other")}
    rows: list[dict[str, object]] = []
    for record in records:
        if record.label != "attack":
            continue
        family = classify_family(record.payload)
        classified = Record(record.payload, record.label, record.source_line, record.order, family)
        pools[family].append(classified)
        rows.append({"source_line": record.source_line, "family": family, "payload": record.payload})
    write_dict_rows(audit_path, rows, ("source_line", "family", "payload"))
    return pools


def split_records(records: Sequence[Record], holdout_fraction: float, seed: int) -> tuple[list[Record], list[Record]]:
    if not 0 < holdout_fraction < 1:
        raise DatasetError("Holdout fraction must be between zero and one")
    count = math.floor(len(records) * holdout_fraction)
    if records and count == 0:
        count = 1
    indices = list(range(len(records)))
    random.Random(seed).shuffle(indices)
    holdout_indices = set(indices[:count])
    train = [record for index, record in enumerate(records) if index not in holdout_indices]
    holdout = [record for index, record in enumerate(records) if index in holdout_indices]
    return train, holdout


def percentile(values: Sequence[int], q: float) -> float:
    ordered = sorted(values)
    if not ordered:
        raise DatasetError("Cannot compute percentile of empty pool")
    position = (len(ordered) - 1) * q
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return float(ordered[lower])
    return ordered[lower] + (position - lower) * (ordered[upper] - ordered[lower])


def iqr_records(pool: Sequence[Record]) -> list[Record]:
    if not pool:
        return []
    lengths = [len(record.payload) for record in pool]
    q1, q3 = percentile(lengths, 0.25), percentile(lengths, 0.75)
    return [record for record in pool if q1 <= len(record.payload) <= q3]


def char_trigrams(text: str) -> frozenset[str]:
    value = normalized_payload(text)
    return frozenset(value[index:index + 3] for index in range(max(0, len(value) - 2)))


def jaccard(left: frozenset[str], right: frozenset[str]) -> float:
    if not left and not right:
        return 1.0
    return len(left & right) / len(left | right) if left and right else 0.0


def diverse_order(pool: Sequence[Record], seed: int) -> list[Record]:
    if not pool:
        return []
    records = list(pool)
    grams = [char_trigrams(record.payload) for record in records]
    first = random.Random(seed).randrange(len(records))
    selected = [first]
    remaining = set(range(len(records)))
    remaining.remove(first)
    sums = [0.0] * len(records)
    for index in remaining:
        sums[index] = jaccard(grams[index], grams[first])
    while remaining:
        chosen = min(remaining, key=lambda index: (sums[index], len(records[index].payload), records[index].payload))
        selected.append(chosen)
        remaining.remove(chosen)
        for index in remaining:
            sums[index] += jaccard(grams[index], grams[chosen])
    return [records[index] for index in selected]


def scenario_order(pool: Sequence[Record], scenario: str, seed: int, full: bool = False) -> tuple[list[Record], int]:
    records = list(pool)
    if scenario not in {"A", "B", "C", "D", "E", "F"}:
        raise DatasetError(f"Unknown scenario: {scenario}")
    if full:
        return sorted(records, key=lambda record: record.order), len(records)
    if scenario == "A":
        return sorted(records, key=lambda record: record.order), len(records)
    if scenario == "B":
        return sorted(records, key=lambda record: (len(record.payload), record.order)), len(records)
    if scenario == "C":
        if not records:
            return [], 0
        lengths = [len(record.payload) for record in records]
        minimum, maximum = min(lengths), max(lengths)
        if minimum == maximum:
            center = float(minimum)
        else:
            width = (maximum - minimum) / 20
            bins = [0] * 20
            for length in lengths:
                bins[min(19, int((length - minimum) / width))] += 1
            modal = max(range(20), key=lambda index: bins[index])
            center = minimum + (modal + 0.5) * width
        return sorted(records, key=lambda record: (abs(len(record.payload) - center), len(record.payload), record.order)), len(records)
    if scenario == "D":
        eligible = iqr_records(records)
        random.Random(seed).shuffle(eligible)
        return eligible, len(eligible)
    if scenario == "E":
        random.Random(seed).shuffle(records)
        return records, len(records)
    if scenario == "F":
        ordered = diverse_order(records, seed)
        return ordered, len(ordered)
    raise DatasetError(f"Unknown scenario: {scenario}")


def write_dict_rows(path: Path, rows: Sequence[dict[str, object]], fields: Sequence[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def write_records(path: Path, records: Iterable[Record]) -> None:
    rows = list(records)
    write_dict_rows(
        path,
        [{"label": record.label, "payload": record.payload, "family": record.family or ("normal" if record.label == "normal" else "other")} for record in rows],
        ("label", "payload", "family"),
    )


def read_records(path: Path) -> list[Record]:
    output: list[Record] = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for index, row in enumerate(csv.DictReader(handle)):
            output.append(Record(str(row["payload"]), str(row["label"]), index + 2, index, str(row.get("family", ""))))
    return output


def dataset_entry(path: Path) -> dict[str, object]:
    count = sum(1 for _ in path.open("r", encoding="utf-8-sig")) - 1
    return {"path": str(path.relative_to(REPO_ROOT)).replace("\\", "/"), "rows": max(0, count), "sha256": sha256_file(path)}


def snapshot_source(source: Path, snapshot: Path) -> dict[str, object]:
    snapshot.parent.mkdir(parents=True, exist_ok=True)
    source_hash = sha256_file(source)
    if not snapshot.exists() or sha256_file(snapshot) != source_hash:
        temporary = snapshot.with_suffix(snapshot.suffix + ".tmp")
        shutil.copy2(source, temporary)
        temporary.replace(snapshot)
    return {"source": str(source.relative_to(REPO_ROOT)).replace("\\", "/"), "snapshot": str(snapshot.relative_to(REPO_ROOT)).replace("\\", "/"), "sha256": source_hash, "bytes": source.stat().st_size}


def materialize_phase2a(work_dir: Path, pools: dict[str, list[Record]], normal_train_count: int, cfg: dict, seed: int) -> dict[str, object]:
    phase_dir = work_dir / "phase2a"
    reset_dir(phase_dir, work_dir)
    ratio = int(cfg["phase2a"]["ratio"])
    target = math.floor(normal_train_count / ratio)
    scenarios = cfg["scenarios"]
    rows: list[dict[str, object]] = []
    all_feasible = True
    for family in cfg["families"]:
        for scenario in scenarios:
            capacity = len(iqr_records(pools[family])) if scenario == "D" else len(pools[family])
            feasible = capacity >= target
            all_feasible = all_feasible and feasible
            rows.append({"family": family, "scenario": scenario, "ratio": ratio, "target": target, "capacity": capacity, "selected": target if feasible else 0, "status": "ready" if feasible else "insufficient_pool"})
    if all_feasible:
        for family in cfg["families"]:
            for scenario in scenarios:
                candidates, _ = scenario_order(pools[family], scenario, seed)
                selected = sorted(candidates[:target], key=lambda record: record.order)
                write_records(phase_dir / family / scenario / "attack_train.csv", selected)
    report = phase_dir / "preflight.csv"
    write_dict_rows(report, rows, ("family", "scenario", "ratio", "target", "capacity", "selected", "status"))
    return {"ratio": ratio, "target_attack_count": target, "normal_train_count": normal_train_count, "feasible": all_feasible, "report": str(report.relative_to(REPO_ROOT)).replace("\\", "/"), "cells": rows}


def prepare(config_path: Path = DEFAULT_CONFIG) -> dict[str, object]:
    cfg = load_config(config_path)
    seed = int(cfg["seed"])
    source = repo_path(cfg["dataset"]["raw_input"])
    snapshot = repo_path(cfg["dataset"]["source_snapshot"])
    work_dir = repo_path(cfg["dataset"]["work_dir"])
    work_dir.mkdir(parents=True, exist_ok=True)
    source_info = snapshot_source(source, snapshot)
    logs_dir = work_dir / "logs"
    splits_dir = work_dir / "splits"
    phase1_dir = work_dir / "phase1"
    reset_dir(logs_dir, work_dir)
    reset_dir(splits_dir, work_dir)
    reset_dir(phase1_dir, work_dir)
    reset_dir(work_dir / "phase2b", work_dir)
    reset_dir(work_dir / "frozen", work_dir)
    records, stats = parse_dataset(snapshot, logs_dir)
    pools = classify_records(records, logs_dir / "family_classification.csv")
    normal = [record for record in records if record.label == "normal"]
    normal_train, normal_test = split_records(normal, float(cfg["dataset"]["normal_test_fraction"]), seed)
    family_train: dict[str, list[Record]] = {}
    family_holdout: dict[str, list[Record]] = {}
    for family in (*cfg["families"], "other"):
        train, holdout = split_records(pools.get(family, []), float(cfg["dataset"]["family_holdout_fraction"]), seed)
        family_train[family] = train
        family_holdout[family] = holdout
        write_records(splits_dir / f"{family}_train_pool.csv", train)
        write_records(splits_dir / f"{family}_holdout.csv", holdout)
    write_records(splits_dir / "normal_train.csv", normal_train)
    write_records(splits_dir / "normal_test.csv", normal_test)
    attack_train_all = sorted([record for values in family_train.values() for record in values], key=lambda record: record.order)
    attack_holdout_all = sorted([record for values in family_holdout.values() for record in values], key=lambda record: record.order)
    write_records(phase1_dir / "attack_train.csv", attack_train_all)
    write_records(phase1_dir / "attack_holdout.csv", attack_holdout_all)
    write_records(work_dir / "canonical_dataset.csv", [*normal, *sorted([record for values in pools.values() for record in values], key=lambda record: record.order)])
    phase2a = materialize_phase2a(work_dir, family_train, len(normal_train), cfg, seed)
    variants = cfg["phase3"]["variants"]
    write_dict_rows(work_dir / "seqgan_variants.csv", variants, ("id", "sequence_length", "generator_pretrain_epochs", "sql_reward", "tokenizer_mode"))
    data_files = [path for path in splits_dir.glob("*.csv")] + [phase1_dir / "attack_train.csv", phase1_dir / "attack_holdout.csv", work_dir / "canonical_dataset.csv", work_dir / "seqgan_variants.csv"]
    manifest = {
        "schema_version": int(cfg["schema_version"]),
        "seed": seed,
        "source": source_info,
        "parse": asdict(stats),
        "family_counts": {family: len(values) for family, values in pools.items()},
        "split_counts": {
            "normal_train": len(normal_train),
            "normal_test": len(normal_test),
            **{f"{family}_train_pool": len(family_train[family]) for family in family_train},
            **{f"{family}_holdout": len(family_holdout[family]) for family in family_holdout},
        },
        "phase2a": phase2a,
        "files": [dataset_entry(path) for path in sorted(data_files)],
    }
    write_json(work_dir / "dataset_manifest.json", manifest)
    return manifest


def read_selected_cells(path: Path, families: Sequence[str]) -> list[tuple[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    cells: list[tuple[str, str]] = []
    for row in rows:
        family, scenario = str(row.get("family", "")), str(row.get("scenario", ""))
        rank = int(float(row.get("rank", row.get("rank_within_family", 99)) or 99))
        if family in families and rank <= 2:
            cells.append((family, scenario))
    counts = Counter(family for family, _ in cells)
    if any(counts[family] != 2 for family in families) or len(set(cells)) != len(cells):
        raise DatasetError("Selection must contain exactly two unique scenarios per family")
    return cells


def materialize_phase2b(config_path: Path, selection_path: Path) -> dict[str, object]:
    cfg = load_config(config_path)
    seed = int(cfg["seed"])
    work_dir = repo_path(cfg["dataset"]["work_dir"])
    phase_dir = work_dir / "phase2b"
    reset_dir(phase_dir, work_dir)
    cells = read_selected_cells(selection_path, cfg["families"])
    normal_train_count = len(read_records(work_dir / "splits" / "normal_train.csv"))
    rows: list[dict[str, object]] = []
    for family, scenario in cells:
        pool = read_records(work_dir / "splits" / f"{family}_train_pool.csv")
        for ratio_value in cfg["phase2b"]["ratios"]:
            ratio = str(ratio_value)
            full = ratio == "full"
            target = len(pool) if full else math.floor(normal_train_count / int(ratio))
            candidates, capacity = scenario_order(pool, scenario, seed, full=full)
            feasible = capacity >= target
            output = phase_dir / family / scenario / f"R{ratio}" / "attack_train.csv"
            if feasible:
                selected = sorted(candidates[:target], key=lambda record: record.order)
                write_records(output, selected)
            rows.append({"family": family, "scenario": scenario, "ratio": ratio, "target": target, "capacity": capacity, "selected": target if feasible else 0, "status": "ready" if feasible else "insufficient_pool", "output": str(output.relative_to(REPO_ROOT)).replace("\\", "/")})
    report = phase_dir / "preflight.csv"
    write_dict_rows(report, rows, ("family", "scenario", "ratio", "target", "capacity", "selected", "status", "output"))
    manifest = {"seed": seed, "selection": str(selection_path), "cells": len(cells), "ratios": cfg["phase2b"]["ratios"], "rows": rows}
    write_json(phase_dir / "dataset_manifest.json", manifest)
    return manifest


def freeze_phase3(config_path: Path, selection_path: Path, ratio_path: Path) -> dict[str, object]:
    cfg = load_config(config_path)
    work_dir = repo_path(cfg["dataset"]["work_dir"])
    cells = read_selected_cells(selection_path, cfg["families"])
    ratio_data = json.loads(ratio_path.read_text(encoding="utf-8"))
    ratio = str(ratio_data.get("selected_global_ratio", ratio_data.get("selected_ratio", ratio_data.get("ratio", ""))))
    if ratio not in {str(value) for value in cfg["phase2b"]["ratios"]}:
        raise DatasetError(f"Invalid selected ratio: {ratio}")
    frozen_dir = work_dir / "frozen"
    reset_dir(frozen_dir, work_dir)
    files: list[dict[str, object]] = []
    for family, scenario in cells:
        source = work_dir / "phase2b" / family / scenario / f"R{ratio}" / "attack_train.csv"
        if not source.exists():
            raise DatasetError(f"Cannot freeze missing dataset: {source}")
        destination = frozen_dir / family / scenario / "attack_train.csv"
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        files.append({"family": family, "scenario": scenario, **dataset_entry(destination)})
    manifest = {"seed": int(cfg["seed"]), "selected_global_ratio": ratio, "files": files}
    write_json(frozen_dir / "dataset_manifest.json", manifest)
    return manifest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("prepare")
    phase2b = subparsers.add_parser("phase2b")
    phase2b.add_argument("--selection", type=Path, required=True)
    freeze = subparsers.add_parser("freeze")
    freeze.add_argument("--selection", type=Path, required=True)
    freeze.add_argument("--ratio", type=Path, required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        if args.command == "prepare":
            result = prepare(args.config)
        elif args.command == "phase2b":
            result = materialize_phase2b(args.config, args.selection)
        else:
            result = freeze_phase3(args.config, args.selection, args.ratio)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (DatasetError, OSError, ValueError, KeyError, csv.Error) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
