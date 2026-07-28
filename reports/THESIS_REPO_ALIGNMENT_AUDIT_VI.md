# Báo cáo kiểm toán đồng bộ luận văn–repository GAN_Final

Ngày kiểm toán: 28/07/2026. Nguồn học thuật: `27_07 Luận văn Thạc sĩ Phạm Đỗ
Anh Minh.docx`; nguồn trình bày: `25_07 Báo cáo Đề án thạc sĩ.pptx`. Snapshot
mã nguồn được kiểm toán: `5e2c4d7302ce9f75dbe1849c8431ac3eaca270ff`.

> Trạng thái xuất bản khẩn cấp: tại thời điểm 28/07/2026, `origin/main` trỏ tới
> `c708643a` (“new life”) và chỉ còn README 26 byte. Báo cáo này được triển khai
> trên nhánh `thesis-repo-alignment-audit` từ snapshot khoa học `5e2c4d7` đã
> được GitHub giữ theo SHA. Không nên coi `main` hiện tại là repository luận văn.

## 1. Tóm tắt điều hành

Nền tảng thực nghiệm có bằng chứng đủ mạnh để chứng minh cùng một quy trình
nghiên cứu: cấu hình A–F/V1–V8, metadata huấn luyện, payload, quality/RF metrics
và run index đều tồn tại; `_index/summary.json` ghi 489 lượt chạy chính, không
thiếu artifact bắt buộc và không trùng khóa campaign-aware. Tuy nhiên trạng thái
GitHub hiện hành, tên “SeqGAN Master”, schema WAF `bypass_rate`, và nhiều phạm vi
WAF khác nhau có thể khiến Hội đồng nghi ngờ hoặc diễn giải quá mức.

Kết luận kiểm toán sau khi đối chiếu trực tiếp 42 bảng Word và render 44 slide:
**chuỗi bằng chứng khoa học đã khớp ở mức run và artifact; khâu xuất bản GitHub
vẫn chưa đạt nghiệm thu**. Bảng 3.19–3.21 dùng duy nhất chiến dịch WAF toàn bộ
413.700 payload/827.400 probe. Manifest 21 bảng, 489 run và artifact tương quan
đã được vật hóa mà không thay đổi artifact gốc và không cần huấn luyện lại.

## 2. Rủi ro lớn nhất

| Mức | Rủi ro | Bằng chứng | Hệ quả |
|---|---|---|---|
| Nghiêm trọng | `main` chỉ còn README “New life” | commit `c708643a` | Hội đồng không thể kiểm tra code/artifact |
| Cao | Ba phạm vi WAF bị đặt gần nhau | 13.000, 384.000 và 827.400 probe | Đã khóa Bảng 3.19–3.21 vào campaign full; README đã phân vùng |
| Cao | Tên hiển thị “SeqGAN Master/Improved” | README, catalog, final_result_info | Luận văn–GitHub trông như hai hệ thống |
| Cao | `bypass_rate`/`bypassed` dễ bị hiểu là khai thác | JSON/CSV và summarizer | Phóng đại kết quả WAF |
| Cao | Chưa có `thesis_table_id` nối bảng với run/artifact | run index hiện tại | Chuỗi provenance đứt ở bước cuối |
| Trung bình | `holdout_overlap` không nói rõ exact | quality schema | Nhầm exact với normalized |
| Trung bình | `garbage_rate` là tên kỹ thuật mạnh | quality schema/docs | Nên hiển thị “tỷ lệ chuỗi mất cấu trúc” |
| Trung bình | metadata refinement ghi `phase=phase3` | run V8 đại diện trong final refinement | Nhầm phase với campaign |
| Trung bình | Khác hồ sơ filter bộ phân biệt | master `original`, improved `balanced` | Không được quy là cải tiến đã chứng minh |
| Trung bình | Nhãn “Mẫu duy nhất” rút gọn | Bảng 3.15–3.17 và 3.21 dùng `normalized_unique_rate` | Bảng xuất mới phải ghi rõ “sau chuẩn hóa” |
| Thấp | Slide 44 dùng “Garbage rate”/“not blocked” | PPTX SHA-256 `fc7488...e74f` | Số đúng nhưng nhãn chưa theo chuẩn tiếng Việt |

