# Từ điển thuật ngữ luận văn–mã nguồn

Luận văn `27_07 Luận văn Thạc sĩ Phạm Đỗ Anh Minh.docx` là nguồn ngôn ngữ học
thuật chuẩn. Định danh kỹ thuật và trường lịch sử không bị đổi tên; chúng được
ánh xạ tại đây. Quy tắc áp dụng cho README, notebook, hướng dẫn, mã nguồn sinh
báo cáo và mọi artifact được tạo mới. Artifact lịch sử chỉ đọc.

| Khái niệm | Tên chuẩn trong luận văn | Định danh code | Alias lịch sử được giữ | Không dùng làm tên hiển thị | Ghi chú |
|---|---|---|---|---|---|
| Phương pháp 1 | SMOTE | `smote` | – | generated SQL payload | Sinh véc-tơ, sau đó truy hồi payload |
| Phương pháp 2 | Vanilla GAN | `gan`, `vanilla_gan` | `gan` | generated SQL payload | Sinh véc-tơ, sau đó truy hồi payload |
| Phương pháp 3 | CTGAN | `ctgan` | – | generated SQL payload | Sinh hàng đặc trưng, sau đó truy hồi payload |
| Phương pháp 4 | SeqGAN cơ sở | `seqgan_master` | SeqGAN Master, baseline/original SeqGAN | Master model | Sinh trực tiếp chuỗi rời rạc |
| Phương pháp 5 | SeqGAN cải tiến | `seqgan_improved` | SeqGAN Improved | advanced, better, enhanced, best model | Chỉ bốn thành phần đã khảo sát được gọi là cải tiến |
| Nhánh véc-tơ | Nhánh không gian đặc trưng | `generation_kind=retrieval` | feature-space generation | direct payload generation | Đầu ra cuối: payload được truy hồi |
| Nhánh chuỗi | Nhánh sinh chuỗi trực tiếp | `generation_kind=direct` | text generation | retrieved payload | Đầu ra: chuỗi được sinh trực tiếp |
| Dữ liệu xác thực | Vai trò xác thực được trích từ tập huấn luyện | `validation_split` hoặc metadata tương ứng | validation subset | independent validation set | Không hàm ý tệp vật lý độc lập |
| Tập đánh giá | Tập kiểm tra độc lập | `holdout`, `attack_holdout`, `test` theo schema | holdout set | validation set | Không dùng lẫn với xác thực |
| Họ tấn công | Boolean-based, Union-based, Time-based, Error-based | `boolean`, `union`, `time`, `error` | – | Other như họ chính | `other` chỉ bảo toàn dữ liệu |
| Kịch bản | Kịch bản lựa chọn dữ liệu A–F | `scenario=A..F` | tên mô tả trong YAML | phase/variant | Là quy tắc chọn dữ liệu |
| Tỷ lệ | Tỷ lệ mất cân bằng | `ratio=R10...R500`, `full` | `1:10...1:500` | scenario/configuration | Phải nêu mẫu số dữ liệu bình thường/tấn công |
| Biến thể | Biến thể SeqGAN V1–V8 | `variant=V1..V8` | – | configuration/campaign | Tổ hợp bốn trục khảo sát |
| Cấu hình | Cấu hình đầy đủ | `execution_profile=full` | full | complete/final model | Ngân sách huấn luyện, không phải kết luận tối ưu |
| Cấu hình | Cấu hình thực nghiệm trung bình | `execution_profile=medium` | medium | final | Bằng chứng chẩn đoán/trung gian |
| Cấu hình | Cấu hình khảo sát sơ bộ | `execution_profile=mini` | mini | final | Không thay thế số liệu cuối |
| Cấu hình | Cấu hình kiểm tra nhanh | `execution_profile=smoke` | smoke | experiment result | Chỉ kiểm tra đường chạy |
| Giai đoạn | Giai đoạn thực nghiệm | `phase` | phase1, phase2a, phase2b, phase3, final | campaign/run | Bước logic trong thiết kế |
| Chiến dịch | Chiến dịch thực thi | `campaign` | đường dẫn chiến dịch | phase | Nhóm lượt chạy có cùng mục đích/phạm vi |
| Lượt chạy | Lượt chạy | `run_id`, `run_key` | job | configuration | Một thực thi cụ thể |
| Tỷ lệ cấu trúc | Tỷ lệ chuỗi bảo toàn cấu trúc SQL | `sql_structure_rate` | shaped_rate | valid SQL rate | Dựa trên luật/motif, không chứng minh thực thi DBMS |
| Tỷ lệ mất cấu trúc | Tỷ lệ chuỗi mất cấu trúc | `garbage_rate` | garbage rate | chuỗi rác | Alias lịch sử bằng `1-sql_structure_rate` |
| Dấu hiệu họ | Tỷ lệ chứa dấu hiệu họ | `family_motif_hit_rate` | motif hit | motif coverage | Mẫu số là payload |
| Bao phủ dấu hiệu | Mức bao phủ nhóm dấu hiệu của họ | `family_motif_coverage` | motif coverage | motif hit rate | Mẫu số là tập motif định nghĩa trước |
| Duy nhất tuyệt đối | Tỷ lệ payload duy nhất theo trùng khớp tuyệt đối | `unique_rate` | – | normalized unique rate | Trước chuẩn hóa |
| Duy nhất chuẩn hóa | Tỷ lệ payload duy nhất sau chuẩn hóa | `normalized_unique_rate` | – | unique rate | Sau chuẩn hóa |
| Trùng huấn luyện | Tỷ lệ trùng với tập huấn luyện | `exact_input_overlap`, `normalized_input_overlap` | input overlap | holdout overlap | Ghi rõ tuyệt đối/chuẩn hóa |
| Trùng tập giữ lại | Tỷ lệ trùng với tập giữ lại | `holdout_overlap`, `normalized_holdout_overlap` | exact holdout overlap | input overlap | `holdout_overlap` là alias lịch sử của exact |
| WAF chặn | Tỷ lệ yêu cầu bị WAF chặn | `blocked_rate` | – | attack failure | Mẫu số chỉ gồm yêu cầu đủ điều kiện được gửi |
| WAF không chặn | Tỷ lệ yêu cầu không bị WAF chặn | `waf_not_blocked_rate` | `bypass_rate` | attack success, successful bypass | Không chứng minh khai thác DBMS |
| Trạng thái WAF | Ứng viên không bị WAF chặn | `not_blocked` | `bypassed` | successful attack | Trạng thái lớp phòng vệ בלבד |

## Quy tắc sử dụng

1. Tên hiển thị dùng cột “Tên chuẩn”; code và đường dẫn có thể giữ định danh kỹ thuật.
2. Khi đọc artifact cũ, trình bày cả alias và tên chuẩn ở lần xuất hiện đầu tiên.
3. Không đổi tên tệp/field lịch sử nếu làm thay đổi hash; lớp xuất mới thêm trường chuẩn.
4. Mọi tỷ lệ phải ghi tử số, mẫu số, quy tắc payload rỗng và trạng thái chuẩn hóa.
5. “Cải tiến” chỉ gồm tokenizer nhận biết SQL, số vòng tiền huấn luyện bộ sinh,
   độ dài tối đa theo đơn vị chuỗi và phần thưởng cấu trúc SQL dựa trên luật.
6. Lịch cập nhật bộ phân biệt không được mô tả là đóng góp vì được giữ nguyên giữa
   hai cấu hình so sánh trong `configs/experiment_config.yaml`.
