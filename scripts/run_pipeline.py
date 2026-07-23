from __future__ import annotations

import argparse
import runpy
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
MODEL_ENTRYPOINTS = {
    "smote": REPO_ROOT / "models" / "smote" / "runtime" / "train.py",
    "gan": REPO_ROOT / "models" / "gan" / "runtime" / "train.py",
    "ctgan": REPO_ROOT / "models" / "ctgan" / "runtime" / "train.py",
    "seqgan_master": REPO_ROOT / "models" / "seqgan" / "runtime" / "train.py",
    "seqgan_improved": REPO_ROOT / "models" / "seqgan_improved" / "runtime" / "train.py",
}
MODEL_MODULES = {
    "seqgan_master": "models.seqgan.runtime.train",
    "seqgan_improved": "models.seqgan_improved.runtime.train",
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True, choices=sorted(MODEL_ENTRYPOINTS))
    return parser


def main() -> int:
    arguments = sys.argv[1:]
    split = arguments.index("--") if "--" in arguments else len(arguments)
    own, forwarded = arguments[:split], arguments[split + 1:] if split < len(arguments) else []
    args = build_parser().parse_args(own)
    entrypoint = MODEL_ENTRYPOINTS[args.model]
    if not entrypoint.exists():
        raise SystemExit(f"Missing model entrypoint: {entrypoint}")
    sys.argv = [str(entrypoint), *forwarded]
    sys.path.insert(0, str(REPO_ROOT))
    if args.model in MODEL_MODULES:
        runpy.run_module(MODEL_MODULES[args.model], run_name="__main__", alter_sys=False)
    else:
        runpy.run_path(str(entrypoint), run_name="__main__")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
