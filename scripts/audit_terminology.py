"""Audit canonical files for thesis-inconsistent scientific terminology.

Historical artifacts are intentionally excluded. The command exits 1 when a
canonical violation is found and can emit text or JSON for CI.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class Rule:
    code: str
    pattern: str
    replacement: str
    reason: str


@dataclass(frozen=True)
class Finding:
    rule: str
    path: str
    line: int
    context: str
    replacement: str
    reason: str


RULES = (
    Rule("seqgan-master-display", r"\bSeqGAN Master\b", "SeqGAN cơ sở", "Tên Master chỉ là alias kỹ thuật lịch sử."),
    Rule("seqgan-improved-display", r"\bSeqGAN Improved\b", "SeqGAN cải tiến", "Dùng tên học thuật đã chốt trong luận văn."),
    Rule("original-seqgan", r"\bOriginal SeqGAN\b", "SeqGAN cơ sở", "Không tuyên bố mức độ trung thành với bài báo khi chưa đối chiếu từng thành phần."),
    Rule("baseline-seqgan", r"\bBaseline SeqGAN\b", "SeqGAN cơ sở", "Dùng một tên học thuật duy nhất."),
    Rule("master-model", r"\bMaster model\b", "mô hình SeqGAN cơ sở", "Tránh tên quảng bá/phân cấp."),
    Rule("successful-bypass", r"\bsuccessful bypass\b", "request not blocked by the WAF", "Không bị chặn không chứng minh khai thác."),
    Rule("successful-attack", r"\bsuccessful attack\b", "request not blocked by the WAF", "Không suy luận thành công tấn công từ HTTP/WAF."),
    Rule("waf-bypass-success", r"\bWAF bypass success\b", "WAF not-blocked result", "Mô tả đúng lớp phòng vệ."),
    Rule("attack-success", r"\battack success\b", "WAF not-blocked result", "Không suy luận khả năng DBMS."),
    Rule("generated-sql-payload", r"\bgenerated SQL payloads?\b", "retrieved payload (for SMOTE/Vanilla GAN/CTGAN)", "Nhánh véc-tơ có bước truy hồi."),
    Rule("garbage-string", r"\bgarbage strings?\b", "structure-lost sequence", "Dùng thuật ngữ đo lường trung tính."),
    Rule("independent-validation", r"\bindependent validation set\b", "validation subset drawn from training data", "Không hàm ý một tệp xác thực độc lập."),
    Rule("optimal-config", r"\boptimal configuration\b", "selected configuration under the stated criteria", "Không vượt quá bằng chứng khảo sát."),
    Rule("faithful-implementation", r"\bfully faithful implementation\b|\bexact implementation of the paper\b", "implementation used in this thesis", "Chưa có đối chiếu từng thành phần với bài báo."),
)

DEFAULT_ROOTS = ("README.md", "COLAB_GUIDE.md", "GAN_SQLi_Colab.ipynb", "common", "configs", "models", "scripts", "docker", "docs")
SKIP_PARTS = {".git", "legacy", "final_result", "final_result_info", "export", "raw", "archive", "__pycache__"}
SKIP_FILES = {"original_gan_for_sqli_readme.md", "terminology_vi.md", "thesis_repo_alignment_audit_vi.md"}
TEXT_SUFFIXES = {".md", ".py", ".yaml", ".yml", ".json", ".csv", ".txt", ".ipynb", ".toml"}


def iter_files(repo: Path, roots: list[str]) -> list[Path]:
    files: list[Path] = []
    for item in roots:
        path = repo / item
        candidates = [path] if path.is_file() else path.rglob("*") if path.exists() else []
        for candidate in candidates:
            if not candidate.is_file() or candidate.suffix.casefold() not in TEXT_SUFFIXES:
                continue
            relative = candidate.relative_to(repo)
            if candidate.name.casefold() in SKIP_FILES or any(part in SKIP_PARTS for part in relative.parts):
                continue
            files.append(candidate)
    return sorted(set(files))


def audit(repo: Path, roots: list[str]) -> list[Finding]:
    findings: list[Finding] = []
    compiled = [(rule, re.compile(rule.pattern, re.IGNORECASE)) for rule in RULES]
    for path in iter_files(repo, roots):
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (UnicodeDecodeError, OSError):
            continue
        for number, line in enumerate(lines, 1):
            if "terminology-audit: allow" in line:
                continue
            for rule, pattern in compiled:
                if pattern.search(line):
                    findings.append(Finding(rule.code, path.relative_to(repo).as_posix(), number, line.strip()[:300], rule.replacement, rule.reason))
    return findings


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--root", action="append", dest="roots", help="Canonical root to scan; repeatable")
    parser.add_argument("--format", choices=("text", "json"), default="text")
    args = parser.parse_args()
    repo = args.repo.resolve()
    findings = audit(repo, args.roots or list(DEFAULT_ROOTS))
    if args.format == "json":
        print(json.dumps({"finding_count": len(findings), "findings": [asdict(item) for item in findings]}, ensure_ascii=False, indent=2))
    else:
        for item in findings:
            print(f"{item.path}:{item.line}: [{item.rule}] {item.context}\n  -> {item.replacement}\n  {item.reason}")
        print(f"Terminology findings: {len(findings)}")
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
