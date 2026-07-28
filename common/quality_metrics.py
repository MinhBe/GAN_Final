from __future__ import annotations

import argparse
import csv
import html
import json
import math
import random
import re
import statistics
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path
from typing import Callable, Iterable, Sequence
from urllib.parse import unquote

import sqlparse
from sqlparse import tokens as sql_tokens

SEED = 88
FAMILIES = ("boolean", "union", "time", "error")
RETRIEVAL_METHODS = frozenset({"smote", "gan", "ctgan", "vanilla_gan"})
NORMALIZATION_VERSION = "nfkc_html_percent1_casefold_ws_quotes_v1"
METRIC_SCHEMA_VERSION = "quality-metrics-v4"

MOTIF_PATTERNS = {
    "boolean": {
        "logical_comparison": re.compile(r"\b(?:and|or)\b[^\r\n;]{0,120}?(?:=|<>|!=|<=|>=|\blike\b|\bis\b)", re.I),
        "numeric_tautology": re.compile(r"\b(?:and|or)\b\s*\(?\s*([+-]?\d+(?:\.\d+)?)\s*=\s*\1\b", re.I),
        "string_tautology": re.compile(r"\b(?:and|or)\b\s*(['\"])(.*?)\1\s*=\s*(['\"])(.*?)\3", re.I | re.S),
        "comment_terminated": re.compile(r"\b(?:and|or)\b.*?(?:--|#|/\*)", re.I | re.S),
    },
    "union": {
        "union_select": re.compile(r"\bunion\s+select\b", re.I),
        "union_all_select": re.compile(r"\bunion\s+all\s+select\b", re.I),
        "select_from": re.compile(r"\bselect\b.+?\bfrom\b", re.I | re.S),
        "column_probe": re.compile(r"\border\s+by\s+\d+|\bnull\s*(?:,\s*null)+", re.I),
    },
    "time": {
        "sleep": re.compile(r"\bsleep\s*\(", re.I),
        "benchmark": re.compile(r"\bbenchmark\s*\(", re.I),
        "waitfor_delay": re.compile(r"\bwaitfor\s+delay\b", re.I),
        "pg_sleep": re.compile(r"\bpg_sleep\s*\(", re.I),
        "dbms_lock_sleep": re.compile(r"\bdbms_lock\s*\.\s*sleep\b", re.I),
    },
    "error": {
        "extractvalue": re.compile(r"\bextractvalue\s*\(", re.I),
        "updatexml": re.compile(r"\bupdatexml\s*\(", re.I),
        "floor_rand": re.compile(r"\bfloor\s*\(\s*rand\s*\(", re.I),
        "exp_error": re.compile(r"\bexp\s*\(\s*~", re.I),
        "group_having": re.compile(r"\bgroup\s+by\b.+?\bhaving\b", re.I | re.S),
        "cast_int": re.compile(r"\bcast\s*\(.+?\bas\s+(?:signed\s+)?int(?:eger)?\b", re.I | re.S),
        "convert_using": re.compile(r"\bconvert\s*\(.+?\busing\b", re.I | re.S),
        "xmltype": re.compile(r"\bxmltype\s*\(", re.I),
    },
}

LEXICAL_TOKEN_RE = re.compile(
    r"--[^\r\n]*|/\*.*?\*/|\#[^\r\n]*|'(?:''|\\.|[^'])*'|\"(?:\"\"|\\.|[^\"])*\"|"
    r"0x[0-9a-f]+|\b\d+(?:\.\d+)?\b|\b[a-z_$][\w$]*\b|<>|!=|<=|>=|:=|&&|\|\||"
    r"[=<>+\-*/%(),.;]",
    re.I | re.S,
)
SQL_KEYWORD_RE = re.compile(
    r"\b(?:select|union|from|where|and|or|insert|update|delete|drop|group|order|by|having|into|values|exec|declare|cast|convert|sleep|benchmark|waitfor|delay)\b",
    re.I,
)
OPERATOR_RE = re.compile(r"<>|!=|<=|>=|:=|&&|\|\||[=<>+\-*/%]")
LITERAL_RE = re.compile(r"'(?:''|\\.|[^'])*'|\"(?:\"\"|\\.|[^\"])*\"|\b\d+(?:\.\d+)?\b", re.S)
FUNCTION_RE = re.compile(r"\b([a-z_$][\w$]*(?:\s*\.\s*[a-z_$][\w$]*)?)\s*\(", re.I)
COMMENT_RE = re.compile(r"--|#|/\*")
LOGICAL_RE = re.compile(r"\b(?:and|or)\b", re.I)


