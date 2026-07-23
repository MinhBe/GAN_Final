from __future__ import annotations

import argparse
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_REPO_ROOT))

from models.seqgan_improved.runtime.train import build_parser as build_improved_parser
from models.seqgan_improved.runtime.train import run_training


def apply_baseline_defaults(args: argparse.Namespace) -> argparse.Namespace:
    # Các yếu tố định danh baseline: KHÔNG BAO GIỜ được đổi, bất kể mini hay full run.
    # Đây là điều làm seqgan_master khác seqgan_improved (xem README).
    args.config = "seqgan_master"
    args.method = "seqgan_master"
    args.variant_id = "MASTER"
    args.tokenizer_mode = "raw_character"
    args.generator_reward_mode = "off"
    args.reward_alpha = 1.0
    args.seed = 88
    args.disc_embed_dim = 64
    args.disc_filter_profile = "original"
    args.disc_label_smoothing = 0.0
    args.dropout = 0.25

    # Các tham số tốc độ/dung lượng: chỉ dùng giá trị full-scale này khi CLI KHÔNG
    # truyền gì (None), tức khi chạy standalone không qua research_pipeline.py.
    # Khi research_pipeline.py truyền --g-pretrain-epochs, --adv-epochs, --rollout-num...
    # (ví dụ từ cấu hình mini để chạy scouting 15-20 phút), các giá trị đó phải được
    # tôn trọng thay vì bị ép về 120/50/3/200/1/5/3/16 như trước đây.
    if getattr(args, "max_len", None) is None:
        args.max_len = 20
    if getattr(args, "g_pretrain_epochs", None) is None:
        args.g_pretrain_epochs = 120
    if getattr(args, "d_pretrain_steps", None) is None:
        args.d_pretrain_steps = 50
    if getattr(args, "d_pretrain_epochs", None) is None:
        args.d_pretrain_epochs = 3
    if getattr(args, "adv_epochs", None) is None:
        args.adv_epochs = 200
    if getattr(args, "g_steps", None) is None:
        args.g_steps = 1
    if getattr(args, "d_steps", None) is None:
        args.d_steps = 5
    if getattr(args, "d_epochs", None) is None:
        args.d_epochs = 3
    if getattr(args, "rollout_num", None) is None:
        args.rollout_num = 16
    return args


def build_parser() -> argparse.ArgumentParser:
    parser = build_improved_parser()
    parser.set_defaults(
        config="seqgan_master",
        method="seqgan_master",
        variant_id="MASTER",
        tokenizer_mode="raw_character",
        generator_reward_mode="off",
        reward_alpha=1.0,
        seed=88,
    )
    return parser


def main() -> None:
    args = apply_baseline_defaults(build_parser().parse_args())
    run_training(args)


if __name__ == "__main__":
    main()