## 3. Từ điển thuật ngữ luận văn–code

Từ điển đầy đủ nằm tại `docs/TERMINOLOGY_VI.md`. Các ánh xạ quyết định:

| Tên chuẩn | ID code/alias | Quy tắc |
|---|---|---|
| SeqGAN cơ sở | `seqgan_master`, alias “SeqGAN Master” | Alias chỉ xuất hiện trong code/path hoặc chú giải lịch sử |
| SeqGAN cải tiến | `seqgan_improved`, alias “SeqGAN Improved” | Không dùng advanced/best/optimal |
| Payload được truy hồi | `generation_kind=retrieval` | SMOTE, Vanilla GAN, CTGAN |
| Chuỗi được sinh trực tiếp | `generation_kind=direct` | Hai SeqGAN |
| Tỷ lệ chuỗi mất cấu trúc | `garbage_rate` | Field lịch sử giữ nguyên, nhãn hiển thị đổi |
| Tỷ lệ yêu cầu không bị WAF chặn | `waf_not_blocked_rate`; alias `bypass_rate` | Không đồng nghĩa khai thác |
| Vai trò xác thực trích từ tập huấn luyện | validation subset/split | Không gọi tập xác thực độc lập |

## 4. Thuật ngữ dùng sai theo tệp và dòng

Số dòng dưới đây thuộc snapshot `5e2c4d7`; artifact lịch sử được đánh dấu, không
sửa cưỡng bức.

| Tệp:dòng | Ngữ cảnh | Vấn đề | Thay thế | Xử lý |
|---|---|---|---|---|
| `README.md:36` | SeqGAN Master/Improved | tên hiển thị lệch luận văn | SeqGAN cơ sở/cải tiến | Đã sửa canonical |
| `README.md:123,128` | SeqGAN Master; bypass candidate | tên và trạng thái WAF | ID trong ngoặc; ứng viên không bị chặn | Đã sửa canonical |
| `docs/RESULTS_CATALOG.md:32` | SeqGAN Master | tên catalog | SeqGAN cơ sở (`seqgan_master`) | Đã sửa |
| `docs/ORIGINAL_GAN_FOR_SQLi_README.md:120,174` | SeqGAN Master, garbage_rate | tài liệu bảo tồn | thêm lớp ánh xạ, không sửa nội dung | Giữ lịch sử |
| `final_result_info/README.md:77...667` | SeqGAN Master, garbage, bypass gate | báo cáo thông tin đã đóng gói | đọc qua TERMINOLOGY; không đổi hash | Giữ lịch sử |
| `scripts/summarize_waf_results.py:31...38` | bypassed/bypass_rate | schema dễ hiểu quá mức | thêm `not_blocked`, `waf_not_blocked_rate`; giữ alias | Đã sửa future output |
| `scripts/summarize_waf_results.py:264` | Bypassed with HTTP 200 | diễn giải mạnh | Requests not blocked by the WAF | Đã sửa |
| `waf_evaluation/**/WAF_*REPORT.md:16...27` | Passed/bypass candidates | artifact chiến dịch | ánh xạ trong schema, không rewrite | Giữ lịch sử |
| `waf_evaluation/**/waf_analysis.json` | `bypass_rate` | field lịch sử | alias sang `waf_not_blocked_rate` | Giữ hash |

`scripts/audit_terminology.py` cung cấp tệp, dòng, ngữ cảnh, lý do và câu thay
thế; mặc định loại `legacy`, `final_result`, `final_result_info`, archive/raw và
tài liệu nguyên gốc.

## 5. Ma trận luận văn–mã nguồn–kết quả

