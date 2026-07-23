from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Iterable, Sequence

PAD_TOKEN = "<PAD>"
BOS_TOKEN = "<BOS>"
EOS_TOKEN = "<EOS>"
UNK_TOKEN = "<UNK>"
SPECIAL_TOKENS = (PAD_TOKEN, BOS_TOKEN, EOS_TOKEN, UNK_TOKEN)
SPECIAL_TOKEN_SET = set(SPECIAL_TOKENS)

SQL_KEYWORDS = (
    "all",
    "alter",
    "and",
    "ascii",
    "benchmark",
    "by",
    "case",
    "cast",
    "char",
    "column",
    "concat",
    "convert",
    "create",
    "database",
    "declare",
    "delay",
    "delete",
    "drop",
    "else",
    "end",
    "exec",
    "extractvalue",
    "floor",
    "from",
    "group",
    "having",
    "if",
    "information_schema",
    "insert",
    "into",
    "is",
    "like",
    "load_file",
    "not",
    "null",
    "or",
    "order",
    "outfile",
    "pg_sleep",
    "rand",
    "select",
    "sleep",
    "substr",
    "substring",
    "table",
    "then",
    "union",
    "update",
    "updatexml",
    "values",
    "waitfor",
    "when",
    "where",
    "xmltype",
)

_KEYWORD_PATTERN = "|".join(re.escape(value) for value in sorted(SQL_KEYWORDS, key=len, reverse=True))
_SQL_TOKEN_RE = re.compile(
    r"(?:%[0-9a-fA-F]{2})+"
    r"|0[xX][0-9a-fA-F]+"
    r"|'(?:''|\\.|[^'\\])*'"
    r'|"(?:""|\\.|[^"\\])*"'
    r"|--|/\*|\*/|#"
    r"|<=|>=|<>|!=|==|\|\||&&|:="
    r"|\b(?:" + _KEYWORD_PATTERN + r")\b"
    r"|\b\d+(?:\.\d+)?\b"
    r"|\s+",
    re.IGNORECASE,
)


def _ensure_unk(vocab: dict[str, int]) -> dict[str, int]:
    out = dict(vocab)
    if UNK_TOKEN not in out:
        out[UNK_TOKEN] = max(out.values(), default=-1) + 1
    return out


def _load_payload(path: str | Path) -> tuple[str, dict[str, int]]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Tokenizer file must contain a JSON object")
    mode = str(data.get("tokenizer_mode") or data.get("tokenizer_type") or "raw_character")
    raw_vocab = data.get("vocab", data)
    if not isinstance(raw_vocab, dict):
        raise ValueError("Tokenizer vocabulary must be a JSON object")
    vocab = _ensure_unk({str(key): int(value) for key, value in raw_vocab.items()})
    return mode, vocab


class RawCharacterTokenizer:
    tokenizer_mode = "raw_character"

    def __init__(self, token_to_id: dict[str, int] | None = None) -> None:
        self.token_to_id = token_to_id or {}
        self.id_to_token = {value: key for key, value in self.token_to_id.items()}

    @property
    def char2idx(self) -> dict[str, int]:
        return self.token_to_id

    @property
    def idx2char(self) -> dict[int, str]:
        return self.id_to_token

    @property
    def tokenizer_type(self) -> str:
        return self.tokenizer_mode

    @property
    def vocab_size(self) -> int:
        return len(self.token_to_id)

    @property
    def pad_id(self) -> int:
        return self.token_to_id[PAD_TOKEN]

    @property
    def bos_id(self) -> int:
        return self.token_to_id[BOS_TOKEN]

    @property
    def eos_id(self) -> int:
        return self.token_to_id[EOS_TOKEN]

    @property
    def unk_id(self) -> int:
        return self.token_to_id[UNK_TOKEN]

    def tokenize(self, text: str) -> list[str]:
        return list(str(text))

    def detokenize(self, tokens: Sequence[str]) -> str:
        return "".join(tokens)

    def build_vocab(self, texts: Iterable[str]) -> "RawCharacterTokenizer":
        observed: set[str] = set()
        for text in texts:
            observed.update(self.tokenize(str(text)))
        base = set(
            "abcdefghijklmnopqrstuvwxyz"
            "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
            "0123456789"
            " ' \"-=#/*(),.;_%<>!|&+:[\\]{}?@`~^\n\r\t"
        )
        tokens = list(SPECIAL_TOKENS) + sorted(observed | base)
        self.token_to_id = {token: index for index, token in enumerate(tokens)}
        self.id_to_token = {index: token for token, index in self.token_to_id.items()}
        return self

    def encode_for_lm(self, text: str, max_len: int) -> list[int]:
        if max_len <= 0:
            raise ValueError("max_len must be positive")
        content = self.tokenize(str(text))
        if len(content) >= max_len:
            sequence = content[:max_len]
        else:
            sequence = content + [EOS_TOKEN]
        ids = [self.bos_id]
        ids.extend(self.token_to_id.get(token, self.unk_id) for token in sequence)
        ids.extend([self.pad_id] * (max_len + 1 - len(ids)))
        return ids[: max_len + 1]

    def decode(self, ids: Sequence[int], stop_at_eos: bool = True) -> str:
        tokens: list[str] = []
        for value in ids:
            token = self.id_to_token.get(int(value), "")
            if token == EOS_TOKEN and stop_at_eos:
                break
            if token not in SPECIAL_TOKEN_SET:
                tokens.append(token)
        return self.detokenize(tokens)

    def save(self, path: str | Path) -> None:
        payload = {
            "schema_version": 2,
            "tokenizer_mode": self.tokenizer_mode,
            "vocab": self.token_to_id,
        }
        Path(path).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path) -> "RawCharacterTokenizer":
        mode, vocab = _load_payload(path)
        if mode not in {"raw_character", "raw_char", "raw", "char"}:
            raise ValueError(f"Tokenizer file contains mode {mode!r}, not raw_character")
        return cls(vocab)


