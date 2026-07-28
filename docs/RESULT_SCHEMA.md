# Schema kết quả và mẫu số

Schema chuẩn hóa này mô tả artifact hiện có; không thay đổi số liệu lịch sử.
Trong artifact lịch sử `quality-metrics-v3`, payload `None` và chuỗi rỗng bị
loại trước khi tính. Schema `quality-metrics-v4` thêm alias rõ nghĩa
`exact_holdout_overlap`, `requested_samples`, `actual_samples` và
`empty_payload_count` mà không đổi công thức các chỉ số cũ.
Vì vậy `n_generated` là số payload không rỗng thực tế dùng
làm mẫu số, không nhất thiết bằng số được yêu cầu.

| Trường | Tên hiển thị tiếng Việt | Công thức/tử số | Mẫu số | Rỗng | Chuẩn hóa |
|---|---|---|---|---|---|
| `sql_parse_rate` | Tỷ lệ chuỗi phân tích cú pháp được | số chuỗi có token không lỗi hoàn toàn | `n_generated` | loại | không |
| `sql_structure_rate` | Tỷ lệ chuỗi bảo toàn cấu trúc SQL | số chuỗi đạt luật cấu trúc/motif | `n_generated` | loại | có chuẩn hóa văn bản nội bộ khi dò luật |
| `garbage_rate` | Tỷ lệ chuỗi mất cấu trúc | `1-sql_structure_rate` | `n_generated` | loại; bằng 1 nếu mẫu số 0 | như trên |
| `family_motif_hit_rate` | Tỷ lệ chứa dấu hiệu họ | số payload có ít nhất một motif của họ đích | `n_generated` | loại | có chuẩn hóa dò motif |
| `family_motif_coverage` | Mức bao phủ nhóm dấu hiệu của họ | số motif khác nhau quan sát được | số motif định nghĩa cho họ đích | loại | có |
| `unique_rate` | Tỷ lệ payload duy nhất theo trùng khớp tuyệt đối | số chuỗi phân biệt tuyệt đối | `n_generated` | loại | không |
| `normalized_unique_rate` | Tỷ lệ payload duy nhất sau chuẩn hóa | số chuỗi phân biệt sau chuẩn hóa | `n_generated` | loại | NFKC, HTML, percent một lần, casefold, khoảng trắng, dấu nháy |
| `exact_input_overlap` | Tỷ lệ trùng tuyệt đối với tập huấn luyện | số payload thuộc tập input | `n_generated` | loại | không |
| `normalized_input_overlap` | Tỷ lệ trùng chuẩn hóa với tập huấn luyện | số payload chuẩn hóa thuộc input chuẩn hóa | `n_generated` | loại | có |
| `holdout_overlap` | Tỷ lệ trùng tuyệt đối với tập giữ lại | số payload thuộc holdout | `n_generated` | loại | không; alias nên hiển thị `exact_holdout_overlap` |
| `normalized_holdout_overlap` | Tỷ lệ trùng chuẩn hóa với tập giữ lại | số payload chuẩn hóa thuộc holdout chuẩn hóa | `n_generated` | loại | có |
| `dominant_payload_share` | Tỷ trọng payload chiếm ưu thế theo trùng tuyệt đối | tần số payload phổ biến nhất | `n_generated` | loại | không |
| `normalized_dominant_payload_share` | Tỷ trọng payload chiếm ưu thế sau chuẩn hóa | tần số dạng chuẩn hóa phổ biến nhất | `n_generated` | loại | có |
| `blocked_rate` | Tỷ lệ yêu cầu bị WAF chặn | yêu cầu có trạng thái thuộc `blocked_statuses` | yêu cầu đủ điều kiện được gửi và phân loại | tách riêng | không |
| `waf_not_blocked_rate` | Tỷ lệ yêu cầu không bị WAF chặn | yêu cầu đã gửi, không lỗi và không bị chặn | cùng mẫu số với `blocked_rate` | tách riêng | không |
| `bypass_rate` | Alias lịch sử của tỷ lệ không bị WAF chặn | như trên | như trên | như trên | không |
| `requested_samples` / `n_samples_requested` | Số payload yêu cầu | số mục tiêu của cấu hình | không phải tỷ lệ | có thể lớn hơn actual | không |
| `actual_samples` / `n_samples_generated` / `n_generated` | Số payload thực tế | số hàng hoặc số payload không rỗng tùy artifact | không phải tỷ lệ | phải ghi rõ | không |

## Bất biến schema

- `0 <= rate <= 1`.
- Với cùng một mẫu số WAF hợp lệ: `blocked_rate + waf_not_blocked_rate = 1`.
- `garbage_rate = 1 - sql_structure_rate` theo triển khai hiện tại.
- `unique_rate <= 1`, `normalized_unique_rate <= 1`; không giả định quan hệ thứ tự
  nếu hàm chuẩn hóa thay đổi, nhưng với phiên bản hiện tại thường
  `normalized_unique_rate <= unique_rate`.
- `requested_samples` không được dùng làm mẫu số chất lượng nếu có payload rỗng.
- WAF phải báo riêng `not_sent_too_long`, `network_error`, `format_error` và
  `empty_payload`; các trạng thái này không được tự động tính là không bị chặn.

## Bảng luận văn

Đối chiếu bản Word có SHA-256
`a603c9157bcbec9b7c56eb60cb1e47de9fbcceeb5e562b9aab6e7dd72c4e8eb9`
cho thấy nhãn ngắn “Mẫu duy nhất” không dùng cùng một field ở mọi giai đoạn:

| Bảng | Field thực tế | Tên hiển thị đầy đủ cần dùng khi xuất lại |
|---|---|---|
| Bảng 3.6 | `unique_rate` | Tỷ lệ payload duy nhất theo trùng khớp tuyệt đối |
| Bảng 3.15 | `normalized_unique_rate` | Tỷ lệ payload duy nhất sau chuẩn hóa |
| Bảng 3.16 | `normalized_unique_rate` | Tỷ lệ payload duy nhất sau chuẩn hóa |
| Bảng 3.17 | `normalized_unique_rate` | Tỷ lệ payload duy nhất sau chuẩn hóa |
| Bảng 3.21 | `normalized_unique_rate` | Tỷ lệ payload duy nhất sau chuẩn hóa |

Ở Bảng 3.17, cột “Mẫu chiếm ưu thế” dùng
`normalized_dominant_payload_share`. Sự khác nhau này được xác minh bằng cách
tái tổng hợp 489 `quality_metrics.json`; không được đổi nhãn ngắn thành
`unique_rate` theo suy đoán. Ánh xạ đầy đủ nằm trong
`final_result_info/_index/thesis_table_manifest.csv`.