| Phát biểu | Code/lớp | Config | Artifact/trường | Đánh giá | Nghiêm trọng |
|---|---|---|---|---|---|
| Năm phương pháp | finalizer/model entry points | methods theo phase | `run_index.method` | Khớp nhưng tên khác | Trung bình |
| Nhánh véc-tơ có truy hồi | `RETRIEVAL_METHODS`; pipeline retrieval | method config | metadata `retrieval_method`; quality `generation_kind` | Khớp hoàn toàn ở mẫu kiểm tra | Thấp |
| SeqGAN sinh trực tiếp | SeqGAN runtimes | master/improved | `generation_kind=direct` | Khớp hoàn toàn | Thấp |
| A–F | selector/runners | `scenarios` | `run_index.scenario` | Khớp hoàn toàn | Thấp |
| Tỷ lệ full, R10...R500 | runners/ranking | phase ratios | run index + RF counts | Khớp nhưng cần mẫu số | Trung bình |
| V1–V8 | improved runtime | variants | training metadata | Khớp hoàn toàn | Thấp |
| D schedule giữ nguyên | runtime config | steps=5, epochs=3 cả hai | metadata đại diện | Khớp | Thấp |
| 11 tổ hợp giữ lại | ranking/refinement | Phase 3 | sidecar canonical + 33 refinement runs | Khớp hoàn toàn | Thấp |
| Tổng 489 run chính | indexer | campaign set | `_index/summary.json` | Khớp hoàn toàn theo catalog này | Thấp |
| RF | RF evaluator | mỗi run | `rf_metrics.json` | Khớp | Thấp |
| WAF | runners/summarizer | full CRS campaign | source manifest/results/summary | Khớp hoàn toàn cho Bảng 3.19–3.21 | Thấp |
| Tương quan mất cấu trúc–không bị chặn | `build_thesis_evidence.py` | full campaign | 489-row correlation CSV + JSON | Khớp hoàn toàn | Thấp |

## 6. Kiểm toán định nghĩa chỉ số

Nguồn tính: `common/quality_metrics.py`. Hàm đầu vào loại `None` và chuỗi rỗng;
do đó mọi rate chất lượng dùng payload không rỗng. Bảng công thức đầy đủ nằm ở
`docs/RESULT_SCHEMA.md`.

| Nhóm | Kết luận code | Rủi ro tên/mẫu số |
|---|---|---|
| `sql_parse_rate` | parser có ít nhất token không lỗi hoàn toàn | Không đồng nghĩa SQL thực thi được |
| `sql_structure_rate` | luật cấu trúc hoặc motif sau chuẩn hóa | Không phải parser/DBMS validity |
| `garbage_rate` | chính xác `1-sql_structure_rate`; bằng 1 khi n=0 | Nhãn hiển thị phải là mất cấu trúc |
| motif hit | payload có ≥1 motif họ; mẫu số payload | Phân biệt coverage |
| motif coverage | motif khác nhau quan sát/tổng motif định nghĩa | Không phải tỷ lệ payload |
| unique/exact overlap | so chuỗi gốc | Phải ghi “trùng khớp tuyệt đối” |
| normalized metrics | normalization version `nfkc_html_percent1_casefold_ws_quotes_v1` | Không trộn với exact |
| `holdout_overlap` | exact holdout overlap | Tên thiếu chữ exact; cần alias |
| WAF rate | code cũ dùng tổng probe trừ blocked/error | Cần loại not-sent/malformed nhất quán theo campaign |
| requested/actual | metadata dùng nhiều tên | Không dùng requested làm mẫu số nếu có rỗng |

Đã xác minh ánh xạ field theo số bảng. Một phát hiện quan trọng là Bảng 3.6 dùng
`unique_rate`, trong khi Bảng 3.15–3.17 và 3.21 dùng
`normalized_unique_rate`; Bảng 3.17 dùng thêm
`normalized_dominant_payload_share`. Ánh xạ nằm trong
`thesis_table_manifest.csv`.

## 7. Kiểm toán ngôn ngữ WAF

