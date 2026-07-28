# Ánh xạ phương pháp–triển khai

| Tên luận văn | ID kỹ thuật | Kiểu sinh | Điểm vào/config | Artifact chứng minh | Giới hạn diễn giải |
|---|---|---|---|---|---|
| SMOTE | `smote` | véc-tơ rồi truy hồi | `configs/experiment_config.yaml`; model/script theo ID | `training_metadata.json: retrieval_method`; `quality_metrics.json: generation_kind=retrieval` | Không gọi payload cuối là chuỗi mới sinh trực tiếp |
| Vanilla GAN | `gan`, `vanilla_gan` | véc-tơ rồi truy hồi | như trên | cùng hai trường trên | Không suy luận novelty chuỗi từ novelty véc-tơ |
| CTGAN | `ctgan` | hàng đặc trưng rồi truy hồi | như trên | `retrieval_method=nearest_attack_euclidean` trong run đại diện | Payload cuối có thể trùng tập huấn luyện theo thiết kế |
| SeqGAN cơ sở | `seqgan_master` | chuỗi trực tiếp | khối `seqgan_master`; `variant=MASTER` | tokenizer `raw_character`, `generation_kind=direct` | “Master” chỉ là ID lịch sử |
| SeqGAN cải tiến | `seqgan_improved` | chuỗi trực tiếp | khối `seqgan_improved`; V1–V8 | tokenizer/reward/max_len/g-pretrain trong metadata | Không gọi cấu hình tối ưu/toàn diện nếu chưa có bằng chứng |

## Bốn thành phần được khảo sát

| Thành phần | Giá trị kỹ thuật | Nguồn |
|---|---|---|
| Tokenizer nhận biết SQL | `tokenizer_mode=sql_aware` so với `raw_character` | V1–V8 trong `configs/experiment_config.yaml` |
| Số vòng tiền huấn luyện bộ sinh | `generator_pretrain_epochs=120/160` | cùng cấu hình |
| Độ dài tối đa theo đơn vị chuỗi | `max_len=20/160` | cùng cấu hình |
| Phần thưởng cấu trúc SQL dựa trên luật | `use_sql_reward=false/true` | cùng cấu hình và training metadata |

`discriminator_steps=5` và `discriminator_epochs=3` được giữ nguyên giữa cấu
hình cơ sở và cải tiến. Hồ sơ số filter của bộ phân biệt có khác trong metadata
đại diện (`original` so với `balanced`), nhưng repository chưa cung cấp thí
nghiệm độc lập để quy phần chênh lệch kết quả cho thay đổi này. Do đó không gọi
đây là một “cải tiến đã được chứng minh”.

## Họ và Other

Bốn họ chính là `boolean`, `union`, `time`, `error`. `other` được bảo toàn để
không làm mất dữ liệu nhưng không tham gia như một cơ chế cấu trúc thống nhất
trong ma trận đánh giá chính.
