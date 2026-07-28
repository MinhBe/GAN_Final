# Ma trận truy vết luận văn–mã nguồn–kết quả

Mốc kiểm toán: luận văn ngày 27/07/2026, SHA-256
`a603c9157bcbec9b7c56eb60cb1e47de9fbcceeb5e562b9aab6e7dd72c4e8eb9`,
slide ngày 25/07/2026, SHA-256
`fc7488fd4f0dd29336352791e8ff07e8bd4628ce6476e94a8eeaf5d00440e74f`,
và repository commit `5e2c4d7302ce9f75dbe1849c8431ac3eaca270ff`.

| Phát biểu khoa học | Code/hàm | Cấu hình | Artifact/trường | Mức khớp | Ghi chú hành động |
|---|---|---|---|---|---|
| Năm phương pháp nghiên cứu | `scripts/finalize_results.py: METHODS`; model entry points | `experiment_config.yaml` | `run_index.csv: method` | Khớp nhưng tên khác | Dùng tên hiển thị chuẩn, giữ ID |
| Ba phương pháp đầu sinh trong không gian đặc trưng rồi truy hồi | `common/quality_metrics.py: RETRIEVAL_METHODS` và pipeline model | method blocks | `generation_kind=retrieval`, `retrieval_method` | Khớp hoàn toàn ở artifact đại diện | README đã chuẩn hóa |
| SeqGAN sinh trực tiếp chuỗi | SeqGAN runtimes | master/improved blocks | `generation_kind=direct` | Khớp hoàn toàn | Không dùng ngôn ngữ truy hồi |
| Sáu kịch bản A–F | bộ chọn dữ liệu theo scenario | `scenarios` A–F | `run_index.csv: scenario` | Khớp hoàn toàn | Giữ tên mô tả YAML làm chú giải |
| Các tỷ lệ mất cân bằng | runner/ranking scripts | phase2b ratios | `run_index.csv: ratio`, RF counts | Khớp nhưng cần nêu mẫu số | RESULT_SCHEMA là nguồn chuẩn |
| Tám biến thể V1–V8 | runtime `seqgan_improved` | `variants` V1–V8 | metadata tokenizer/max_len/reward/gpre | Khớp hoàn toàn | Không xem D schedule là trục khảo sát |
| 11 tổ hợp giữ lại | `rank_combinations.py` và index | kết quả Phase 3/refinement | `phase3_retained_combinations_thesis.csv`; 33 refinement rows | Khớp hoàn toàn theo danh sách luận văn | File placeholder V1 lịch sử không phải bằng chứng lựa chọn |
| Tổng 489 lượt chạy chính | – | các campaign | `_index/summary.json: total_runs=489` | Khớp hoàn toàn cho `final_result_info` | Phân biệt với catalog 1082 run dirs toàn kho |
| RF trước/sau bổ sung | pipeline RF | từng run | `rf_metrics.json` baseline/augmented/delta | Khớp hoàn toàn ở mẫu kiểm tra | Không suy luận từ một chỉ số đơn lẻ |
| WAF phải đọc cùng cấu trúc | `build_thesis_evidence.py` + WAF runner | full campaign | `run_quality_waf_correlation.csv` | Khớp hoàn toàn | 489 run; 825.899 yêu cầu hợp lệ |
| Không bị WAF chặn không phải khai thác DBMS | WAF backend/runner | Docker CRS | HTTP status/blocked/error | Khớp nhưng tên lịch sử gây hiểu sai | Dùng trường chuẩn mới |
| Vai trò xác thực lấy từ tập huấn luyện | `common/ingestion.py:split_records` | seed 88; holdout 20% | `data/prepared/dataset_manifest.json`; split CSV + SHA-256 | Khớp nhưng tên vật lý là holdout | Không có tệp validation độc lập; holdout/test được giữ độc lập |
| Hệ số tương quan Hình 3.12 | `build_thesis_evidence.py:build_correlation` | full WAF campaign | `correlation_summary_canonical.json` | Khớp hoàn toàn | Pearson theo 489 `run_key`; r=0,879048 cho mất cấu trúc |
| “Mẫu duy nhất” trong Bảng 3.15–3.17/3.21 | quality metrics aggregation | full campaigns | `normalized_unique_rate` | Khớp số nhưng nhãn rút gọn | Phải hiển thị “sau chuẩn hóa” trong bảng xuất mới |

## Chuỗi truy vết bắt buộc

`tên luận văn → method_id → config_path+config_sha256 → run_id/run_key →
training_metadata.json → generated_payloads.csv → quality_metrics.json →
rf_metrics.json → WAF source_row+source manifest → WAF result → thesis_table_id`.

Lớp nối canonical đã được bổ sung mà không sửa artifact gốc:

- `thesis_table_manifest.csv`: 21 bảng Chương 3;
- `thesis_run_traceability.csv`: 489 run, run/config/input/artifact hash và dải
  `source_row` WAF;
- `run_quality_waf_correlation.csv`: join quality–WAF theo `run_key`;
- `correlation_summary_canonical.json`: công thức, mẫu số và hệ số Pearson.

Lưu ý còn hiệu lực: một số metadata refinement ghi phase lịch sử; khi mâu thuẫn,
`campaign` từ `run_index.csv` là nguồn phân loại ưu tiên.
