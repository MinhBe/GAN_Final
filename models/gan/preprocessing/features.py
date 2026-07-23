
from __future__ import annotations

import math
import re
from collections import Counter

import numpy as np
import pandas as pd


SQL_KEYWORDS = [
    "select", "union", "where", "from", "sleep", "benchmark", "pg_sleep",
    "waitfor", "delay", "case", "when", "then", "else", "end", "exists",
    "order", "group", "having", "information_schema", "sysibm", "mysql",
    "sqlite", "substring", "substr", "ascii", "char", "cast", "convert",
    "concat", "update", "delete", "insert", "drop", "create", "table",
    "database", "user", "version", "and", "or", "not", "like", "by",
]


REGEX_FEATURES = {
    "url_encoded_count":      r"%[0-9a-fA-F]{2}",
    "hex_literal_count":      r"0x[0-9a-fA-F]+",
    "unicode_escape_count":   r"\\u[0-9a-fA-F]{4}",
    "comment_marker_count":   r"(--|#|/\*|\*/)",
    "comparison_op_count":    r"(=|<>|!=|>=|<=|>|<)",
    "function_call_count":    r"\b[a-zA-Z_][a-zA-Z0-9_]*\s*\(",
    "quoted_string_count":    r"'[^']*'|\"[^\"]*\"",
}

CHAR_FEATURES = {
    "single_quote_count": "'",
    "double_quote_count": '"',
    "dash_count":         "-",
    "hash_count":         "#",
    "slash_count":        "/",
    "backslash_count":    "\\",
    "left_paren_count":   "(",
    "right_paren_count":  ")",
    "comma_count":        ",",
    "semicolon_count":    ";",
    "equals_count":       "=",
    "greater_count":      ">",
    "less_count":         "<",
    "percent_count":      "%",
    "plus_count":         "+",
    "asterisk_count":     "*",
    "at_count":           "@",
}


SIGNAL_PATTERNS = {
    "boolean_signal":  r"\b(or|and)\b\s+[^\n]{0,30}(=|like|>|<)|1=1",
    "union_signal":    r"\bunion\b.{0,20}\bselect\b",
    "time_signal":     r"\b(sleep|pg_sleep|benchmark|waitfor|delay)\b",
    "error_signal":    r"\b(extractvalue|updatexml|floor|rand\(|cast\(|convert\()\b",
    "order_signal":    r"\border\b\s+\bby\b",
    "exists_signal":   r"\bexists\s*\(",
    "stacked_signal":  r";",
}


def _entropy(text: str) -> float:
    if not text:
        return 0.0
    counts = Counter(text)
    n = len(text)
    return float(-sum((c / n) * math.log2(c / n) for c in counts.values()))


def _count_word(text_lower: str, word: str) -> int:
    return len(re.findall(rf"(?<![a-zA-Z0-9_]){re.escape(word)}(?![a-zA-Z0-9_])", text_lower))


def extract_one(payload: object) -> dict[str, float]:
    s = "" if pd.isna(payload) else str(payload)
    sl = s.lower()
    n = len(s)
    safe_n = max(n, 1)
    alpha     = sum(ch.isalpha()   for ch in s)
    digits    = sum(ch.isdigit()   for ch in s)
    spaces    = sum(ch.isspace()   for ch in s)
    upper     = sum(ch.isupper()   for ch in s)
    lower_    = sum(ch.islower()   for ch in s)
    printable = sum(ch.isprintable() for ch in s)
    symbols   = sum((not ch.isalnum()) and (not ch.isspace()) for ch in s)

    feats: dict[str, float] = {
        "payload_length":  float(n),
        "alpha_count":     float(alpha),
        "digit_count":     float(digits),
        "space_count":     float(spaces),
        "upper_count":     float(upper),
        "lower_count":     float(lower_),
        "symbol_count":    float(symbols),
        "printable_ratio": float(printable / safe_n),
        "alpha_ratio":     float(alpha / safe_n),
        "digit_ratio":     float(digits / safe_n),
        "space_ratio":     float(spaces / safe_n),
        "symbol_ratio":    float(symbols / safe_n),
        "entropy":         _entropy(s),
    }

    for name, ch in CHAR_FEATURES.items():
        feats[name] = float(s.count(ch))

    for name, pat in REGEX_FEATURES.items():
        feats[name] = float(len(re.findall(pat, s, flags=re.IGNORECASE)))

    total_sql = 0
    for kw in SQL_KEYWORDS:
        val = _count_word(sl, kw)
        feats[f"kw_{kw}"] = float(val)
        total_sql += val
    feats["sql_keyword_total"] = float(total_sql)

    for name, pat in SIGNAL_PATTERNS.items():
        feats[name] = float(bool(re.search(pat, sl, flags=re.IGNORECASE)))

    return feats


def make_feature_dataframe(payloads: list[str]) -> pd.DataFrame:
    rows = [extract_one(p) for p in payloads]
    return pd.DataFrame(rows).replace([np.inf, -np.inf], 0.0).fillna(0.0)
