from __future__ import annotations

import math
import re
from collections import Counter
from typing import Iterable

import pandas as pd


_KW_RE = re.compile(
    r"\b(select|union|where|from|and|or|sleep|benchmark|extractvalue|updatexml|"
    r"version|information_schema|table_name|column_name|order|group|having|exists|"
    r"insert|update|delete|drop|create|load_file|pg_sleep|waitfor|delay)\b"
)

FEATURE_COLUMNS = [
    "length", "num_letters", "num_digits", "num_spaces",
    "num_single_quotes", "num_double_quotes", "num_parentheses",
    "num_commas", "num_semicolons", "num_equal", "num_dash", "num_slash",
    "num_backslash", "num_pipe", "num_ampersand", "num_percent",
    "num_hash", "num_at", "num_underscore", "num_angle", "num_plus",
    "num_star", "num_comment_tokens", "num_special",
    "ratio_digits", "ratio_spaces", "ratio_special",
    "entropy", "token_count", "avg_token_len", "max_token_len",
    "sql_keyword_count",
    "has_union_select", "has_boolean_pattern", "has_time_pattern",
    "has_error_pattern", "has_order_pattern", "has_stacked_pattern",
    "has_exists_pattern", "has_encoded_pattern",
]

_TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*|\d+|[^\w\s]", re.UNICODE)


def _entropy(text: str) -> float:
    if not text:
        return 0.0
    counts = Counter(text)
    n = len(text)
    return -sum((c / n) * math.log2(c / n) for c in counts.values())


def extract_features(payload: str) -> dict[str, float]:
    text = str(payload) if payload is not None else ""
    lower = text.lower()
    n = len(text)
    safe_n = max(n, 1)

    tokens = _TOKEN_RE.findall(text)
    tl = [len(t) for t in tokens] or [0]

    num_letters = sum(ch.isalpha() for ch in text)
    num_digits = sum(ch.isdigit() for ch in text)
    num_spaces = sum(ch.isspace() for ch in text)
    num_special = sum(not ch.isalnum() and not ch.isspace() for ch in text)

    return {
        "length": float(n),
        "num_letters": float(num_letters),
        "num_digits": float(num_digits),
        "num_spaces": float(num_spaces),
        "num_single_quotes": float(text.count("'")),
        "num_double_quotes": float(text.count('"')),
        "num_parentheses": float(text.count("(") + text.count(")")),
        "num_commas": float(text.count(",")),
        "num_semicolons": float(text.count(";")),
        "num_equal": float(text.count("=")),
        "num_dash": float(text.count("-")),
        "num_slash": float(text.count("/")),
        "num_backslash": float(text.count("\\")),
        "num_pipe": float(text.count("|")),
        "num_ampersand": float(text.count("&")),
        "num_percent": float(text.count("%")),
        "num_hash": float(text.count("#")),
        "num_at": float(text.count("@")),
        "num_underscore": float(text.count("_")),
        "num_angle": float(text.count("<") + text.count(">")),
        "num_plus": float(text.count("+")),
        "num_star": float(text.count("*")),
        "num_comment_tokens": float(text.count("--") + text.count("#") + text.count("/*") + text.count("*/")),
        "num_special": float(num_special),
        "ratio_digits": num_digits / safe_n,
        "ratio_spaces": num_spaces / safe_n,
        "ratio_special": num_special / safe_n,
        "entropy": _entropy(text),
        "token_count": float(len(tokens)),
        "avg_token_len": sum(tl) / max(len(tl), 1),
        "max_token_len": float(max(tl)),
        "sql_keyword_count": float(len(_KW_RE.findall(lower))),
        "has_union_select": float(bool(re.search(r"\bunion\b.*\bselect\b", lower, re.S))),
        "has_boolean_pattern": float(bool(re.search(r"\b(or|and)\b\s+['\"]?\d+['\"]?\s*=\s*['\"]?\d+", lower))),
        "has_time_pattern": float(bool(re.search(r"\b(sleep|pg_sleep|benchmark|waitfor\s+delay)\b", lower))),
        "has_error_pattern": float(bool(re.search(r"\b(extractvalue|updatexml|utl_inaddr)\b", lower))),
        "has_order_pattern": float(bool(re.search(r"\border\s+by\b", lower))),
        "has_stacked_pattern": float(";" in text),
        "has_exists_pattern": float(bool(re.search(r"\bexists\s*\(", lower))),
        "has_encoded_pattern": float(bool(re.search(r"(%[0-9a-f]{2}|0x[0-9a-f]+|char\s*\(|chr\s*\()", lower))),
    }


def feature_frame(payloads: Iterable[str]) -> pd.DataFrame:
    rows = [extract_features(p) for p in payloads]
    df = pd.DataFrame(rows)
    for col in FEATURE_COLUMNS:
        if col not in df.columns:
            df[col] = 0.0
    return df[FEATURE_COLUMNS].astype(float)