Phân loại canonical phải gồm: `blocked`, `not_blocked`, `not_sent_too_long`,
`network_error`, `format_error`, `empty_payload`. HTTP 200 chỉ là
`not_blocked`; backend là echo service, không thực thi DBMS. Chất lượng WAF phải
được đọc cùng `sql_structure_rate`, `garbage_rate` và motif hit/coverage.

Ba phạm vi hiện thấy:

| Campaign/artifact | Payload/probe | Vai trò |
|---|---:|---|
| Phase 1 pilot reports | 6.500 payload, 13.000 probe | pilot/chẩn đoán |
| README final-only | 192.000 payload, 384.000 probe | chiến dịch final-only theo 96 CSV |
| `campaign/full/waf_summary.json` | 413.700 payload, 827.400 probe; 1.501 GET không gửi | nguồn Bảng 3.19–3.21 và Hình 3.12 |

Không được ghép block/not-block count giữa ba hàng. Đối chiếu Word xác nhận
campaign full có 825.899 yêu cầu hợp lệ, 585.661 bị chặn và 240.238 không bị
chặn. Bảng 3.20 chỉ lọc 129 run đánh giá đầy đủ; Bảng 3.21 lọc 33 run SeqGAN
cải tiến.

## 8. Kiểm toán provenance

Chuỗi từ method tới RF artifact hoạt động tốt ở run đại diện: run manifest có
`run_id`, config path/hash và input; metadata ghi phương pháp/truy hồi hoặc
tokenizer/reward; generated CSV, quality JSON và RF JSON cùng thư mục. Index
campaign-aware không thiếu artifact bắt buộc.

Hai điểm đứt đã được đóng bằng sidecar không phá provenance:

1. `thesis_run_traceability.csv` có 489 hàng, chứa `run_id`, bảng luận văn,
   config/input hash, payload/quality/RF hash và dải `source_row` WAF.
2. `thesis_table_manifest.csv` có đủ 21 bảng Chương 3.

Artifact tương quan tái tạo chính xác r = 0,8790475467; -0,8790475467;
-0,6262592060 và -0,9013132083 trên 489 run và 825.899 yêu cầu hợp lệ.

## 9. Điểm còn thiếu bằng chứng

- Chưa có bằng chứng rằng một tập validation vật lý độc lập từng được dùng; code
  và `dataset_manifest.json` chỉ chứng minh train/holdout/test. Vì vậy tài liệu
  phải tiếp tục gọi validation là vai trò lựa chọn trên dữ liệu huấn luyện.
- Chưa đối chiếu từng thành phần với bài báo SeqGAN gốc; không dùng “exact/fully faithful”.
- Chưa có thí nghiệm cô lập thay đổi hồ sơ filter bộ phân biệt.
- `main` hiện tại chưa xuất bản snapshot khoa học có thể đọc được.
- Slide 44 chưa dùng hoàn toàn thuật ngữ hiển thị tiếng Việt chuẩn.

## 10. Kế hoạch sửa theo ưu tiên

| Mức | Tệp | Hiện tại → thay thế | Đổi kết quả/hash | Chạy lại | Ưu tiên/rủi ro |
|---|---|---|---|---|---|
| 1 | README/catalog/summarizer | Master/bypass → tên chuẩn/not blocked | không đổi số; source hash đổi | không | P0/thấp |
| 1 | Git branch/release | main rỗng → release/tag snapshot khoa học | không đổi artifact | không | P0/cao nếu làm sai lịch sử |
| 2 | schema xuất mới | alias mơ hồ → trường chuẩn + alias | derived file hash đổi | chỉ tổng hợp lại | P0/thấp |
| 2 | WAF manifest | thiếu run/artifact hashes → provenance v1 | manifest mới | không | P0/trung bình |
| 3 | README/Colab/notebook/docs | từ ngữ phân tán → liên kết 5 tài liệu chuẩn | source/doc hash đổi | không | P1/thấp |
| 3 | báo cáo/biểu đồ tự động | nhãn garbage/bypass → nhãn Việt chuẩn | hình/bảng dẫn xuất đổi | không huấn luyện | P1/thấp |
| 4 | CI | không có gate → terminology/schema/provenance tests | không | không | P1/thấp |

