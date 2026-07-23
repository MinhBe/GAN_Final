from __future__ import annotations

import math
import re
from collections import Counter

import numpy as np
import pandas as pd

from models.smote.preprocessing.config import META_COLS


SQL_KEYWORDS = [
    "select", "union", "where", "from", "and", "or",
    "insert", "update", "delete", "drop", "create", "alter",
    "sleep", "benchmark", "waitfor", "delay",
    "information_schema", "table", "column", "database",
    "cast", "convert", "concat", "substr", "substring",
    "ascii", "char", "load_file", "outfile", "exec",
    "order", "by", "exists", "case", "when",
]

PATTERNS = {
    "has_single_quote":    r"'",
    "has_double_quote":    r'"',
    "has_comment_dashdash": r"--",
    "has_comment_hash":    r"#",
    "has_comment_block":   r"/\*|\*/",
    "has_equal":           r"=",
    "has_parentheses":     r"[()]",
    "has_semicolon":       r";",
    "has_percent_encoding": r"%[0-9a-fA-F]{2}",
    "has_hex_literal":     r"0x[0-9a-fA-F]+",
    "has_concat_operator": r"\|\|",
}

OPERATOR_CHARS = ["=", "<", ">", "!", "+", "-", "*", "/", "|", "&"]


def _entropy(text: str) -> float:
    if not text:
        return 0.0
    counts = Counter(text)
    n = len(text)
    return float(-sum((c / n) * math.log2(c / n) for c in counts.values()))


def _payload_features(text) -> dict[str, float]:
    s = "" if pd.isna(text) else str(text)
    lower = s.lower()
    n = len(s)
    chars = Counter(s)
    alpha = sum(ch.isalpha() for ch in s)
    digit = sum(ch.isdigit() for ch in s)
    space = sum(ch.isspace() for ch in s)
    punct = sum((not ch.isalnum()) and (not ch.isspace()) for ch in s)

    feats: dict[str, float] = {
        "length":           float(n),
        "num_unique_chars": float(len(chars)),
        "entropy":          _entropy(s),
        "alpha_count":      float(alpha),
        "digit_count":      float(digit),
        "space_count":      float(space),
        "punct_count":      float(punct),
        "alpha_ratio":      alpha / max(1, n),
        "digit_ratio":      digit / max(1, n),
        "space_ratio":      space / max(1, n),
        "punct_ratio":      punct / max(1, n),
        "single_quote_count": float(s.count("'")),
        "double_quote_count": float(s.count('"')),
        "dash_count":       float(s.count("-")),
        "slash_count":      float(s.count("/")),
        "star_count":       float(s.count("*")),
        "equals_count":     float(s.count("=")),
        "semicolon_count":  float(s.count(";")),
        "paren_count":      float(s.count("(") + s.count(")")),
        "percent_count":    float(s.count("%")),
        "underscore_count": float(s.count("_")),
        "comma_count":      float(s.count(",")),
        "operator_count":   float(sum(s.count(op) for op in OPERATOR_CHARS)),
    }

    for name, pattern in PATTERNS.items():
        feats[name] = float(bool(re.search(pattern, s)))

    for kw in SQL_KEYWORDS:
        feats[f"kw_{kw}"] = float(len(re.findall(r"\b" + re.escape(kw) + r"\b", lower)))

    feats["keyword_total"] = float(sum(feats[f"kw_{kw}"] for kw in SQL_KEYWORDS))
    return feats


def build_features(df: pd.DataFrame) -> pd.DataFrame:
    missing = set(META_COLS) - set(df.columns)
    if missing:
        raise ValueError(f"Missing columns: {sorted(missing)}")
    feature_rows = [_payload_features(x) for x in df["payload"]]
    feat_df = pd.DataFrame(feature_rows).replace([np.inf, -np.inf], 0.0).fillna(0.0)
    return pd.concat([df[META_COLS].reset_index(drop=True), feat_df], axis=1)


def feature_columns(df: pd.DataFrame) -> list[str]:
    return [c for c in df.columns if c not in META_COLS]
