from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import re
import tempfile
import zipfile
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import BinaryIO, Iterable


FINAL_ENTRY_RE = re.compile(
    r"(?:^|/)result/final/"
    r"(?P<method>[^/]+)/"
    r"(?P<family>[^/]+)/"
    r"(?P<scenario>[^/]+)/"
    r"(?P<ratio>R[^/]+)/"
    r"(?:(?P<variant>[^/]+)/)?"
    r"generated_payloads\.csv$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class SourceCsv:
    container: Path
    entry_name: str
    method: str
    family: str
    scenario: str
    ratio: str
    variant: str
    is_zip: bool

    @property
    def identity(self) -> str:
        return self.entry_name.replace("\\", "/").casefold()


def _metadata(path: str) -> dict[str, str] | None:
    match = FINAL_ENTRY_RE.search(path.replace("\\", "/"))
    if match is None:
        return None
    return {key: value or "" for key, value in match.groupdict().items()}


def discover_sources(paths: Iterable[Path]) -> list[SourceCsv]:
    discovered: list[SourceCsv] = []
    for raw_path in paths:
        path = raw_path.resolve()
        if not path.exists():
            raise FileNotFoundError(path)
        if path.is_file() and path.suffix.casefold() == ".zip":
            with zipfile.ZipFile(path) as archive:
                for info in archive.infolist():
                    if info.is_dir():
                        continue
                    metadata = _metadata(info.filename)
                    if metadata is None:
                        continue
                    discovered.append(
                        SourceCsv(
                            container=path,
                            entry_name=info.filename,
                            is_zip=True,
                            **metadata,
                        )
                    )
            continue
        if path.is_dir():
            for csv_path in path.rglob("generated_payloads.csv"):
                relative = csv_path.relative_to(path).as_posix()
                metadata = _metadata(relative)
                if metadata is None:
                    metadata = _metadata(csv_path.as_posix())
                if metadata is None:
                    continue
                discovered.append(
                    SourceCsv(
                        container=csv_path,
                        entry_name=relative,
                        is_zip=False,
                        **metadata,
                    )
                )
            continue
        raise ValueError(f"Source must be a ZIP archive or directory: {path}")

    discovered.sort(
        key=lambda source: (
            source.ratio.casefold(),
            source.method.casefold(),
            source.family.casefold(),
            source.scenario.casefold(),
            source.variant.casefold(),
            str(source.container).casefold(),
        )
    )
    duplicate_paths = [
        identity
        for identity, count in Counter(source.identity for source in discovered).items()
        if count > 1
    ]
    if duplicate_paths:
        examples = ", ".join(duplicate_paths[:5])
        raise ValueError(f"Duplicate Final entries across sources: {examples}")
    return discovered


def _read_bytes(source: SourceCsv) -> bytes:
    if not source.is_zip:
        return source.container.read_bytes()
    with zipfile.ZipFile(source.container) as archive:
        with archive.open(source.entry_name) as handle:
            return handle.read()


def _payloads(raw: bytes, source: SourceCsv) -> list[str]:
    text = io.TextIOWrapper(io.BytesIO(raw), encoding="utf-8-sig", newline="")
    reader = csv.DictReader(text)
    if not reader.fieldnames or "payload" not in reader.fieldnames:
        raise ValueError(
            f"{source.container}!{source.entry_name} must contain a 'payload' column; "
            f"found {reader.fieldnames}"
        )
    return [(row.get("payload") or "") for row in reader]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _atomic_csv_path(output: Path) -> tuple[Path, BinaryIO]:
    output.parent.mkdir(parents=True, exist_ok=True)
    file_descriptor, name = tempfile.mkstemp(
        prefix=f".{output.name}.",
        suffix=".tmp",
        dir=output.parent,
    )
    return Path(name), os.fdopen(file_descriptor, "wb")


def aggregate(
    sources: list[SourceCsv],
    output: Path,
    source_manifest: Path,
    manifest: Path,
    expected_files: int | None = None,
    expected_rows_per_file: int | None = None,
) -> dict[str, object]:
    if not sources:
        raise ValueError("No result/final/**/generated_payloads.csv files were found")
    if expected_files is not None and len(sources) != expected_files:
        raise ValueError(f"Expected {expected_files} Final CSV files, found {len(sources)}")

    temporary_path, raw_handle = _atomic_csv_path(output)
    source_rows: list[dict[str, object]] = []
    unique_payloads: set[str] = set()
    global_empty_count = 0
    global_row = 0
    try:
        with raw_handle:
            text_handle = io.TextIOWrapper(raw_handle, encoding="utf-8", newline="")
            writer = csv.DictWriter(text_handle, fieldnames=["payload"])
            writer.writeheader()
            for source in sources:
                raw = _read_bytes(source)
                payloads = _payloads(raw, source)
                if expected_rows_per_file is not None and len(payloads) != expected_rows_per_file:
                    raise ValueError(
                        f"{source.entry_name}: expected {expected_rows_per_file} rows, "
                        f"found {len(payloads)}"
                    )
                row_start = global_row
                empty_count = 0
                for payload in payloads:
                    writer.writerow({"payload": payload})
                    unique_payloads.add(payload)
                    empty_count += int(payload == "")
                    global_row += 1
                global_empty_count += empty_count
                source_rows.append(
                    {
                        "source_archive": str(source.container),
                        "source_entry": source.entry_name,
                        "method": source.method,
                        "family": source.family,
                        "scenario": source.scenario,
                        "ratio": source.ratio,
                        "variant": source.variant,
                        "row_start_inclusive": row_start,
                        "row_end_exclusive": global_row,
                        "row_count": len(payloads),
                        "empty_payload_count": empty_count,
                        "source_csv_sha256": hashlib.sha256(raw).hexdigest(),
                    }
                )
            text_handle.flush()
        os.replace(temporary_path, output)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise

    source_manifest.parent.mkdir(parents=True, exist_ok=True)
    source_fields = [
        "source_archive",
        "source_entry",
        "method",
        "family",
        "scenario",
        "ratio",
        "variant",
        "row_start_inclusive",
        "row_end_exclusive",
        "row_count",
        "empty_payload_count",
        "source_csv_sha256",
    ]
    with source_manifest.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=source_fields)
        writer.writeheader()
        writer.writerows(source_rows)

    by_method = Counter(str(row["method"]) for row in source_rows)
    by_ratio = Counter(str(row["ratio"]) for row in source_rows)
    by_family = Counter(str(row["family"]) for row in source_rows)
    summary: dict[str, object] = {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "selection": "result/final/**/generated_payloads.csv",
        "input_containers": sorted({str(source.container) for source in sources}),
        "source_csv_count": len(source_rows),
        "payload_count": global_row,
        "unique_payload_count": len(unique_payloads),
        "duplicate_payload_count": global_row - len(unique_payloads),
        "empty_payload_count": global_empty_count,
        "duplicates_preserved": True,
        "output_columns": ["payload"],
        "output_csv": str(output),
        "output_csv_sha256": _sha256(output),
        "source_manifest": str(source_manifest),
        "counts_by_method": dict(sorted(by_method.items())),
        "counts_by_ratio": dict(sorted(by_ratio.items())),
        "counts_by_family": dict(sorted(by_family.items())),
    }
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Combine only result/final/**/generated_payloads.csv into one payload-only "
            "CSV for local WAF evaluation. Duplicate and empty payload rows are preserved."
        )
    )
    parser.add_argument(
        "--source",
        type=Path,
        action="append",
        required=True,
        help="ZIP archive or directory; repeat for multiple sources",
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-manifest", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--expected-files", type=int)
    parser.add_argument("--expected-rows-per-file", type=int)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    output = args.output.resolve()
    source_manifest = (
        args.source_manifest.resolve()
        if args.source_manifest
        else output.with_name(f"{output.stem}_sources.csv")
    )
    manifest = (
        args.manifest.resolve()
        if args.manifest
        else output.with_name(f"{output.stem}_manifest.json")
    )
    sources = discover_sources(args.source)
    summary = aggregate(
        sources=sources,
        output=output,
        source_manifest=source_manifest,
        manifest=manifest,
        expected_files=args.expected_files,
        expected_rows_per_file=args.expected_rows_per_file,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
