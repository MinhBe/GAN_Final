from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import shutil
import tempfile
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath


PHASES = {
    "phase1",
    "phase2a",
    "phase2b",
    "phase2b_batch6x",
    "phase3",
    "final",
    "waf",
}
SOURCE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]*$")
MANIFEST_FIELDS = [
    "source_id",
    "source_mode",
    "source_root",
    "source_relative",
    "source_size",
    "source_sha256",
    "canonical_relative",
    "canonical_sha256",
    "action",
    "note",
]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def safe_relative(value: str | Path) -> PurePosixPath:
    relative = PurePosixPath(str(value).replace("\\", "/"))
    if relative.is_absolute() or ".." in relative.parts or not relative.parts:
        raise ValueError(f"Unsafe relative path: {value}")
    return relative


def mapped_relative(
    source_relative: PurePosixPath,
    mode: str,
    profile: str,
) -> PurePosixPath:
    if mode == "direct":
        return source_relative
    first, *rest = source_relative.parts
    if mode in {"profile", "delta_profile"}:
        if first.casefold() in PHASES:
            return PurePosixPath(first, "_profiles", profile, *rest)
        return PurePosixPath("_profiles", profile, first, *rest)
    if mode == "export":
        if first.casefold() in PHASES:
            return PurePosixPath(first, "_exports", profile, *rest)
        return PurePosixPath("_exports", profile, first, *rest)
    raise ValueError(f"Unsupported source mode: {mode}")


def history_relative(source_id: str, canonical: PurePosixPath) -> PurePosixPath:
    return PurePosixPath("_history", source_id, *canonical.parts)


def copy_verified(source: Path, target: Path, expected_sha256: str) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    file_descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.",
        suffix=".tmp",
        dir=target.parent,
    )
    os.close(file_descriptor)
    temporary = Path(temporary_name)
    try:
        shutil.copyfile(source, temporary)
        if sha256_file(temporary) != expected_sha256:
            raise IOError(f"SHA-256 mismatch after copying {source} to {target}")
        os.replace(temporary, target)
        try:
            shutil.copystat(source, target)
        except OSError:
            pass
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def iter_files(root: Path):
    for path in sorted((path for path in root.rglob("*") if path.is_file()), key=str):
        yield path, safe_relative(path.relative_to(root))


def validate_plan(repo_root: Path, plan: dict[str, object]) -> tuple[Path, list[dict[str, object]]]:
    if int(plan.get("schema_version", 0)) != 1:
        raise ValueError("Unsupported consolidation plan schema")
    destination = (repo_root / str(plan["destination"])).resolve()
    try:
        destination.relative_to(repo_root)
    except ValueError as exc:
        raise ValueError("Destination must be inside repository root") from exc
    sources = list(plan.get("sources", []))
    seen_ids: set[str] = set()
    for source in sources:
        source_id = str(source.get("id", ""))
        if not SOURCE_ID_RE.fullmatch(source_id) or source_id in seen_ids:
            raise ValueError(f"Invalid or duplicate source id: {source_id}")
        seen_ids.add(source_id)
        mode = str(source.get("mode", ""))
        if mode not in {"direct", "profile", "delta_profile", "export"}:
            raise ValueError(f"Invalid mode for {source_id}: {mode}")
        if mode != "direct" and not str(source.get("profile", "")):
            raise ValueError(f"{source_id} requires a profile")
        source_path = (repo_root / str(source["path"])).resolve()
        if not source_path.is_dir():
            raise FileNotFoundError(source_path)
        if source_path == destination or destination in source_path.parents:
            raise ValueError(f"Source cannot be destination or inside destination: {source_path}")
        source["_resolved_path"] = source_path
        if mode == "delta_profile":
            reference = (repo_root / str(source["reference"])).resolve()
            if not reference.is_dir():
                raise FileNotFoundError(reference)
            source["_resolved_reference"] = reference
    return destination, sources


def seed_destination(destination: Path) -> dict[PurePosixPath, str]:
    known: dict[PurePosixPath, str] = {}
    if not destination.exists():
        return known
    for path, relative in iter_files(destination):
        if relative.parts[0] == "_provenance":
            continue
        known[relative] = sha256_file(path)
    return known


def resolve_conflict_target(
    destination: Path,
    known: dict[PurePosixPath, str],
    source_id: str,
    canonical: PurePosixPath,
    source_sha256: str,
) -> tuple[PurePosixPath, str]:
    candidate = history_relative(source_id, canonical)
    existing = known.get(candidate)
    if existing is None or existing == source_sha256:
        return candidate, "history"
    stem = candidate.stem
    suffix = candidate.suffix
    versioned = candidate.with_name(f"{stem}__sha256_{source_sha256[:12]}{suffix}")
    existing = known.get(versioned)
    if existing is not None and existing != source_sha256:
        raise ValueError(f"Hash-named history target collision: {versioned}")
    return versioned, "history_version"


