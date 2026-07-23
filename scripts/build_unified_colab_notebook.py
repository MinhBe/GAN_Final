from __future__ import annotations

import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
OUTPUT = REPO_ROOT / "GAN_SQLi_Colab.ipynb"


def markdown(source: str) -> dict:
    return {
        "cell_type": "markdown",
        "metadata": {},
        "source": source.splitlines(keepends=True),
    }


def code(source: str) -> dict:
    return {
        "cell_type": "code",
        "execution_count": None,
        "metadata": {},
        "outputs": [],
        "source": source.splitlines(keepends=True),
    }


def activation_cell(flag: str, phase: str, label: str) -> dict:
    return code(
        f'''# KÍCH HOẠT {label}: đổi duy nhất False thành True rồi chạy ô này.
{flag} = False

if {flag}:
    run_phase("{phase}")
else:
    print("{label} chưa chạy ({flag}=False)")
'''
    )


cells = [
    markdown(
        """# GAN for SQLi — Full Colab pipeline

Notebook dùng một server L4 cho toàn bộ method. Phần đầu chỉ setup môi trường; mỗi phase có đúng một ô kích hoạt riêng ở cuối notebook. Tất cả cờ mặc định là `False` để `Run All` không vô tình chạy nhiều phase.

Kết quả bền vững: `/content/drive/MyDrive/GAN_SQLi_Colab/results`.
"""
    ),
    markdown("## 1. Mount Google Drive"),
    code(
        '''from google.colab import drive
drive.mount("/content/drive", force_remount=False)
'''
    ),
    markdown("## 2. Kiểm tra GPU, RAM, disk và compute unit"),
    code(
        '''import json
import os
import platform
import shutil
import subprocess
import sys
import time
from pathlib import Path

RUNTIME_STARTED = time.monotonic()


def _command_output(command):
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    output = result.stdout.strip() or result.stderr.strip()
    print(output if output else f"Không có output (exit={result.returncode})")
    return result.returncode


def check_colab_resources(compute_units=None, burn_rate_per_hour=None):
    print("=== Runtime ===")
    print("Python:", sys.version.split()[0], "| Platform:", platform.platform())
    print("\\n=== GPU ===")
    _command_output([
        "nvidia-smi",
        "--query-gpu=name,memory.total,memory.used,utilization.gpu",
        "--format=csv,noheader",
    ])
    print("\\n=== System RAM ===")
    _command_output(["free", "-h"])
    print("\\n=== Disk ===")
    _command_output(["df", "-h", "/content", "/content/drive"])
    elapsed = (time.monotonic() - RUNTIME_STARTED) / 3600
    print(f"\\nRuntime elapsed: {elapsed:.2f} giờ")
    if compute_units is None or burn_rate_per_hour is None:
        print("Compute unit: xem bằng cách rê chuột lên biểu tượng Colab ở status bar VS Code.")
        print("Nhập hai số ở ô kế tiếp để tính số giờ còn lại.")
    elif burn_rate_per_hour <= 0:
        print("burn_rate_per_hour phải > 0")
    else:
        print(f"Compute units còn: {compute_units:g} CU")
        print(f"Tốc độ: {burn_rate_per_hour:g} CU/giờ")
        print(f"Ước tính còn: {compute_units / burn_rate_per_hour:.2f} giờ")


check_colab_resources()
'''
    ),
    code(
        '''# Điền từ Colab status bar nếu muốn ước tính thời gian.
COMPUTE_UNITS_REMAINING = None
BURN_RATE_PER_HOUR = None

check_colab_resources(
    compute_units=COMPUTE_UNITS_REMAINING,
    burn_rate_per_hour=BURN_RATE_PER_HOUR,
)
'''
    ),
    markdown("## 3. Copy project sang ổ nhanh `/content`"),
    code(
        '''DRIVE_MOUNT = Path("/content/drive/MyDrive")
DRIVE_PROJECT = DRIVE_MOUNT / "GAN_for_SQLi"
DRIVE_RUN_ROOT = DRIVE_MOUNT / "GAN_SQLi_Colab"
LOCAL_PROJECT = Path("/content/GAN_for_SQLi")

assert DRIVE_MOUNT.is_dir(), "Google Drive chưa mount"
assert (DRIVE_PROJECT / "scripts/research_pipeline.py").is_file(), (
    f"Không tìm thấy project tại {DRIVE_PROJECT}"
)

DRIVE_RUN_ROOT.mkdir(parents=True, exist_ok=True)
shutil.copytree(
    DRIVE_PROJECT,
    LOCAL_PROJECT,
    dirs_exist_ok=True,
    ignore=shutil.ignore_patterns(
        "__pycache__", "*.pyc", "results", "results_smoke"
    ),
)
os.chdir(LOCAL_PROJECT)

print("Code:", LOCAL_PROJECT)
print("Results:", DRIVE_RUN_ROOT / "results")
'''
    ),
    markdown("## 4. Cài dependency và tạo config runtime"),
    code(
        '''%pip install -q -r requirements.txt

import pandas as pd
import torch
import yaml

assert torch.cuda.is_available(), "Notebook full yêu cầu Colab GPU server"
print("GPU:", torch.cuda.get_device_name(0))
'''
    ),
    code(
        '''config = yaml.safe_load(
    (LOCAL_PROJECT / "configs/experiment_config.yaml").read_text(encoding="utf-8")
)
config["outputs"]["results_root"] = str(DRIVE_RUN_ROOT / "results")

RUNTIME_CONFIG_DIR = Path("/content/colab_configs")
RUNTIME_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
FULL_CONFIG = RUNTIME_CONFIG_DIR / "full.yaml"
FULL_CONFIG.write_text(
    yaml.safe_dump(config, sort_keys=False),
    encoding="utf-8",
)

PIPELINE = [
    sys.executable,
    "scripts/research_pipeline.py",
    "--config",
    str(FULL_CONFIG),
]

print("Config:", FULL_CONFIG)
print("Results root:", config["outputs"]["results_root"])
'''
    ),
    markdown("## 5. Hàm điều phối dùng chung"),
    code(
        '''FINAL_COMMANDS = {
    "phase1": ["calibrate-phase1"],
    "phase2a": ["rank-phase2a"],
    "phase2b": ["select-ratio"],
    "phase3": ["rank-phase3"],
    "final": ["finalize"],
}


def phase_status(phase):
    phase_root = DRIVE_RUN_ROOT / "results" / phase
    records = []
    for path in sorted(phase_root.rglob("run_manifest.json")):
        item = json.loads(path.read_text(encoding="utf-8"))
        records.append({
            "run_id": item.get("run_id"),
            "status": item.get("status"),
            "failed_step": item.get("failed_step", ""),
            "started_at": item.get("started_at", ""),
            "ended_at": item.get("ended_at", ""),
        })
    frame = pd.DataFrame(records)
    display(frame)
    return frame


def prepare_phase(phase):
    if phase == "phase2a":
        result = subprocess.run([*PIPELINE, "preflight-phase2a"])
        if result.returncode != 0:
            raise RuntimeError(
                "Phase 2A bị chặn bởi exact-count preflight 1:20; không chạy full."
            )
    elif phase == "phase2b":
        subprocess.run([*PIPELINE, "prepare-phase2b"], check=True)
    elif phase == "phase3":
        subprocess.run([*PIPELINE, "freeze-phase3"], check=True)


def run_phase(phase):
    if phase not in FINAL_COMMANDS:
        raise ValueError(f"Unknown phase: {phase}")
    assert torch.cuda.is_available(), "Hãy chọn Colab L4 GPU server"
    print(f"\\n===== START {phase.upper()} =====")
    check_colab_resources(COMPUTE_UNITS_REMAINING, BURN_RATE_PER_HOUR)
    prepare_phase(phase)

    matrix_path = DRIVE_RUN_ROOT / "results" / phase / "run_matrix.csv"
    subprocess.run([*PIPELINE, "matrix", "--phase", phase], check=True)
    matrix = pd.read_csv(matrix_path)
    display(matrix[["run_id", "method", "data_status", "out_dir"]])
    blocked = matrix.loc[~matrix["data_status"].eq("ready")]
    if not blocked.empty:
        display(blocked[["run_id", "data_status"]])
        raise RuntimeError(f"{len(blocked)} run chưa ready; dừng trước khi train")

    subprocess.run([
        *PIPELINE,
        "run-matrix",
        "--matrix",
        str(matrix_path),
        "--steps",
        "all",
        "--execute",
        "--resume",
    ], check=True)

    status = phase_status(phase)
    if status.empty or not status["status"].eq("completed").all():
        raise RuntimeError(f"{phase} chưa hoàn tất toàn bộ run; chưa finalize")

    subprocess.run([*PIPELINE, *FINAL_COMMANDS[phase]], check=True)
    print(f"===== COMPLETED {phase.upper()} =====")
    check_colab_resources(COMPUTE_UNITS_REMAINING, BURN_RATE_PER_HOUR)
'''
    ),
    markdown(
        """## 6. Các ô kích hoạt phase

Chỉ đổi `False` thành `True` trong **một** ô rồi chạy riêng ô đó. Không cần sửa biến phase dùng chung.
"""
    ),
    markdown("### Phase 1 — 4 baseline run và calibrate thresholds"),
    activation_cell("RUN_PHASE_1", "phase1", "PHASE 1"),
    markdown("### Phase 2A — 96 run và scenario ranking"),
    activation_cell("RUN_PHASE_2A", "phase2a", "PHASE 2A"),
    markdown("### Phase 2B — 224 run và ratio selection"),
    activation_cell("RUN_PHASE_2B", "phase2b", "PHASE 2B"),
    markdown("### Phase 3 — 64 SeqGAN Improved run và variant ranking"),
    activation_cell("RUN_PHASE_3", "phase3", "PHASE 3"),
    markdown("### Final — 40 independent comparison run và tổng hợp"),
    activation_cell("RUN_PHASE_FINAL", "final", "FINAL"),
]


notebook = {
    "cells": cells,
    "metadata": {
        "kernelspec": {
            "display_name": "Python 3",
            "language": "python",
            "name": "python3",
        },
        "language_info": {"name": "python", "version": "3"},
    },
    "nbformat": 4,
    "nbformat_minor": 5,
}

OUTPUT.write_text(
    json.dumps(notebook, ensure_ascii=False, indent=1) + "\n",
    encoding="utf-8",
)
print(OUTPUT)
