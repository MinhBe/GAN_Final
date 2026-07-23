from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable

import pandas as pd

FAMILIES = ("boolean", "union", "time", "error")
PAYLOAD_COLUMNS = ("payload", "sentence")
LABELS = {
    "1": "attack",
    "true": "attack",
    "attack": "attack",
    "malicious": "attack",
    "sqli": "attack",
    "sql injection": "attack",
    "0": "normal",
    "false": "normal",
    "normal": "normal",
    "benign": "normal",
    "clean": "normal",
}

_ERROR_RE = re.compile(
    r"\b(extractvalue|updatexml|xpath|floor\s*\(\s*rand|cast\s*\(|convert\s*\(|group\s+by.+having)\b",
    re.IGNORECASE | re.DOTALL,
)
_TIME_RE = re.compile(
    r"\b(sleep\s*\(|benchmark\s*\(|waitfor\s+delay|pg_sleep\s*\(|dbms_lock\s*\.\s*sleep)\b",
    re.IGNORECASE | re.DOTALL,
)
_UNION_RE = re.compile(r"\bunion\s+(?:all\s+)?select\b", re.IGNORECASE | re.DOTALL)
_BOOLEAN_RE = re.compile(
    r"\b(?:and|or)\b\s*(?:\(?\s*\d+\s*=\s*\d+|['\"][^'\"]*['\"]\s*=\s*['\"][^'\"]*['\"]|.+?(?:--|#))",
    re.IGNORECASE | re.DOTALL,
)


def normalize_label(value) -> str:
    text = str(value).strip().lower()
    return LABELS.get(text, text)


def infer_payload_type(payload: str, label: str) -> str:
    if normalize_label(label) == "normal":
        return "normal"
    text = str(payload)
    try:
        from common.ingestion import classify_family

        family = classify_family(text)
        return family if family in set(FAMILIES) else "other"
    except BaseException:
        if _ERROR_RE.search(text):
            return "error"
        if _TIME_RE.search(text):
            return "time"
        if _UNION_RE.search(text):
            return "union"
        if _BOOLEAN_RE.search(text):
            return "boolean"
        return "other"


def canonical_payload_frame(
    path: str | Path,
    *,
    include_other: bool = True,
    infer_types: bool = True,
) -> pd.DataFrame:
    df = pd.read_csv(Path(path), dtype=str, keep_default_na=False)
    cols = {str(c).strip().lower(): c for c in df.columns}

    payload_col = next((cols[c] for c in PAYLOAD_COLUMNS if c in cols), None)
    label_col = cols.get("label")
    if payload_col is None or label_col is None:
        raise ValueError(f"Expected columns label,payload. Got: {list(df.columns)}")

    out = pd.DataFrame(
        {
            "id": df[cols["id"]].astype(str) if "id" in cols else [f"R{i+1:06d}" for i in range(len(df))],
            "payload": df[payload_col].fillna("").astype(str),
            "label": df[label_col].map(normalize_label),
        }
    )

    if "payload_type" in cols or "family" in cols:
        type_column = cols.get("payload_type", cols.get("family"))
        out["payload_type"] = df[type_column].fillna("").astype(str).str.lower().str.strip()
    else:
        out["payload_type"] = "unknown"

    if infer_types:
        needs_type = out["payload_type"].isin(["", "unknown", "nan", "seqgan_generated"])
        out.loc[needs_type, "payload_type"] = [
            infer_payload_type(payload, label)
            for payload, label in zip(out.loc[needs_type, "payload"], out.loc[needs_type, "label"])
        ]
        out.loc[out["label"].eq("normal"), "payload_type"] = "normal"

    out = out[out["payload"].str.strip().ne("")].reset_index(drop=True)
    if not include_other:
        out = out[out["payload_type"].isin(["normal", *FAMILIES])].reset_index(drop=True)
    return out[["id", "label", "payload_type", "payload"]]


def write_two_column_dataset(path: str | Path, rows: Iterable[tuple[str, str]]) -> None:
    out_path = Path(path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows, columns=["label", "payload"]).to_csv(out_path, index=False)