class SQLAwareTokenizer(RawCharacterTokenizer):
    tokenizer_mode = "sql_aware"
    atomic_prefix = "A:"
    character_prefix = "C:"

    def tokenize(self, text: str) -> list[str]:
        source = str(text)
        tokens: list[str] = []
        position = 0
        for match in _SQL_TOKEN_RE.finditer(source):
            if match.start() > position:
                tokens.extend(self.character_prefix + char for char in source[position : match.start()])
            tokens.append(self.atomic_prefix + match.group(0))
            position = match.end()
        if position < len(source):
            tokens.extend(self.character_prefix + char for char in source[position:])
        return tokens

    def detokenize(self, tokens: Sequence[str]) -> str:
        output: list[str] = []
        for token in tokens:
            if token.startswith(self.atomic_prefix):
                output.append(token[len(self.atomic_prefix) :])
            elif token.startswith(self.character_prefix):
                output.append(token[len(self.character_prefix) :])
            else:
                output.append(token)
        return "".join(output)

    def build_vocab(self, texts: Iterable[str]) -> "SQLAwareTokenizer":
        observed: set[str] = set()
        for text in texts:
            observed.update(self.tokenize(str(text)))
        base_chars = set(
            "abcdefghijklmnopqrstuvwxyz"
            "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
            "0123456789"
            " ' \"-=#/*(),.;_%<>!|&+:[\\]{}?@`~^\n\r\t"
        )
        base = {self.character_prefix + value for value in base_chars}
        tokens = list(SPECIAL_TOKENS) + sorted(observed | base)
        self.token_to_id = {token: index for index, token in enumerate(tokens)}
        self.id_to_token = {index: token for token, index in self.token_to_id.items()}
        return self

    @classmethod
    def load(cls, path: str | Path) -> "SQLAwareTokenizer":
        mode, vocab = _load_payload(path)
        if mode not in {"sql_aware", "template", "template_token"}:
            raise ValueError(f"Tokenizer file contains mode {mode!r}, not sql_aware")
        return cls(vocab)


CharTokenizer = RawCharacterTokenizer
TemplateTokenizer = SQLAwareTokenizer


def make_tokenizer(mode: str) -> RawCharacterTokenizer:
    value = str(mode).strip().lower()
    if value == "raw_character":
        return RawCharacterTokenizer()
    if value == "sql_aware":
        return SQLAwareTokenizer()
    raise ValueError(f"Unsupported tokenizer mode {mode!r}")


def load_tokenizer(path: str | Path) -> RawCharacterTokenizer:
    mode, _ = _load_payload(path)
    if mode in {"raw_character", "raw_char", "raw", "char"}:
        return RawCharacterTokenizer.load(path)
    if mode in {"sql_aware", "template", "template_token"}:
        return SQLAwareTokenizer.load(path)
    raise ValueError(f"Unsupported tokenizer mode {mode!r}")