def normalize_payload(payload: str) -> str:
    text = unicodedata.normalize("NFKC", str(payload))
    text = html.unescape(text)
    text = unquote(text)
    text = text.translate(str.maketrans({"\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"', "\u0060": "'"}))
    return " ".join(text.casefold().split())


def load_payloads(path: str | Path, column: str = "payload", label_filter: str | None = None) -> list[str]:
    payloads, _ = inspect_payload_file(path, column=column, label_filter=label_filter)
    return payloads


def inspect_payload_file(
    path: str | Path,
    column: str = "payload",
    label_filter: str | None = None,
) -> tuple[list[str], bool]:
    source = Path(path)
    with source.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fields = [str(field or "").strip().lower() for field in (reader.fieldnames or [])]
        if column.lower() in fields:
            actual_column = (reader.fieldnames or [])[fields.index(column.lower())]
            label_column = None
            if "label" in fields:
                label_column = (reader.fieldnames or [])[fields.index("label")]
            values = []
            for row in reader:
                if label_filter is not None and label_column is not None:
                    if str(row.get(label_column) or "").strip().casefold() != label_filter.casefold():
                        continue
                value = row.get(actual_column)
                if value is not None and value != "":
                    values.append(str(value))
            return values, True
        if source.suffix.casefold() == ".csv":
            return [], False
        handle.seek(0)
        values = [line.rstrip("\r\n") for line in handle]
        return [value for value in values if value != ""], True


def lexical_tokens(payload: str) -> list[str]:
    return [match.group(0).casefold() for match in LEXICAL_TOKEN_RE.finditer(normalize_payload(payload))]


def character_trigrams(payload: str) -> frozenset[str]:
    text = normalize_payload(payload)
    if len(text) < 3:
        return frozenset({text}) if text else frozenset()
    return frozenset(text[index : index + 3] for index in range(len(text) - 2))


def jaccard(left: set | frozenset, right: set | frozenset) -> float:
    if not left and not right:
        return 1.0
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def _quantile(values: Sequence[float], probability: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(float(value) for value in values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def _summary(values: Sequence[float], prefix: str) -> dict[str, float]:
    clean = [float(value) for value in values if math.isfinite(float(value))]
    if not clean:
        return {f"{prefix}_mean": 0.0, f"{prefix}_median": 0.0, f"{prefix}_p90": 0.0}
    return {
        f"{prefix}_mean": statistics.fmean(clean),
        f"{prefix}_median": statistics.median(clean),
        f"{prefix}_p90": _quantile(clean, 0.90),
    }


def _entropy(values: Iterable[str]) -> float:
    counts = Counter(values)
    total = sum(counts.values())
    if total == 0 or len(counts) <= 1:
        return 0.0
    raw = -sum((count / total) * math.log(count / total) for count in counts.values())
    return raw / math.log(len(counts))


def _ngrams(tokens: Sequence[str], n: int) -> Counter[tuple[str, ...]]:
    if len(tokens) < n:
        return Counter()
    return Counter(tuple(tokens[index : index + n]) for index in range(len(tokens) - n + 1))


def _closest_reference_length(candidate_length: int, references: Sequence[Sequence[str]]) -> int:
    if not references:
        return candidate_length
    lengths = [len(reference) for reference in references]
    return min(lengths, key=lambda length: (abs(length - candidate_length), length))


def _reference_maxima(
    counters: Sequence[Counter[tuple[str, ...]]],
) -> dict[tuple[str, ...], tuple[int, set[int], int]]:
    mutable: dict[tuple[str, ...], list] = {}
    for index, counter in enumerate(counters):
        for gram, count in counter.items():
            entry = mutable.setdefault(gram, [0, set(), 0])
            if count > entry[0]:
                entry[2] = entry[0]
                entry[0] = count
                entry[1] = {index}
            elif count == entry[0]:
                entry[1].add(index)
            elif count > entry[2]:
                entry[2] = count
    return {gram: (values[0], values[1], values[2]) for gram, values in mutable.items()}


def self_bleu(payloads: Sequence[str], sample_size: int = 200, seed: int = SEED) -> float:
    if len(payloads) < 2:
        return 0.0
    tokenized = [list(normalize_payload(payload)) for payload in payloads]
    indices = list(range(len(tokenized)))
    if len(indices) > sample_size:
        indices = random.Random(seed).sample(indices, sample_size)
    counters_by_n = {
        n: [_ngrams(tokens, n) for tokens in tokenized]
        for n in range(1, 5)
    }
    maxima_by_n = {n: _reference_maxima(counters) for n, counters in counters_by_n.items()}
    scores = []
    for index in indices:
        candidate = tokenized[index]
        if not candidate:
            scores.append(0.0)
            continue
        precisions = []
        for n in range(1, 5):
            candidate_ngrams = counters_by_n[n][index]
            if not candidate_ngrams:
                precisions.append(1e-9)
                continue
            clipped = 0
            for gram, count in candidate_ngrams.items():
                maximum, maximum_indices, second = maxima_by_n[n][gram]
                reference_maximum = second if index in maximum_indices and len(maximum_indices) == 1 else maximum
                clipped += min(count, reference_maximum)
            precisions.append(max(clipped / sum(candidate_ngrams.values()), 1e-9))
        geometric_mean = math.exp(sum(math.log(value) for value in precisions) / 4)
        references = [tokens for other, tokens in enumerate(tokenized) if other != index]
        reference_length = _closest_reference_length(len(candidate), references)
        brevity_penalty = 1.0 if len(candidate) > reference_length else math.exp(1.0 - reference_length / len(candidate))
        scores.append(brevity_penalty * geometric_mean)
    return statistics.fmean(scores) if scores else 0.0


def _motif_matches(payload: str) -> dict[str, set[str]]:
    text = normalize_payload(payload)
    return {
        family: {name for name, pattern in patterns.items() if pattern.search(text)}
        for family, patterns in MOTIF_PATTERNS.items()
    }


def _parse_payload(payload: str) -> tuple[bool, list]:
    try:
        statements = sqlparse.parse(str(payload))
    except Exception:
        return False, []
    flattened = [
        token
        for statement in statements
        for token in statement.flatten()
        if not token.is_whitespace and str(token.value) != ""
    ]
    if not flattened:
        return False, []
    return any(token.ttype not in sql_tokens.Error for token in flattened), flattened


def _has_structure(payload: str, motif_matches: dict[str, set[str]]) -> bool:
    text = normalize_payload(payload)
    if any(motif_matches[family] for family in FAMILIES):
        return True
    has_keyword = bool(SQL_KEYWORD_RE.search(text))
    has_operator = bool(OPERATOR_RE.search(text))
    has_literal = bool(LITERAL_RE.search(text))
    has_function = bool(FUNCTION_RE.search(text))
    has_comment = bool(COMMENT_RE.search(text))
    has_logical = bool(LOGICAL_RE.search(text))
    return has_keyword and sum((has_operator, has_literal, has_function, has_comment, has_logical)) >= 2


def structural_quality(payloads: Sequence[str], family: str) -> dict[str, object]:
    target_families = FAMILIES if family in {"all", "mixed", "raw_baseline", "other"} else (family,)
    parsed_count = 0
    structured_count = 0
    payload_motif_hits = 0
    observed = {name: set() for name in target_families}
    family_hit_counts = Counter()
    inferred_counts = Counter()
    for payload in payloads:
        parsed, _ = _parse_payload(payload)
        matches = _motif_matches(payload)
        structured = _has_structure(payload, matches)
        parsed_count += int(parsed)
        structured_count += int(structured)
        matched_target = False
        for target in target_families:
            observed[target].update(matches[target])
            if matches[target]:
                family_hit_counts[target] += 1
                matched_target = True
        payload_motif_hits += int(matched_target)
        inferred = next((name for name in ("error", "time", "union", "boolean") if matches[name]), "other")
        inferred_counts[inferred] += 1
    count = len(payloads)
    total_motifs = sum(len(MOTIF_PATTERNS[name]) for name in target_families)
    observed_motifs = sum(len(observed[name]) for name in target_families)
    parse_rate = parsed_count / count if count else 0.0
    structure_rate = structured_count / count if count else 0.0
    motif_coverage = observed_motifs / total_motifs if total_motifs else 0.0
    motif_hit_rate = payload_motif_hits / count if count else 0.0
    garbage_rate = 1.0 - structure_rate if count else 1.0
    return {
        "sql_parse_rate": parse_rate,
        "sql_structure_rate": structure_rate,
        "family_motif_coverage": motif_coverage,
        "family_motif_hit_rate": motif_hit_rate,
        "garbage_rate": garbage_rate,
        "wellformed_rate": parse_rate,
        "shaped_rate": structure_rate,
        "family_motif_coverage_by_family": {
            name: len(observed[name]) / len(MOTIF_PATTERNS[name]) for name in target_families
        },
        "family_motif_hit_rate_by_family": {
            name: family_hit_counts[name] / count if count else 0.0 for name in target_families
        },
        "inferred_family_distribution": {
            name: inferred_counts[name] / count if count else 0.0 for name in (*FAMILIES, "other")
        },
    }


def uniqueness_stats(payloads: Sequence[str]) -> dict[str, float | int]:
    count = len(payloads)
    if count == 0:
        return {
            "n_generated": 0,
            "unique_rate": 0.0,
            "normalized_unique_rate": 0.0,
            "duplicate_rate": 1.0,
            "model_collapse_rate": 1.0,
            "dominant_payload_share": 1.0,
            "normalized_dominant_payload_share": 1.0,
        }
    exact = Counter(str(payload) for payload in payloads)
    normalized = Counter(normalize_payload(payload) for payload in payloads)
    unique_rate = len(exact) / count
    return {
        "n_generated": count,
        "unique_rate": unique_rate,
        "normalized_unique_rate": len(normalized) / count,
        "duplicate_rate": 1.0 - unique_rate,
        "model_collapse_rate": 1.0 - unique_rate,
        "dominant_payload_share": max(exact.values()) / count,
        "normalized_dominant_payload_share": max(normalized.values()) / count,
    }


def _overlap_rate(payloads: Sequence[str], reference: Sequence[str], transform: Callable[[str], str]) -> float:
    if not payloads or not reference:
        return 0.0
    reference_set = {transform(value) for value in reference}
    return sum(transform(value) in reference_set for value in payloads) / len(payloads)


def _levenshtein_similarity(left: str, right: str) -> float:
    if left == right:
        return 1.0
    if not left or not right:
        return 0.0
    if len(left) < len(right):
        left, right = right, left
    previous = list(range(len(right) + 1))
    for row_index, left_char in enumerate(left, 1):
        current = [row_index]
        for column_index, right_char in enumerate(right, 1):
            current.append(
                min(
                    current[-1] + 1,
                    previous[column_index] + 1,
                    previous[column_index - 1] + int(left_char != right_char),
                )
            )
        previous = current
    return 1.0 - previous[-1] / max(len(left), len(right))


def _feature_vector(payload: str) -> tuple[float, ...]:
    text = normalize_payload(payload)
    length = max(len(text), 1)
    return (
        min(len(text), 320) / 320,
        len(SQL_KEYWORD_RE.findall(text)) / length,
        len(OPERATOR_RE.findall(text)) / length,
        len(LITERAL_RE.findall(text)) / length,
        len(FUNCTION_RE.findall(text)) / length,
        len(COMMENT_RE.findall(text)) / length,
        sum(character.isdigit() for character in text) / length,
        sum(character.isalpha() for character in text) / length,
        sum(character.isspace() for character in text) / length,
        text.count("'") / length,
        text.count("(") / length,
        text.count(")") / length,
    )


def _cosine(left: Sequence[float], right: Sequence[float]) -> float:
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    return sum(a * b for a, b in zip(left, right)) / (left_norm * right_norm)


def nearest_input_stats(payloads: Sequence[str], reference: Sequence[str]) -> dict[str, float | int]:
    if not payloads or not reference:
        empty = {}
        for prefix in (
            "nearest_input_similarity",
            "nearest_char3_jaccard",
            "nearest_token_jaccard",
            "nearest_edit_similarity",
            "nearest_feature_cosine",
            "nearest_input_distance",
        ):
            empty.update(_summary([], prefix))
        empty.update(
            {
                "mean_nearest_similarity": 0.0,
                "median_nearest_similarity": 0.0,
                "p90_nearest_similarity": 0.0,
                "unique_nearest_payload_rate": 0.0,
                "dominant_retrieved_payload_share": 1.0 if payloads else 0.0,
                "nearest_reference_count": len(reference),
            }
        )
        return empty
    reference_grams = [character_trigrams(value) for value in reference]
    reference_tokens = [set(lexical_tokens(value)) for value in reference]
    reference_features = [_feature_vector(value) for value in reference]
    index: dict[str, set[int]] = defaultdict(set)
    for reference_index, grams in enumerate(reference_grams):
        for gram in grams:
            index[gram].add(reference_index)
    primary_values = []
    token_values = []
    edit_values = []
    cosine_values = []
    nearest_indices = []
    for payload in payloads:
        grams = character_trigrams(payload)
        hits: Counter[int] = Counter()
        for gram in grams:
            hits.update(index.get(gram, ()))
        if hits:
            nearest_index, intersection = min(
                hits.items(),
                key=lambda item: (
                    -(item[1] / (len(grams) + len(reference_grams[item[0]]) - item[1])),
                    item[0],
                ),
            )
            primary = intersection / (len(grams) + len(reference_grams[nearest_index]) - intersection)
        else:
            nearest_index = min(range(len(reference)), key=lambda candidate: (len(reference_grams[candidate]) != 0, candidate))
            primary = jaccard(grams, reference_grams[nearest_index])
        normalized_payload = normalize_payload(payload)
        normalized_reference = normalize_payload(reference[nearest_index])
        primary_values.append(primary)
        token_values.append(jaccard(set(lexical_tokens(payload)), reference_tokens[nearest_index]))
        edit_values.append(_levenshtein_similarity(normalized_payload, normalized_reference))
        cosine_values.append(_cosine(_feature_vector(payload), reference_features[nearest_index]))
        nearest_indices.append(nearest_index)
    nearest_counts = Counter(nearest_indices)
    distances = [1.0 - value for value in primary_values]
    result: dict[str, float | int] = {}
    result.update(_summary(primary_values, "nearest_input_similarity"))
    result.update(_summary(primary_values, "nearest_char3_jaccard"))
    result.update(_summary(token_values, "nearest_token_jaccard"))
    result.update(_summary(edit_values, "nearest_edit_similarity"))
    result.update(_summary(cosine_values, "nearest_feature_cosine"))
    result.update(_summary(distances, "nearest_input_distance"))
    result.update(
        {
            "mean_nearest_similarity": result["nearest_input_similarity_mean"],
            "median_nearest_similarity": result["nearest_input_similarity_median"],
            "p90_nearest_similarity": result["nearest_input_similarity_p90"],
            "unique_nearest_payload_rate": len(nearest_counts) / len(payloads),
            "dominant_retrieved_payload_share": max(nearest_counts.values()) / len(payloads),
            "nearest_reference_count": len(reference),
        }
    )
    return result


def overlap_stats(
    payloads: Sequence[str],
    train_ref: Sequence[str] | None,
    holdout_ref: Sequence[str] | None,
) -> dict[str, float | int]:
    train = list(train_ref or [])
    holdout = list(holdout_ref or [])
    result: dict[str, float | int] = {
        "train_reference_count": len(train),
        "holdout_reference_count": len(holdout),
        "exact_input_overlap": _overlap_rate(payloads, train, str),
        "normalized_input_overlap": _overlap_rate(payloads, train, normalize_payload),
        "exact_holdout_overlap": _overlap_rate(payloads, holdout, str),
        # Historical alias retained for existing aggregators and artifacts.
        "holdout_overlap": _overlap_rate(payloads, holdout, str),
        "normalized_holdout_overlap": _overlap_rate(payloads, holdout, normalize_payload),
    }
    result.update(nearest_input_stats(payloads, train))
    return result


def distinct_ngram_stats(payloads: Sequence[str]) -> dict[str, float]:
    tokenized = [lexical_tokens(payload) for payload in payloads]
    result = {}
    for n in (1, 2, 3):
        total = 0
        unique = set()
        for tokens in tokenized:
            grams = list(_ngrams(tokens, n).elements())
            total += len(grams)
            unique.update(grams)
        result[f"distinct_{n}"] = len(unique) / total if total else 0.0
    all_tokens = [token for tokens in tokenized for token in tokens]
    all_characters = [character for payload in payloads for character in normalize_payload(payload)]
    keywords = [token for token in all_tokens if SQL_KEYWORD_RE.fullmatch(token)]
    operators = [token for token in all_tokens if OPERATOR_RE.fullmatch(token)]
    functions = [name.casefold() for payload in payloads for name in FUNCTION_RE.findall(normalize_payload(payload))]
    comment_styles = []
    for payload in payloads:
        text = normalize_payload(payload)
        comment_styles.extend(style for style, pattern in (("dash", r"--"), ("hash", r"#"), ("block", r"/\*")) if re.search(pattern, text))
    zones = []
    for payload in payloads:
        length = len(payload)
        zones.append("le20" if length <= 20 else "le40" if length <= 40 else "le80" if length <= 80 else "le160" if length <= 160 else "gt160")
    result.update(
        {
            "lexical_diversity": len(set(all_tokens)) / len(all_tokens) if all_tokens else 0.0,
            "character_diversity": _entropy(all_characters),
            "token_diversity": _entropy(all_tokens),
            "keyword_diversity": _entropy(keywords),
            "operator_diversity": _entropy(operators),
            "function_diversity": _entropy(functions),
            "comment_style_diversity": len(set(comment_styles)) / 3.0,
            "length_zone_diversity": len(set(zones)) / 5.0 if zones else 0.0,
        }
    )
    return result


def compute_quality_metrics(
    payloads: Sequence[str],
    method: str,
    family: str,
    scenario: str,
    ratio: str | int,
    train_ref: Sequence[str] | None = None,
    holdout_ref: Sequence[str] | None = None,
    stop_reason: str = "",
    self_bleu_sample_size: int = 200,
    seed: int = SEED,
    schema_valid: bool = True,
    requested_count: int | None = None,
    generation_kind: str = "auto",
) -> dict[str, object]:
    values = [str(payload) for payload in payloads if payload is not None and str(payload) != ""]
    empty_payload_count = len(payloads) - len(values)
    normalized_method = method.casefold().replace("-", "_")
    retrieval = normalized_method in RETRIEVAL_METHODS if generation_kind == "auto" else generation_kind == "retrieval"
    row: dict[str, object] = {
        "metric_schema_version": METRIC_SCHEMA_VERSION,
        "normalization_version": NORMALIZATION_VERSION,
        "seed": seed,
        "method": method,
        "family": family,
        "scenario": scenario,
        "ratio": ratio,
        "generation_kind": "retrieval" if retrieval else "direct",
        "schema_valid": bool(schema_valid),
        "stop_reason": stop_reason or "n/a",
    }
    row.update(uniqueness_stats(values))
    row.update(structural_quality(values, family))
    row.update(overlap_stats(values, train_ref, holdout_ref))
    row.update(distinct_ngram_stats(values))
    row["self_bleu"] = self_bleu(values, sample_size=self_bleu_sample_size, seed=seed)
    row["self_bleu_char"] = row["self_bleu"]
    row["requested_count"] = requested_count
    row["requested_samples"] = requested_count
    row["actual_samples"] = len(values)
    row["empty_payload_count"] = empty_payload_count
    row["generated_count_fraction"] = (
        len(values) / requested_count if requested_count is not None and requested_count > 0 else None
    )
    return row


def _read_json(path: Path) -> dict[str, object] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError):
        return None
    return value if isinstance(value, dict) else None


def discover_quality_rows(root: Path) -> list[dict[str, object]]:
    rows = []
    for path in sorted(root.rglob("quality_metrics.json")):
        row = _read_json(path)
        if row is not None:
            row = dict(row)
            row["quality_metrics_path"] = str(path)
            rows.append(row)
    return rows


def _finite_values(rows: Sequence[dict[str, object]], key: str) -> list[float]:
    values = []
    for row in rows:
        value = row.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value)):
            values.append(float(value))
    return values


def derive_thresholds(
    rows: Sequence[dict[str, object]],
    margin: float = 0.05,
    max_rf_macro_f1_drop: float = 0.15,
    max_rf_attack_recall_drop: float = 0.20,
) -> dict[str, object]:
    usable = [
        row
        for row in rows
        if int(row.get("n_generated") or 0) > 0
        and bool(row.get("schema_valid", True))
        and int(row.get("seed") or -1) == SEED
    ]
    if not usable:
        raise ValueError("No nonempty schema-valid seed-88 Phase 1 metrics were supplied")
    direct = [row for row in usable if str(row.get("generation_kind") or "direct") == "direct"]
    retrieval = [row for row in usable if str(row.get("generation_kind") or "direct") == "retrieval"]

    def lower(source: Sequence[dict[str, object]], key: str, fallback: float = 0.0) -> float:
        values = _finite_values(source, key)
        return max(0.0, min(values) - margin) if values else fallback

    def upper(source: Sequence[dict[str, object]], key: str, fallback: float = 1.0) -> float:
        values = _finite_values(source, key)
        return min(1.0, max(values) + margin) if values else fallback

    generated_counts = [int(row.get("n_generated") or 0) for row in usable]
    thresholds = {
        "threshold_schema_version": "quality-thresholds-v1",
        "metric_schema_version": METRIC_SCHEMA_VERSION,
        "seed": SEED,
        "calibration_run_count": len(usable),
        "calibration_methods": sorted({str(row.get("method") or "") for row in usable}),
        "margin": margin,
        "required_metrics": [
            "n_generated",
            "sql_parse_rate",
            "sql_structure_rate",
            "family_motif_coverage",
            "garbage_rate",
            "exact_input_overlap",
            "normalized_input_overlap",
            "holdout_overlap",
            "mean_nearest_similarity",
            "unique_rate",
            "self_bleu",
            "distinct_1",
            "distinct_2",
            "distinct_3",
            "dominant_payload_share",
            "lexical_diversity",
        ],
        "common": {
            "min_generated_count": min(generated_counts) if generated_counts else 1,
            "min_generated_count_fraction": 1.0,
            "min_sql_parse_rate": lower(usable, "sql_parse_rate"),
            "min_sql_structure_rate": lower(usable, "sql_structure_rate"),
            "min_family_motif_coverage": lower(usable, "family_motif_coverage"),
            "max_garbage_rate": upper(usable, "garbage_rate"),
            "min_nearest_similarity": 0.0,
            "require_train_reference": True,
            "require_holdout_reference": True,
        },
        "direct": {
            "min_unique_rate": lower(direct, "unique_rate"),
            "max_dominant_payload_share": upper(direct, "dominant_payload_share"),
            "max_normalized_input_overlap": upper(direct, "normalized_input_overlap"),
        },
        "retrieval": {
            "min_unique_nearest_payload_rate": lower(retrieval, "unique_nearest_payload_rate"),
            "max_dominant_retrieved_payload_share": upper(retrieval, "dominant_retrieved_payload_share"),
        },
        "rf": {
            "max_macro_f1_drop": max_rf_macro_f1_drop,
            "max_attack_recall_drop": max_rf_attack_recall_drop,
        },
        "severe_stop_reasons": [
            "error",
            "exception",
            "nan_loss",
            "non_finite_loss",
            "empty_output",
            "training_failed",
            "vanishing_reward",
        ],
    }
    return thresholds


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False), encoding="utf-8")


