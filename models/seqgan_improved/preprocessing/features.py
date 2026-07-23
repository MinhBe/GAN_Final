from __future__ import annotations

import math
import re
from collections import Counter

import numpy as np
import pandas as pd

SQL_KEYWORDS = [
    "select", "union", "where", "from", "and", "or", "insert", "update", "delete", "drop", "create",
    "alter", "sleep", "benchmark", "waitfor", "delay", "information_schema", "table", "column", "database",
    "cast", "convert", "concat", "substr", "substring", "ascii", "char", "load_file", "outfile", "exec",
]

PATTERNS = {
    "has_single_quote": r"'",
    "has_double_quote": r'"',
    "has_comment_dashdash": r"--",
    "has_comment_hash": r"#",
    "has_comment_block": r"/\*|\*/",
    "has_equal": r"=",
    "has_parentheses": r"[()]",
    "has_semicolon": r";",
    "has_percent_encoding": r"%[0-9a-fA-F]{2}",
    "has_hex_literal": r"0x[0-9a-fA-F]+",
    "has_concat_operator": r"\|\|",
}


def shannon_entropy(text: str) -> float:
    if not text:
        return 0.0
    counts = Counter(text)
    n = len(text)
    return float(-sum((c / n) * math.log2(c / n) for c in counts.values()))


def payload_features(text: str) -> dict[str, float]:
    s = str(text)
    lower = s.lower()
    n = len(s)
    chars = Counter(s)
    alpha = sum(ch.isalpha() for ch in s)
    digit = sum(ch.isdigit() for ch in s)
    space = sum(ch.isspace() for ch in s)
    punct = sum((not ch.isalnum()) and (not ch.isspace()) for ch in s)
    feats: dict[str, float] = {
        "length": float(n),
        "num_unique_chars": float(len(chars)),
        "entropy": shannon_entropy(s),
        "alpha_count": float(alpha),
        "digit_count": float(digit),
        "space_count": float(space),
        "punct_count": float(punct),
        "alpha_ratio": alpha / max(1, n),
        "digit_ratio": digit / max(1, n),
        "space_ratio": space / max(1, n),
        "punct_ratio": punct / max(1, n),
        "single_quote_count": float(s.count("'")),
        "double_quote_count": float(s.count('"')),
        "dash_count": float(s.count("-")),
        "slash_count": float(s.count("/")),
        "star_count": float(s.count("*")),
        "equals_count": float(s.count("=")),
        "semicolon_count": float(s.count(";")),
        "paren_count": float(s.count("(") + s.count(")")),
        "percent_count": float(s.count("%")),
        "underscore_count": float(s.count("_")),
        "comma_count": float(s.count(",")),
        "operator_count": float(sum(s.count(op) for op in ["=", "<", ">", "!", "+", "-", "*", "/", "|", "&"])),
    }
    for name, pattern in PATTERNS.items():
        feats[name] = float(bool(re.search(pattern, s)))
    for kw in SQL_KEYWORDS:
        feats[f"kw_{kw}"] = float(len(re.findall(r"\b" + re.escape(kw) + r"\b", lower)))
    feats["keyword_total"] = float(sum(feats[f"kw_{kw}"] for kw in SQL_KEYWORDS))
    return feats


def make_feature_dataframe(texts: list[str]) -> pd.DataFrame:
    rows = [payload_features(text) for text in texts]
    return pd.DataFrame(rows).replace([np.inf, -np.inf], 0.0).fillna(0.0)