def write_state(
    state_path: Path,
    started_at: str,
    processed: int,
    total: int,
    actions: Counter[str],
    current_source: str,
    status: str,
) -> None:
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state = {
        "schema_version": 1,
        "started_at": started_at,
        "updated_at": utc_now(),
        "status": status,
        "processed_source_files": processed,
        "total_source_files": total,
        "progress": processed / total if total else 1.0,
        "current_source": current_source,
        "actions": dict(sorted(actions.items())),
    }
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def consolidate(
    repo_root: Path,
    plan: dict[str, object],
    dry_run: bool = False,
    progress_every: int = 100,
) -> dict[str, object]:
    destination, sources = validate_plan(repo_root, plan)
    max_file_bytes = int(plan.get("max_file_bytes", 95_000_000))
    destination.mkdir(parents=True, exist_ok=True)
    provenance = destination / "_provenance"
    manifest_path = provenance / (
        "consolidation_manifest_dry_run.csv" if dry_run else "consolidation_manifest.csv"
    )
    summary_path = provenance / (
        "consolidation_summary_dry_run.json" if dry_run else "consolidation_summary.json"
    )
    state_path = provenance / (
        "consolidation_state_dry_run.json" if dry_run else "consolidation_state.json"
    )
    all_source_files: list[tuple[dict[str, object], Path, PurePosixPath]] = []
    for source in sources:
        root = Path(source["_resolved_path"])
        all_source_files.extend((source, path, relative) for path, relative in iter_files(root))
    total = len(all_source_files)
    known = seed_destination(destination)
    started_at = utc_now()
    actions: Counter[str] = Counter()
    by_source: dict[str, Counter[str]] = defaultdict(Counter)
    records: list[dict[str, object]] = []
    copied_bytes = 0

    for index, (source, source_path, source_relative) in enumerate(all_source_files, start=1):
        source_id = str(source["id"])
        mode = str(source["mode"])
        profile = str(source.get("profile", ""))
        source_size = source_path.stat().st_size
        source_sha256 = ""
        canonical_sha256 = ""
        note = ""

        if source_size >= max_file_bytes:
            action = "excluded_size"
            canonical = mapped_relative(source_relative, mode, profile)
            note = f"size>={max_file_bytes}"
        elif mode == "delta_profile":
            reference_root = Path(source["_resolved_reference"])
            reference_path = reference_root.joinpath(*source_relative.parts)
            source_sha256 = sha256_file(source_path)
            if reference_path.is_file() and reference_path.stat().st_size == source_size:
                reference_sha256 = sha256_file(reference_path)
                if reference_sha256 == source_sha256:
                    action = "covered_by_reference"
                    canonical = mapped_relative(source_relative, mode, profile)
                    canonical_sha256 = reference_sha256
                    note = str(reference_path)
                else:
                    action = ""
                    canonical = mapped_relative(source_relative, mode, profile)
            else:
                action = ""
                canonical = mapped_relative(source_relative, mode, profile)
        else:
            action = ""
            canonical = mapped_relative(source_relative, mode, profile)

        if not action:
            if not source_sha256:
                source_sha256 = sha256_file(source_path)
            existing_sha256 = known.get(canonical)
            if existing_sha256 is None:
                action = "would_copy" if dry_run else "copied"
                canonical_sha256 = source_sha256
                known[canonical] = source_sha256
                copied_bytes += source_size
                if not dry_run:
                    copy_verified(
                        source_path,
                        destination.joinpath(*canonical.parts),
                        source_sha256,
                    )
            elif existing_sha256 == source_sha256:
                action = "duplicate_same_path"
                canonical_sha256 = existing_sha256
            else:
                conflict_target, conflict_kind = resolve_conflict_target(
                    destination,
                    known,
                    source_id,
                    canonical,
                    source_sha256,
                )
                conflict_existing = known.get(conflict_target)
                if conflict_existing == source_sha256:
                    action = "history_duplicate"
                else:
                    action = (
                        f"would_copy_{conflict_kind}"
                        if dry_run
                        else f"copied_{conflict_kind}"
                    )
                    known[conflict_target] = source_sha256
                    copied_bytes += source_size
                    if not dry_run:
                        copy_verified(
                            source_path,
                            destination.joinpath(*conflict_target.parts),
                            source_sha256,
                        )
                note = f"canonical_conflict={canonical.as_posix()}"
                canonical = conflict_target
                canonical_sha256 = source_sha256

        actions[action] += 1
        by_source[source_id][action] += 1
        records.append(
            {
                "source_id": source_id,
                "source_mode": mode,
                "source_root": str(source["_resolved_path"]),
                "source_relative": source_relative.as_posix(),
                "source_size": source_size,
                "source_sha256": source_sha256,
                "canonical_relative": canonical.as_posix(),
                "canonical_sha256": canonical_sha256,
                "action": action,
                "note": note,
            }
        )
        if index % progress_every == 0 or index == total:
            write_state(
                state_path,
                started_at,
                index,
                total,
                actions,
                source_id,
                "dry_run" if dry_run else ("completed" if index == total else "running"),
            )
            print(
                json.dumps(
                    {
                        "processed": index,
                        "total": total,
                        "progress": round(index / total, 6) if total else 1.0,
                        "source": source_id,
                        "actions": dict(sorted(actions.items())),
                    }
                ),
                flush=True,
            )

    provenance.mkdir(parents=True, exist_ok=True)
    with manifest_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=MANIFEST_FIELDS)
        writer.writeheader()
        writer.writerows(records)
    summary: dict[str, object] = {
        "schema_version": 1,
        "dry_run": dry_run,
        "repo_root": str(repo_root),
        "destination": str(destination),
        "max_file_bytes": max_file_bytes,
        "started_at": started_at,
        "finished_at": utc_now(),
        "source_count": len(sources),
        "source_file_count": total,
        "destination_file_count_excluding_provenance": len(known),
        "bytes_to_copy" if dry_run else "bytes_copied": copied_bytes,
        "actions": dict(sorted(actions.items())),
        "by_source": {
            source_id: dict(sorted(counts.items()))
            for source_id, counts in sorted(by_source.items())
        },
        "manifest": str(manifest_path),
    }
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--progress-every", type=int, default=100)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.progress_every < 1:
        raise ValueError("--progress-every must be at least 1")
    repo_root = args.repo_root.resolve()
    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    summary = consolidate(
        repo_root=repo_root,
        plan=plan,
        dry_run=args.dry_run,
        progress_every=args.progress_every,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
