# Quy tắc provenance thực nghiệm

## Định danh canonical

Khóa duy nhất là `campaign|method|family|scenario|ratio|variant`. `run_id` là ID
thực thi; `run_key` là khóa catalog. `phase` mô tả bước khoa học và không thay
thế `campaign`. Mọi bảng mới phải chứa `audit_commit`, `config_sha256`,
`dataset_sha256` và hash artifact nguồn.

## Manifest tối thiểu

```json
{
  "schema_version": "experiment-provenance-v1",
  "audit_commit": "5e2c4d7302ce9f75dbe1849c8431ac3eaca270ff",
  "thesis_table_ids": ["<chapter/table title>"],
  "campaign": "final_full/baselines",
  "phase": "final",
  "run_id": "final__ctgan__boolean__D__R100",
  "run_key": "final_full/baselines|ctgan|boolean|D|R100|BASE",
  "method_id": "ctgan",
  "method_display_vi": "CTGAN",
  "config_path": "configs/experiment_config.yaml",
  "config_sha256": "<sha256>",
  "inputs": [{"path": "<path>", "sha256": "<sha256>", "role": "training"}],
  "artifacts": [{"path": "generated_payloads.csv", "sha256": "<sha256>", "role": "generated_or_retrieved_output"}],
  "waf": {"source_manifest_sha256": "<sha256>", "source_row_start": 0, "source_row_end_exclusive": 2000}
}
```

## Manifest đã vật hóa

- `_index/thesis_source_snapshot.json`: khóa phiên bản DOCX/PPTX bằng SHA-256.
- `_index/thesis_table_manifest.csv`: ánh xạ 21 bảng Chương 3 sang campaign,
  artifact và field chuẩn.
- `_index/thesis_run_traceability.csv`: 489 hàng; mỗi hàng nối `run_key` với
  bảng luận văn, `run_id`, config/input hash, payload/quality/RF hash và dải row
  trong input WAF.
- `_provenance/decision_artifacts/phase3_retained_combinations_thesis.csv`:
  danh sách canonical 11 tổ hợp; file `phase3_selected_variant_PLACEHOLDER.json`
  chỉ là artifact vận hành lịch sử.
- `waf_evaluation/.../run_quality_waf_correlation.csv`: 489 hàng chất lượng–WAF.
- `waf_evaluation/.../correlation_summary_canonical.json`: hệ số Pearson và
  mẫu số chiến dịch đầy đủ.

Các manifest mới là sidecar; không thay đổi hash của `run_index.csv`, payload,
quality/RF JSON hay probe CSV gốc.

## Nguồn ưu tiên khi mâu thuẫn

1. Artifact gốc và hash.
2. `final_result_info/_index/run_index.csv` và `summary.json`.
3. `run_manifest.json`.
4. `training_metadata.json`.
5. README/báo cáo dẫn xuất.

Không sửa artifact để giải quyết mâu thuẫn. Ghi `historical_value`,
`canonical_value`, `mapping_reason` trong manifest bổ sung.

## Phân vùng bằng chứng

- Canonical: cấu hình/mã nguồn hiện hành và campaign được luận văn sử dụng.
- Diagnostic: smoke, mini, medium, preflight, recovery; chỉ dùng giải thích vận hành.
- Historical/legacy: giữ nguyên hash, không dùng làm số liệu chính nếu không có ánh xạ.
- WAF: mỗi campaign phải có `campaign_id`, phạm vi input, số row/probe, tiêu chí
  loại trừ, image digest và source-manifest hash. Không trộn pilot 13.000 probe,
  final-only 384.000 probe và campaign full 827.400 probe.