## 11. Thay đổi không cần chạy lại thực nghiệm

- Đổi nhãn hiển thị và bổ sung alias schema.
- Thêm tài liệu thuật ngữ, schema, phương pháp và provenance.
- Thêm `thesis_table_id`, hashes và campaign ID vào manifest mới.
- Sinh lại WAF summary/bảng/biểu đồ từ probe CSV gốc.
- Sinh lại bảng quality/RF từ JSON gốc với nhãn chuẩn.
- Thêm kiểm thử và GitHub Actions.
- Tạo tag/release chỉ đọc tại snapshot khoa học.

## 12. Thay đổi bắt buộc chạy lại nếu thực hiện

- Thay tokenizer, dữ liệu huấn luyện/holdout, seed, ratio/scenario selector.
- Thay số vòng pretrain/adversarial, max length, reward hoặc lịch D.
- Thay logic truy hồi nearest payload.
- Thay định nghĩa thuật toán của metric rồi muốn so sánh số mới với luận văn.
- Thay CRS/image/paranoia/threshold, HTTP encoding hoặc chính sách blocked status
  rồi muốn thay bảng WAF.
- Không cần chạy lại chỉ để thêm alias; nếu loại payload rỗng theo quy tắc khác,
  phải tái tổng hợp WAF và ghi schema version mới, không nhất thiết huấn luyện lại.

## 13. Tiêu chí nghiệm thu cuối

- [ ] GitHub default branch hoặc release được ghim tới snapshot khoa học đầy đủ.
- [ ] Mỗi phương pháp có một tên học thuật và một mapping ID duy nhất.
- [ ] Scanner trả 0 vi phạm trong canonical; legacy/raw bị loại có chủ đích.
- [ ] README nói rõ retrieval/direct và validation role.
- [ ] Không có tuyên bố HTTP 200 là khai thác/thành công tấn công.
- [ ] Mọi rate có tử số, mẫu số, empty policy và normalization version.
- [x] Mỗi bảng có `thesis_table_id`, campaign, run keys và artifact hashes.
- [x] WAF campaign scope duy nhất được ghi cho từng bảng.
- [x] Join correlation có danh sách run và script tái tạo.
- [ ] `python -m unittest discover -s tests -v` thành công.
- [ ] `python scripts/audit_terminology.py` thành công.

## 14. Tài liệu và kiểm soát đã triển khai

- `docs/TERMINOLOGY_VI.md`: từ điển, alias, tên cấm và quy tắc hiển thị.
- `docs/RESULT_SCHEMA.md`: công thức, tử/mẫu, rỗng và chuẩn hóa.
- `docs/THESIS_CODE_TRACEABILITY.md`: ma trận phát biểu–code–artifact và điểm đứt.
- `docs/METHOD_IMPLEMENTATION_MAP.md`: hai nhánh sinh và bốn thành phần khảo sát.
- `docs/EXPERIMENT_PROVENANCE.md`: khóa run, manifest v1, nguồn ưu tiên và phân vùng bằng chứng.
- `scripts/audit_terminology.py`: quét canonical, trả tệp/dòng/ngữ cảnh/thay thế; hỗ trợ JSON/CI.
- `scripts/audit_provenance.py`: kiểm tra khóa campaign-aware, cột bắt buộc và tổng hợp thiếu/trùng.
- `scripts/build_thesis_evidence.py`: tạo manifest 489 run và tái tạo tương quan quality–WAF.
- `tests/test_audit_contracts.py`: gate thuật ngữ, alias WAF, index và mẫu số payload rỗng.

Các bước còn lại trước nghiệm thu công khai: commit/push nhánh audit hoặc tạo
release từ snapshot khoa học, quyết định có phát hành một bản slide cập nhật
nhãn hay chỉ ghi errata, và bảo đảm default branch trỏ tới nội dung có thể đọc.
Không sửa các artifact lịch sử để đạt các bước này.