def _write_csv(path: Path, rows: Sequence[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = sorted({key for row in rows for key in row})
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def cmd_score(args: argparse.Namespace) -> int:
    payloads, schema_valid = inspect_payload_file(args.generated)
    train_ref = load_payloads(args.train_ref, label_filter=args.reference_label) if args.train_ref else []
    holdout_ref = load_payloads(args.holdout_ref, label_filter=args.reference_label) if args.holdout_ref else []
    row = compute_quality_metrics(
        payloads,
        method=args.method,
        family=args.family,
        scenario=args.scenario,
        ratio=args.ratio,
        train_ref=train_ref,
        holdout_ref=holdout_ref,
        stop_reason=args.stop_reason,
        self_bleu_sample_size=args.self_bleu_sample_size,
        seed=args.seed,
        schema_valid=schema_valid,
        requested_count=args.requested_count,
        generation_kind=args.generation_kind,
    )
    _write_json(args.out, row)
    print(json.dumps(row, indent=2, ensure_ascii=False, allow_nan=False))
    return 0


def cmd_aggregate(args: argparse.Namespace) -> int:
    rows = discover_quality_rows(args.results_root)
    _write_csv(args.out, rows)
    print(f"Wrote {len(rows)} rows to {args.out}")
    return 0


def cmd_calibrate_thresholds(args: argparse.Namespace) -> int:
    rows = discover_quality_rows(args.results_root)
    if not rows:
        raise SystemExit(f"No quality_metrics.json found under {args.results_root}")
    thresholds = derive_thresholds(
        rows,
        margin=args.margin,
        max_rf_macro_f1_drop=args.max_rf_macro_f1_drop,
        max_rf_attack_recall_drop=args.max_rf_attack_recall_drop,
    )
    _write_json(args.out, thresholds)
    print(json.dumps(thresholds, indent=2, ensure_ascii=False, allow_nan=False))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="quality_metrics.py")
    commands = parser.add_subparsers(dest="command", required=True)

    score = commands.add_parser("score")
    score.add_argument("--generated", type=Path, required=True)
    score.add_argument("--method", required=True)
    score.add_argument("--family", choices=[*FAMILIES, "all", "mixed", "other", "raw_baseline"], required=True)
    score.add_argument("--scenario", default="A")
    score.add_argument("--ratio", default="full")
    score.add_argument("--train-ref", type=Path)
    score.add_argument("--holdout-ref", type=Path)
    score.add_argument("--reference-label", default="attack")
    score.add_argument("--stop-reason", default="")
    score.add_argument("--requested-count", type=int)
    score.add_argument("--generation-kind", choices=["auto", "direct", "retrieval"], default="auto")
    score.add_argument("--self-bleu-sample-size", type=int, default=200)
    score.add_argument("--seed", type=int, default=SEED)
    score.add_argument("--out", type=Path, required=True)
    score.set_defaults(func=cmd_score)

    aggregate = commands.add_parser("aggregate")
    aggregate.add_argument("--results-root", type=Path, required=True)
    aggregate.add_argument("--out", type=Path, required=True)
    aggregate.set_defaults(func=cmd_aggregate)

    calibrate = commands.add_parser("calibrate-thresholds")
    calibrate.add_argument("--results-root", type=Path, required=True)
    calibrate.add_argument("--out", type=Path, required=True)
    calibrate.add_argument("--margin", type=float, default=0.05)
    calibrate.add_argument("--max-rf-macro-f1-drop", type=float, default=0.15)
    calibrate.add_argument("--max-rf-attack-recall-drop", type=float, default=0.20)
    calibrate.set_defaults(func=cmd_calibrate_thresholds)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
