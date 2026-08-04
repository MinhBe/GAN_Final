from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import platform
import subprocess
import sys
from importlib import metadata as importlib_metadata
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Sequence

import yaml


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = REPO_ROOT / "configs" / "experiment_config.yaml"
BASELINE_METHODS = ("smote", "gan", "ctgan", "seqgan_master")
sys.path.insert(0, str(REPO_ROOT))


@dataclass(frozen=True)
class RunSpec:
    phase: str
    run_id: str
    method: str
    family: str
    scenario: str
    ratio: str
    variant_id: str
    dataset: str
    holdout_ref: str
    out_dir: str
    data_status: str
    config_digest: str
    train_command: str
    quality_command: str
    rf_command: str


class PipelineError(RuntimeError):
    pass


def load_config(path: Path) -> dict:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise PipelineError(f"Invalid config: {path}")
    return data


def semantic_config_digest(cfg: dict) -> str:
    encoded = json.dumps(cfg, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def rel(path: Path | str) -> str:
    value = Path(path)
    try:
        return str(value.resolve().relative_to(REPO_ROOT.resolve())).replace("\\", "/")
    except ValueError:
        return str(value).replace("\\", "/")


def quote(value: object) -> str:
    text = str(value)
    if not text or any(character.isspace() or character in '"&|<>^' for character in text):
        return subprocess.list2cmdline([text])
    return text


def command(parts: Iterable[object]) -> str:
    return " ".join(quote(part) for part in parts)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def source_sha256() -> str:
    files: set[Path] = set()
    for directory in ("common", "models", "export", "scripts", "docker"):
        root = REPO_ROOT / directory
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if path.is_file() and (path.suffix.lower() in {".py", ".yml", ".yaml"} or path.name.endswith("Dockerfile")):
                files.add(path)
    for path in (REPO_ROOT / "configs" / "experiment_config.yaml", REPO_ROOT / "requirements.txt"):
        if path.exists():
            files.add(path)
    digest = hashlib.sha256()
    for path in sorted(files, key=lambda item: rel(item)):
        name = rel(path).encode("utf-8")
        content = path.read_bytes()
        digest.update(len(name).to_bytes(8, "big"))
        digest.update(name)
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return digest.hexdigest()


def runtime_environment() -> dict[str, object]:
    packages = {}
    for name in ("numpy", "pandas", "scikit-learn", "torch", "sqlparse", "PyYAML"):
        try:
            packages[name] = importlib_metadata.version(name)
        except importlib_metadata.PackageNotFoundError:
            packages[name] = None
    return {"python": platform.python_version(), "platform": platform.platform(), "packages": packages}


def write_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def results_root(cfg: dict) -> Path:
    return repo_path(cfg["outputs"]["results_root"])


def work_dir(cfg: dict) -> Path:
    return repo_path(cfg["dataset"]["work_dir"])


def output_dir(cfg: dict, phase: str, method: str, family: str, scenario: str, ratio: str, variant_id: str = "") -> Path:
    base = results_root(cfg) / phase / method / family / scenario / f"R{ratio}"
    return base / variant_id if variant_id else base


def model_train_command(method: str, dataset: Path, holdout: Path, out_dir: Path, family: str, scenario: str, phase: str, ratio: str, cfg: dict, variant: dict | None = None) -> str:
    seed = int(cfg["seed"])
    n_samples = int(cfg["generation"]["n_samples"])
    parts: list[object] = [sys.executable, "scripts/run_pipeline.py", "--model", method, "--", "--dataset", rel(dataset), "--out-dir", rel(out_dir), "--family", family, "--n-samples", n_samples, "--seed", seed]
    if method == "smote":
        parts.extend(["--k-neighbors", int(cfg["generation"]["smote"]["k_neighbors"])])
    elif method == "gan":
        block = cfg["generation"]["gan"]
        parts.extend(["--epochs", int(block["epochs"]), "--batch-size", int(block["batch_size"]), "--noise-dim", int(block["noise_dim"]), "--hidden-dim", int(block["hidden_dim"]), "--lr", float(block["learning_rate"])])
    elif method == "ctgan":
        block = cfg["generation"]["ctgan"]
        parts.extend(["--epochs", int(block["epochs"]), "--batch-size", int(block["batch_size"])])
    elif method == "seqgan_master":
        block = cfg["generation"]["seqgan_master"]
        parts.extend([
            "--holdout-ref", rel(holdout), "--scenario", scenario, "--phase", phase, "--ratio", ratio,
            "--sequence-length", int(block["sequence_length"]),
            "--g-pretrain-epochs", int(block["generator_pretrain_epochs"]),
            "--d-pretrain-steps", int(block["discriminator_pretrain_steps"]),
            "--d-pretrain-epochs", int(block["discriminator_pretrain_epochs"]),
            "--adv-epochs", int(block["adversarial_epochs"]),
            "--g-steps", int(block["generator_steps"]),
            "--d-steps", int(block["discriminator_steps"]),
            "--d-epochs", int(block["discriminator_epochs"]),
            "--rollout-num", int(block["rollout_count"]),
        ])
    elif method == "seqgan_improved":
        if variant is None:
            raise PipelineError("SeqGAN cải tiến requires a variant")
        block = cfg["generation"]["seqgan_improved"]
        reward_mode = "on" if bool(variant["sql_reward"]) else "off"
        parts.extend([
            "--holdout-ref", rel(holdout), "--scenario", scenario, "--phase", phase, "--ratio", ratio,
            "--config", "seqgan_improved", "--variant-id", variant["id"],
            "--tokenizer-mode", variant["tokenizer_mode"],
            "--generator-reward-mode", reward_mode,
            "--reward-alpha", float(cfg["phase3"]["discriminator_reward_weight"]),
            "--sequence-length", int(variant["sequence_length"]),
            "--g-pretrain-epochs", int(variant["generator_pretrain_epochs"]),
            "--d-pretrain-steps", int(block["discriminator_pretrain_steps"]),
            "--d-pretrain-epochs", int(block["discriminator_pretrain_epochs"]),
            "--adv-epochs", int(block["adversarial_epochs"]),
            "--g-steps", int(block["generator_steps"]),
            "--d-steps", int(block["discriminator_steps"]),
            "--d-epochs", int(block["discriminator_epochs"]),
            "--rollout-num", int(block["rollout_count"]),
        ])
    return command(parts)


def quality_command(method: str, family: str, scenario: str, ratio: str, dataset: Path, holdout: Path, out_dir: Path, cfg: dict) -> str:
    generation_kind = "retrieval" if method in {"smote", "gan", "ctgan"} else "direct"
    return command([
        sys.executable, "common/quality_metrics.py", "score",
        "--generated", rel(out_dir / "generated_payloads.csv"),
        "--method", method,
        "--family", family,
        "--scenario", scenario,
        "--ratio", ratio,
        "--train-ref", rel(dataset),
        "--holdout-ref", rel(holdout),
        "--seed", int(cfg["seed"]),
        "--requested-count", int(cfg["generation"]["n_samples"]),
        "--generation-kind", generation_kind,
        "--self-bleu-sample-size", int(cfg["quality"]["self_bleu_sample_size"]),
        "--out", rel(out_dir / "quality_metrics.json"),
    ])


def rf_command(dataset: Path, holdout: Path, out_dir: Path, cfg: dict) -> str:
    prepared = work_dir(cfg)
    return command([
        sys.executable, "export/classifier_export/rf_eval.py",
        "--normal-train", rel(prepared / "splits" / "normal_train.csv"),
        "--normal-test", rel(prepared / "splits" / "normal_test.csv"),
        "--attack-train", rel(dataset),
        "--attack-holdout", rel(holdout),
        "--generated", rel(out_dir / "generated_payloads.csv"),
        "--seed", int(cfg["seed"]),
        "--n-estimators", int(cfg["detector"]["n_estimators"]),
        "--out", rel(out_dir / "rf_metrics.json"),
    ])


def make_spec(phase: str, method: str, family: str, scenario: str, ratio: str, dataset: Path, holdout: Path, cfg: dict, data_status: str = "ready", variant: dict | None = None) -> RunSpec:
    variant_id = str(variant["id"]) if variant else ""
    out = output_dir(cfg, phase, method, family, scenario, ratio, variant_id)
    run_id = "__".join(value for value in (phase, method, family, scenario, f"R{ratio}", variant_id) if value)
    return RunSpec(
        phase=phase,
        run_id=run_id,
        method=method,
        family=family,
        scenario=scenario,
        ratio=ratio,
        variant_id=variant_id,
        dataset=rel(dataset),
        holdout_ref=rel(holdout),
        out_dir=rel(out),
        data_status=data_status,
        config_digest=semantic_config_digest(cfg),
        train_command=model_train_command(method, dataset, holdout, out, family, scenario, phase, ratio, cfg, variant),
        quality_command=quality_command(method, family, scenario, ratio, dataset, holdout, out, cfg),
        rf_command=rf_command(dataset, holdout, out, cfg),
    )


def phase1_matrix(cfg: dict) -> list[RunSpec]:
    prepared = work_dir(cfg)
    dataset = prepared / "phase1" / "attack_train.csv"
    holdout = prepared / "phase1" / "attack_holdout.csv"
    status = "ready" if dataset.exists() and holdout.exists() else "missing_prepared_data"
    return [make_spec("phase1", method, "all", "raw", "full", dataset, holdout, cfg, status) for method in cfg["phase1"]["methods"]]


def phase2a_status(cfg: dict) -> dict[tuple[str, str], str]:
    manifest_path = work_dir(cfg) / "dataset_manifest.json"
    if not manifest_path.exists():
        return {}
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    phase = manifest.get("phase2a", {})
    if not phase.get("feasible", False):
        status = {(str(row["family"]), str(row["scenario"])): str(row["status"]) for row in phase.get("cells", [])}
        return {key: (value if value != "ready" else "blocked_by_exact_count_preflight") for key, value in status.items()}
    return {(str(row["family"]), str(row["scenario"])): str(row["status"]) for row in phase.get("cells", [])}


def phase2a_matrix(cfg: dict) -> list[RunSpec]:
    prepared = work_dir(cfg)
    ratio = str(cfg["phase2a"]["ratio"])
    statuses = phase2a_status(cfg)
    rows: list[RunSpec] = []
    for family in cfg["families"]:
        holdout = prepared / "splits" / f"{family}_holdout.csv"
        for method in cfg["phase2a"]["methods"]:
            for scenario in cfg["scenarios"]:
                dataset = prepared / "phase2a" / family / scenario / "attack_train.csv"
                status = statuses.get((family, scenario), "missing_preflight")
                rows.append(make_spec("phase2a", method, family, scenario, ratio, dataset, holdout, cfg, status))
    return rows


def phase2b_matrix(cfg: dict) -> list[RunSpec]:
    prepared = work_dir(cfg)
    manifest_path = prepared / "phase2b" / "dataset_manifest.json"
    if not manifest_path.exists():
        raise PipelineError("Phase 2B datasets are missing; run prepare-phase2b after Phase 2A ranking")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    rows: list[RunSpec] = []
    for cell in manifest["rows"]:
        family, scenario, ratio = str(cell["family"]), str(cell["scenario"]), str(cell["ratio"])
        dataset = repo_path(cell["output"])
        holdout = prepared / "splits" / f"{family}_holdout.csv"
        for method in cfg["phase2b"]["methods"]:
            rows.append(make_spec("phase2b", method, family, scenario, ratio, dataset, holdout, cfg, str(cell["status"])))
    return rows


def phase3_matrix(cfg: dict) -> list[RunSpec]:
    prepared = work_dir(cfg)
    manifest_path = prepared / "frozen" / "dataset_manifest.json"
    if not manifest_path.exists():
        raise PipelineError("Frozen Phase 3 datasets are missing; select a global ratio and run freeze-phase3")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    ratio = str(manifest["selected_global_ratio"])
    rows: list[RunSpec] = []
    for item in manifest["files"]:
        family, scenario = str(item["family"]), str(item["scenario"])
        dataset = repo_path(item["path"])
        holdout = prepared / "splits" / f"{family}_holdout.csv"
        for variant in cfg["phase3"]["variants"]:
            rows.append(make_spec("phase3", "seqgan_improved", family, scenario, ratio, dataset, holdout, cfg, "ready", variant))
    return rows


def selected_variant(cfg: dict) -> dict:
    path = results_root(cfg) / "phase3" / "selected_seqgan_variant.json"
    if not path.exists():
        raise PipelineError("Selected SeqGAN cải tiến variant is missing")
    selected = json.loads(path.read_text(encoding="utf-8"))
    variant_id = str(selected.get("selected_variant", selected.get("variant_id", "")))
    for variant in cfg["phase3"]["variants"]:
        if str(variant["id"]) == variant_id:
            return variant
    raise PipelineError(f"Unknown selected variant: {variant_id}")


def final_matrix(cfg: dict) -> list[RunSpec]:
    prepared = work_dir(cfg)
    manifest_path = prepared / "frozen" / "dataset_manifest.json"
    if not manifest_path.exists():
        raise PipelineError("Frozen datasets are missing")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    ratio = str(manifest["selected_global_ratio"])
    improved = selected_variant(cfg)
    rows: list[RunSpec] = []
    for item in manifest["files"]:
        family, scenario = str(item["family"]), str(item["scenario"])
        dataset = repo_path(item["path"])
        holdout = prepared / "splits" / f"{family}_holdout.csv"
        for method in (*BASELINE_METHODS, "seqgan_improved"):
            rows.append(make_spec("final", method, family, scenario, ratio, dataset, holdout, cfg, "ready", improved if method == "seqgan_improved" else None))
    return rows


def build_matrix(cfg: dict, phase: str) -> list[RunSpec]:
    builders = {"phase1": phase1_matrix, "phase2a": phase2a_matrix, "phase2b": phase2b_matrix, "phase3": phase3_matrix, "final": final_matrix}
    if phase not in builders:
        raise PipelineError(f"Unknown phase: {phase}")
    rows = builders[phase](cfg)
    expected = {"phase1": 4, "phase2a": 96, "phase2b": 224, "phase3": 64, "final": 40}[phase]
    if len(rows) != expected:
        raise PipelineError(f"{phase} matrix has {len(rows)} rows; expected {expected}")
    return rows


def write_matrix(rows: Sequence[RunSpec], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = tuple(RunSpec.__dataclass_fields__)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow(asdict(row))


def read_matrix(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def run_step(command_text: str, log_path: Path) -> int:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w", encoding="utf-8") as log:
        process = subprocess.run(command_text, cwd=REPO_ROOT, shell=True, stdout=log, stderr=subprocess.STDOUT, text=True)
    return int(process.returncode)


def run_matrix(path: Path, execute: bool, steps: Sequence[str], resume: bool, continue_on_error: bool, config_path: Path) -> int:
    rows = read_matrix(path)
    config = load_config(config_path)
    configured_seed = int(config["seed"])
    current_config_digest = semantic_config_digest(config)
    stale_rows = [row.get("run_id", "") for row in rows if row.get("config_digest") != current_config_digest]
    if stale_rows:
        raise PipelineError(f"Matrix config digest does not match {config_path}; regenerate the matrix")
    if not execute:
        for row in rows:
            print(f"{row['run_id']} [{row['data_status']}]")
            for step in steps:
                print(row[f"{step}_command"])
        print(f"Planned runs: {len(rows)}")
        return 0
    current_source_hash = source_sha256()
    environment = runtime_environment()
    failures = 0
    for row in rows:
        out = repo_path(row["out_dir"])
        manifest_path = out / "run_manifest.json"
        if row["data_status"] != "ready":
            write_json(manifest_path, {"run_id": row["run_id"], "status": "blocked_data", "data_status": row["data_status"], "seed": configured_seed})
            failures += 1
            if not continue_on_error:
                return 2
            continue
        if resume and manifest_path.exists():
            existing = json.loads(manifest_path.read_text(encoding="utf-8"))
            existing_inputs = existing.get("inputs") if isinstance(existing.get("inputs"), dict) else {}
            dataset_input = existing_inputs.get("dataset") if isinstance(existing_inputs.get("dataset"), dict) else {}
            holdout_input = existing_inputs.get("holdout") if isinstance(existing_inputs.get("holdout"), dict) else {}
            current_config_hash = sha256_file(config_path)
            current_dataset_hash = sha256_file(repo_path(row["dataset"])) if repo_path(row["dataset"]).exists() else ""
            current_holdout_hash = sha256_file(repo_path(row["holdout_ref"])) if repo_path(row["holdout_ref"]).exists() else ""
            existing_commands = existing.get("commands") if isinstance(existing.get("commands"), dict) else {}
            commands_match = all(existing_commands.get(step) == row[f"{step}_command"] for step in steps)
            inputs_match = (
                existing.get("seed") == configured_seed
                and existing.get("config_sha256") == current_config_hash
                and existing.get("source_sha256") == current_source_hash
                and dataset_input.get("sha256") == current_dataset_hash
                and holdout_input.get("sha256") == current_holdout_hash
            )
            if existing.get("status") == "completed" and inputs_match and commands_match and all((out / {"train": "training_metadata.json", "quality": "quality_metrics.json", "rf": "rf_metrics.json"}[step]).exists() for step in steps):
                continue
        dataset = repo_path(row["dataset"])
        holdout = repo_path(row["holdout_ref"])
        if not dataset.exists() or not holdout.exists():
            write_json(manifest_path, {"run_id": row["run_id"], "status": "missing_input", "dataset": row["dataset"], "holdout_ref": row["holdout_ref"], "seed": configured_seed})
            failures += 1
            if not continue_on_error:
                return 2
            continue
        manifest: dict[str, object] = {
            "schema_version": 1,
            "run_id": row["run_id"],
            "phase": row["phase"],
            "method": row["method"],
            "family": row["family"],
            "scenario": row["scenario"],
            "ratio": row["ratio"],
            "variant_id": row["variant_id"],
            "seed": configured_seed,
            "status": "running",
            "started_at": now_utc(),
            "config": rel(config_path),
            "config_sha256": sha256_file(config_path),
            "config_digest": current_config_digest,
            "source_sha256": current_source_hash,
            "environment": environment,
            "inputs": {
                "dataset": {"path": row["dataset"], "sha256": sha256_file(dataset)},
                "holdout": {"path": row["holdout_ref"], "sha256": sha256_file(holdout)},
            },
            "commands": {step: row[f"{step}_command"] for step in steps},
        }
        write_json(manifest_path, manifest)
        failed_step = ""
        for step in steps:
            code = run_step(row[f"{step}_command"], out / "logs" / f"{step}.log")
            if code != 0:
                failed_step = step
                manifest["status"] = "failed"
                manifest["failed_step"] = step
                manifest["exit_code"] = code
                break
        if not failed_step:
            manifest["status"] = "completed"
        manifest["ended_at"] = now_utc()
        write_json(manifest_path, manifest)
        if failed_step:
            failures += 1
            if not continue_on_error:
                return 1
    return 1 if failures else 0


def call_python(parts: Sequence[object], dry_run: bool) -> int:
    full = [sys.executable, *map(str, parts)]
    print(command(full))
    return 0 if dry_run else subprocess.call(full, cwd=REPO_ROOT)


def cmd_prepare(args: argparse.Namespace) -> int:
    from common.ingestion import prepare

    manifest = prepare(args.config)
    phase2a = manifest["phase2a"]
    print(f"Prepared fixed data with seed {manifest['seed']}")
    print(f"Phase 2A target={phase2a['target_attack_count']} feasible={phase2a['feasible']}")
    if not phase2a["feasible"]:
        print(f"Preflight blocked: {phase2a['report']}")
    return 0


def cmd_preflight(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    manifest_path = work_dir(cfg) / "dataset_manifest.json"
    if not manifest_path.exists():
        raise PipelineError("Run prepare-data first")
    phase = json.loads(manifest_path.read_text(encoding="utf-8"))["phase2a"]
    print(json.dumps(phase, ensure_ascii=False, indent=2))
    return 0 if phase["feasible"] else 2


def cmd_matrix(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    rows = build_matrix(cfg, args.phase)
    path = args.out or results_root(cfg) / args.phase / "run_matrix.csv"
    write_matrix(rows, path)
    counts = Counter(row.data_status for row in rows)
    print(f"Wrote {len(rows)} rows to {path}")
    print(json.dumps(counts, ensure_ascii=False))
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    steps = ("train", "quality", "rf") if args.steps == "all" else tuple(part.strip() for part in args.steps.split(",") if part.strip())
    if not steps or any(step not in {"train", "quality", "rf"} for step in steps):
        raise PipelineError("Steps must be train, quality, rf, or all")
    return run_matrix(args.matrix, args.execute, steps, args.resume, args.continue_on_error, args.config)


def cmd_calibrate(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    root = results_root(cfg)
    return call_python([
        "common/quality_metrics.py", "calibrate-thresholds",
        "--results-root", root / "phase1",
        "--margin", float(cfg["quality"]["calibration_margin"]),
        "--max-rf-macro-f1-drop", float(cfg["detector"]["severe_macro_f1_drop"]),
        "--max-rf-attack-recall-drop", float(cfg["detector"]["severe_attack_recall_drop"]),
        "--out", root / "phase1" / "validity_thresholds.json",
    ], args.dry_run)


def cmd_rank_phase2a(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    root = results_root(cfg)
    return call_python([
        "scripts/rank_combinations.py", "rank-phase2a",
        "--results-root", root / "phase2a",
        "--thresholds", root / "phase1" / "validity_thresholds.json",
        "--ratio", str(cfg["phase2a"]["ratio"]),
        "--out", root / "phase2a" / "top2_scenarios_per_family.csv",
        "--details-out", root / "phase2a" / "ranking.csv",
    ], args.dry_run)


def cmd_prepare_phase2b(args: argparse.Namespace) -> int:
    from common.ingestion import materialize_phase2b

    cfg = load_config(args.config)
    selection = args.selection or results_root(cfg) / "phase2a" / "top2_scenarios_per_family.csv"
    manifest = materialize_phase2b(args.config, selection)
    ready = sum(row["status"] == "ready" for row in manifest["rows"])
    print(f"Phase 2B datasets: {ready}/{len(manifest['rows'])} ready")
    return 0


def cmd_select_ratio(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    root = results_root(cfg)
    return call_python([
        "scripts/rank_combinations.py", "select-ratio",
        "--results-root", root / "phase2b",
        "--thresholds", root / "phase1" / "validity_thresholds.json",
        "--cells", root / "phase2a" / "top2_scenarios_per_family.csv",
        "--ratios", *[str(value) for value in cfg["phase2b"]["ratios"]],
        "--out", root / "phase2b" / "selected_global_ratio.json",
        "--audit-out", root / "phase2b" / "viability.csv",
    ], args.dry_run)


def cmd_freeze(args: argparse.Namespace) -> int:
    from common.ingestion import freeze_phase3

    cfg = load_config(args.config)
    root = results_root(cfg)
    selection = args.selection or root / "phase2a" / "top2_scenarios_per_family.csv"
    ratio = args.ratio or root / "phase2b" / "selected_global_ratio.json"
    manifest = freeze_phase3(args.config, selection, ratio)
    print(f"Frozen {len(manifest['files'])} datasets at ratio {manifest['selected_global_ratio']}")
    return 0


def cmd_rank_phase3(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    root = results_root(cfg)
    frozen = work_dir(cfg) / "frozen" / "dataset_manifest.json"
    if not frozen.exists() and not args.dry_run:
        raise PipelineError("Frozen dataset manifest is missing")
    ratio = str(json.loads(frozen.read_text(encoding="utf-8"))["selected_global_ratio"]) if frozen.exists() else "SELECTED_RATIO"
    return call_python([
        "scripts/rank_combinations.py", "rank-phase3",
        "--results-root", root / "phase3",
        "--thresholds", root / "phase1" / "validity_thresholds.json",
        "--cells", root / "phase2a" / "top2_scenarios_per_family.csv",
        "--ratio", ratio,
        "--out", root / "phase3" / "variant_ranking.csv",
        "--details-out", root / "phase3" / "variant_ranking_details.csv",
        "--selected-out", root / "phase3" / "selected_seqgan_variant.json",
    ], args.dry_run)


def cmd_finalize(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    root = results_root(cfg)
    parts: list[object] = [
        "scripts/finalize_results.py",
        "--results-root", root,
        "--frozen-manifest", work_dir(cfg) / "frozen" / "dataset_manifest.json",
        "--selected-variant", root / "phase3" / "selected_seqgan_variant.json",
        "--out-dir", root / "final",
    ]
    if args.reuse:
        parts.append("--reuse")
    return call_python(parts, args.dry_run)


def cmd_waf_up(args: argparse.Namespace) -> int:
    parts = ["docker", "compose", "-f", str(REPO_ROOT / "docker" / "docker-compose.yml"), "up", "-d"]
    print(command(parts))
    return 0 if args.dry_run else subprocess.call(parts, cwd=REPO_ROOT)


def cmd_waf_down(args: argparse.Namespace) -> int:
    parts = ["docker", "compose", "-f", str(REPO_ROOT / "docker" / "docker-compose.yml"), "down"]
    print(command(parts))
    return 0 if args.dry_run else subprocess.call(parts, cwd=REPO_ROOT)


def cmd_evaluate_waf(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    parts: list[object] = [
        "scripts/evaluate_waf.py",
        "--input", args.input,
        "--target-url", args.target_url,
        "--out-dir", args.out_dir or results_root(cfg) / "waf",
        "--seed", int(cfg["seed"]),
    ]
    if args.max_payloads is not None:
        parts.extend(["--max-payloads", args.max_payloads])
    if args.allow_remote:
        parts.append("--allow-remote")
    return call_python(parts, args.dry_run)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    subparsers = parser.add_subparsers(dest="command", required=True)
    prepare = subparsers.add_parser("prepare-data")
    prepare.set_defaults(func=cmd_prepare)
    preflight = subparsers.add_parser("preflight-phase2a")
    preflight.set_defaults(func=cmd_preflight)
    matrix = subparsers.add_parser("matrix")
    matrix.add_argument("--phase", choices=("phase1", "phase2a", "phase2b", "phase3", "final"), required=True)
    matrix.add_argument("--out", type=Path)
    matrix.set_defaults(func=cmd_matrix)
    run = subparsers.add_parser("run-matrix")
    run.add_argument("--matrix", type=Path, required=True)
    run.add_argument("--steps", default="all")
    run.add_argument("--execute", action="store_true")
    run.add_argument("--resume", action="store_true")
    run.add_argument("--continue-on-error", action="store_true")
    run.set_defaults(func=cmd_run)
    calibrate = subparsers.add_parser("calibrate-phase1")
    calibrate.add_argument("--dry-run", action="store_true")
    calibrate.set_defaults(func=cmd_calibrate)
    rank2a = subparsers.add_parser("rank-phase2a")
    rank2a.add_argument("--dry-run", action="store_true")
    rank2a.set_defaults(func=cmd_rank_phase2a)
    prepare2b = subparsers.add_parser("prepare-phase2b")
    prepare2b.add_argument("--selection", type=Path)
    prepare2b.set_defaults(func=cmd_prepare_phase2b)
    ratio = subparsers.add_parser("select-ratio")
    ratio.add_argument("--dry-run", action="store_true")
    ratio.set_defaults(func=cmd_select_ratio)
    freeze = subparsers.add_parser("freeze-phase3")
    freeze.add_argument("--selection", type=Path)
    freeze.add_argument("--ratio", type=Path)
    freeze.set_defaults(func=cmd_freeze)
    rank3 = subparsers.add_parser("rank-phase3")
    rank3.add_argument("--dry-run", action="store_true")
    rank3.set_defaults(func=cmd_rank_phase3)
    finalize = subparsers.add_parser("finalize")
    finalize.add_argument("--reuse", action="store_true")
    finalize.add_argument("--dry-run", action="store_true")
    finalize.set_defaults(func=cmd_finalize)
    waf_up = subparsers.add_parser("waf-up")
    waf_up.add_argument("--dry-run", action="store_true")
    waf_up.set_defaults(func=cmd_waf_up)
    waf_down = subparsers.add_parser("waf-down")
    waf_down.add_argument("--dry-run", action="store_true")
    waf_down.set_defaults(func=cmd_waf_down)
    waf_eval = subparsers.add_parser("evaluate-waf")
    waf_eval.add_argument("--input", type=Path, required=True)
    waf_eval.add_argument("--target-url", default="http://127.0.0.1:8080/")
    waf_eval.add_argument("--out-dir", type=Path)
    waf_eval.add_argument("--max-payloads", type=int)
    waf_eval.add_argument("--allow-remote", action="store_true")
    waf_eval.add_argument("--dry-run", action="store_true")
    waf_eval.set_defaults(func=cmd_evaluate_waf)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        return int(args.func(args))
    except (PipelineError, OSError, ValueError, KeyError, json.JSONDecodeError, csv.Error) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
