from __future__ import annotations

import re

TIER_GARBAGE = 0.0
TIER_WELLFORMED = 0.5
TIER_INJECTION_SHAPED = 1.0

_TEMPLATE_KEYWORD = re.compile(r"<KW_([A-Z_]+)>")
_SQL_KEYWORDS = re.compile(
    r"\b(select|union|from|where|and|or|insert|update|delete|drop|group\s+by|order\s+by|having|exec|declare|cast|convert|sleep|benchmark|waitfor|delay|extractvalue|updatexml)\b",
    re.IGNORECASE,
)
_BOOLEAN_TAUTOLOGY = re.compile(
    r"(\bor\b|\band\b)\s+(?:['\"]?\s*\d+\s*['\"]?|['\"][^'\"]+['\"])\s*=\s*(?:['\"]?\s*\d+\s*['\"]?|['\"][^'\"]+['\"])",
    re.IGNORECASE,
)
_INJECTION_PATTERNS = {
    "boolean": re.compile(r"(\bor\b|\band\b).*?(=|like|is\s+not\s+null)|--|#", re.IGNORECASE),
    "union": re.compile(r"\bunion\b\s+(\ball\b\s+)?\bselect\b", re.IGNORECASE),
    "time": re.compile(r"\bsleep\s*\(|\bwaitfor\s+delay\b|\bbenchmark\s*\(|\bpg_sleep\s*\(", re.IGNORECASE),
    "error": re.compile(
        r"\bextractvalue\s*\(|\bupdatexml\s*\(|\bfloor\s*\(\s*rand\s*\(|\bgroup\s+by\b.*\bhaving\b|"
        r"\bexp\s*\(|\bxmltype\s*\(",
        re.IGNORECASE,
    ),
}
_COMMENT_OR_BREAK = re.compile(r"(--|#|/\*|\*/|;)")
_COMPARE_OR_OPERATOR = re.compile(r"(=|<>|!=|<=|>=|\blike\b|\bis\b)", re.IGNORECASE)
_QUOTES_OR_PARENS = re.compile(r"['\"()]")


def normalize_template_text(payload: str) -> str:
    text = str(payload)
    text = _TEMPLATE_KEYWORD.sub(lambda m: m.group(1).lower(), text)
    text = text.replace("<NUM>", "1")
    text = text.replace("<STR>", "'a'")
    text = text.replace("<HEX>", "0x1")
    text = text.replace("<ENC>", "%27")
    return text


def _has_sql_keyword(payload: str) -> bool:
    return bool(_SQL_KEYWORDS.search(payload))


def _has_injection_shape(payload: str, family: str) -> bool:
    text = normalize_template_text(payload)
    if family == "boolean" and _BOOLEAN_TAUTOLOGY.search(text):
        return True
    pattern = _INJECTION_PATTERNS.get(family)
    if pattern is not None and pattern.search(text):
        return True
    return bool(_has_sql_keyword(text) and _COMMENT_OR_BREAK.search(text))


def heuristic_score(payload: str, family: str) -> float:
    text = normalize_template_text(payload).strip()
    if not text:
        return 0.0
    score = 0.0
    if _has_sql_keyword(text):
        score += 0.25
    if _COMPARE_OR_OPERATOR.search(text):
        score += 0.15
    if _COMMENT_OR_BREAK.search(text):
        score += 0.15
    if _QUOTES_OR_PARENS.search(text):
        score += 0.10
    if _has_injection_shape(text, family):
        score += 0.45
    
    low = text.lower()
    if family == "boolean" and (" or " in f" {low} " or " and " in f" {low} "):
        score += 0.10
    elif family == "union" and ("union" in low or "select" in low):
        score += 0.10
    elif family == "time" and any(k in low for k in ["sleep", "waitfor", "delay", "benchmark", "pg_sleep"]):
        score += 0.10
    elif family == "error" and any(k in low for k in ["extractvalue", "updatexml", "floor", "rand", "having", "xmltype"]):
        score += 0.10
    return float(max(0.0, min(1.0, score)))


def classify_payload(payload: str, family: str) -> tuple[str, float]:
    score = heuristic_score(payload, family)
    if score >= 0.70:
        return "injection_shaped", TIER_INJECTION_SHAPED
    if score >= 0.35:
        return "wellformed", TIER_WELLFORMED
    return "garbage", TIER_GARBAGE


def batch_parser_reward(payloads: list[str], family: str) -> list[float]:
    return [heuristic_score(p, family) for p in payloads]


def batch_pass_rate(payloads: list[str], family: str) -> dict[str, float]:
    if not payloads:
        return {"garbage": 0.0, "wellformed": 0.0, "injection_shaped": 0.0}
    counts = {"garbage": 0, "wellformed": 0, "injection_shaped": 0}
    for p in payloads:
        tier, _ = classify_payload(p, family)
        counts[tier] += 1
    n = len(payloads)
    return {k: v / n for k, v in counts.items()}
