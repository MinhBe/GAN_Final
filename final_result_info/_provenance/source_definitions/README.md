# Hệ thống sinh và đánh giá payload SQL Injection

Repository này triển khai pipeline nghiên cứu có thể truy vết từ dữ liệu gốc đến family, scenario, ratio, generator, chất lượng SQL, novelty, diversity, Random Forest và kiểm tra WAF. Toàn bộ cấu hình nghiên cứu nằm tại `configs/experiment_config.yaml`.

## Trạng thái hiện tại

Code cho Phase 1, Phase 2A, Phase 2B, Phase 3, so sánh cuối và WAF đã được triển khai. Quá trình thực nghiệm không chạy thẳng cấu hình lớn ngay từ đầu mà đi qua các lớp `smoke -> mini -> medium -> full`, sau đó dùng checkpoint/resume cho các job bị gián đoạn.

Các kịch bản có ít epoch hơn mức tối đa **không phải là kịch bản bị thiếu**. Nhiều run SeqGAN đã được chủ động kết thúc sớm vì `discriminator_reward_mean` thấp liên tục, thường hiển thị xấp xỉ `0.000` hoặc `0.0000`, không còn tín hiệu cải thiện. Run như vậy vẫn là một kết quả thực nghiệm hợp lệ nếu có `training_metadata.json`, log epoch và `stop_reason=vanishing_reward`.

Preflight lịch sử tại tỷ lệ thử nghiệm `1:20` cho thấy tỷ lệ này không khả thi nếu sáu scenario phải có cùng số payload:

| Đại lượng | Giá trị |
|---|---:|
| `normal_train` | 15.604 |
| Số attack cần cho mỗi cell tại `1:20` | 780 |
| `boolean_train_pool` | 3.669 |
| `union_train_pool` | 1.678 |
| `time_train_pool` | 1.186 |
| `error_train_pool` | 1.036 |
| Capacity `boolean/D` trong IQR | 1.842 |
| Capacity `union/D` trong IQR | 864 |
| Capacity `time/D` trong IQR | 597 |
| Capacity `error/D` trong IQR | 522 |

Pipeline không cap hoặc lấy mẫu có hoàn lại. Vì vậy cấu hình thực thi hiện tại dùng `1:50` cho Phase 2A; kết quả preflight `1:20` được giữ lại như bằng chứng về quá trình lựa chọn cấu hình, không được dùng để kết luận rằng các run dừng sớm do collapse là “thiếu dữ liệu” hay “thiếu kịch bản”. Báo cáo chi tiết nằm tại `data/prepared/phase2a/preflight.csv`.

## Quy tắc cố định

- Seed duy nhất: `88`.
- Phase 2A thực thi dùng ratio `1:50`; `1:20` chỉ là cấu hình preflight lịch sử đã bị loại.
- Phase 2B kiểm tra `full`, `1:10`, `1:20`, `1:50`, `1:100`, `1:200`, `1:500`.
- Không còn `budget_fraction`, `search_fraction`, `scale_int` hoặc cơ chế scale epoch.
- Mỗi model nhận toàn bộ attack train đã chọn. Model không tự chia train/test.
- Random Forest luôn dùng `normal_train`, `normal_test`, attack train và family holdout đã đóng băng.
- Scenario chỉ đọc từ family train pool. Holdout không bao giờ được đưa vào scenario hay generator.
- Output sinh giữ nguyên duplicate. Diversity không được tính trên tập đã deduplicate.
- Retrieval model được đánh giá bằng collapse riêng, không bị loại chỉ vì overlap với train cao.

## Chiến lược chạy từ kiểm tra nhẹ đến full

Mỗi thư mục run được định danh bằng các trường `phase / method / family / scenario / ratio / variant`. Cùng một kịch bản khoa học có thể xuất hiện ở nhiều hồ sơ thực thi bên dưới. Hồ sơ nhẹ dùng để kiểm tra code, dữ liệu và dấu hiệu collapse; chỉ hồ sơ `full` hoặc `B6X resume` mới được coi là lần chạy cấu hình cuối.

| Hồ sơ | Mục đích | Số mẫu sinh | Cấu hình chính |
|---|---|---:|---|
| `smoke` | Kiểm tra import, schema, đường dẫn và output contract | 64 | GAN 2 epoch, batch 32; CTGAN 2 epoch, batch 64; SeqGAN G-pretrain 1, D-pretrain `1 x 1`, adversarial tối đa 1, rollout 2; RF 20 cây |
| `mini` | Chạy thử nhẹ trên CPU/GPU và một số cell đại diện trước khi mở rộng | 200 | GAN 15 epoch, batch 64, noise 16, hidden 64; CTGAN 25 epoch, batch 500; SeqGAN G-pretrain 15, D-pretrain `8 x 2`, adversarial tối đa 6, D-step `3 x 1`, rollout 3; RF 30 cây |
| `medium` | Quét SeqGAN với chi phí vừa để phát hiện vanishing reward/collapse sớm | 500 | Batch 64; Master G-pretrain 60; Improved G-pretrain 60 hoặc 80 theo variant; D-pretrain `30 x 3`; adversarial tối đa 60; D-step `5 x 3`; rollout 8 |
| `full` | Lần chạy khoa học cuối với dữ liệu và ngân sách chuẩn | 2.000 | SMOTE `k=5`; GAN 100 epoch; CTGAN 300 epoch; Master G-pretrain 120; Improved G-pretrain 120/160; D-pretrain `50 x 3`; adversarial tối đa 200; D-step `5 x 3`; rollout 16; RF 300 cây |
| `B6X resume` | Khôi phục 13 job full bị gián đoạn, tăng batch và chạy song song | 2.000 | Batch 384; giữ lịch full của variant; checkpoint mỗi 10 epoch, giữ 3 bản; resume checkpoint mới nhất; tối đa 13 job đồng thời |

Trình tự thực tế:

1. Chạy `smoke` để bắt lỗi môi trường, dữ liệu và contract.
2. Chạy `mini` trên các cell đại diện trước, không dùng metric mini thay cho kết quả full.
3. Chạy `medium` cho SeqGAN để quan sát reward, stability và collapse trên grid rộng hơn.
4. Chỉ sau khi cấu hình ổn định mới chạy `full` với 2.000 mẫu sinh và ngân sách huấn luyện cuối.
5. Job full bị ngắt được tiếp tục bằng checkpoint; suffix `_B6X` mô tả cách khôi phục vận hành, không tạo ra một phương pháp khoa học mới.

### Cấu hình full theo phương pháp

| Phương pháp | Cấu hình full |
|---|---|
| SMOTE | `n_samples=2000`, `k_neighbors=5` |
| Vanilla GAN | `n_samples=2000`, `epochs=100`, `batch_size=64`, `noise_dim=32`, `hidden_dim=128`, `lr=0.0002` |
| CTGAN | `n_samples=2000`, `epochs=300`, `batch_size=500`, latent 128, hidden 256, PAC 10, 5 critic step |
| SeqGAN Master | `n_samples=2000`, length 20, batch 64, G-pretrain 120, D-pretrain `50 x 3`, adversarial tối đa 200, G-step 1, D-step `5 x 3`, rollout 16, generator LR 0.01, discriminator LR 0.0001 |
| SeqGAN Improved | Như Master về batch và lịch D; G-pretrain 120/160, length 20/160, tokenizer và SQL reward theo V1-V8; discriminator profile cân bằng, tổng 384 filter, label smoothing 0.05 |

Trong bảng, `D-pretrain a x b` nghĩa là `a` bước, mỗi bước `b` epoch; `D-step a x b` có cùng cách đọc trong từng adversarial epoch.

Các baseline full trong đợt so sánh cuối tập trung ở `R100`, `R200`, `R500`. Phase 2B vẫn giữ grid ratio rộng hơn để chọn cấu hình. Với mọi run, cấu hình dự kiến nằm trong config/command; cấu hình thực thi và số epoch thực tế phải ưu tiên đọc từ `training_metadata.json`, `run_manifest.json` và `logs/epoch_metrics.csv`.

### 13 run khôi phục B6X

Đợt `rerun_13` không phải một phase mới. Đây là 13 cell full được tiếp tục từ checkpoint với `batch_size=384`. Ba variant xuất hiện trong đợt này là:

| Variant | Length | G-pretrain | Tokenizer | SQL reward |
|---|---:|---:|---|---|
| V2 | 160 | 120 | `sql_aware` | Off |
| V4 | 160 | 160 | `raw_character` | Off |
| V8 | 160 | 160 | `sql_aware` | On |

| Run B6X | Epoch bổ sung sau resume | Trạng thái |
|---|---:|---|
| `boolean/E/R100/V2_B6X` | 40 | OK, completed |
| `time/D/R100/V8_B6X` | 30 | OK, completed |
| `union/D/R100/V2_B6X` | 40 | OK, completed |
| `union/D/R200/V2_B6X` | 40 | OK, completed |
| `boolean/D/R500/V8_B6X` | 40 | OK, completed |
| `boolean/E/R500/V2_B6X` | 40 | OK, completed |
| `error/B/R500/V8_B6X` | 40 | OK, completed |
| `error/D/R500/V4_B6X` | 30 | OK, completed |
| `error/D/R500/V8_B6X` | 30 | OK, completed |
| `time/A/R500/V8_B6X` | 40 | OK, completed |
| `time/D/R500/V8_B6X` | 30 | OK, completed |
| `union/D/R500/V2_B6X` | 40 | OK, completed |
| `union/D/R500/V8_B6X` | 40 | OK, completed |

“Epoch bổ sung” là phần huấn luyện của lượt resume, không phải tổng adversarial epoch từ đầu. Tổng epoch phải ghép checkpoint gốc với `training_metadata.json`/`epoch_metrics.csv`; không được lấy riêng tên checkpoint backup làm epoch hiện tại.

## Dừng sớm khi SeqGAN mất tín hiệu học

Runtime SeqGAN dùng trong các run này áp dụng quy tắc mặc định:

```text
EARLY_STOP_THRESHOLD = 0.05
EARLY_STOP_PATIENCE = 3
```

Sau mỗi adversarial epoch, runtime đo `discriminator_reward_mean`. Nếu reward nhỏ hơn `0.05` trong 3 epoch liên tiếp, run dừng với `stop_reason=vanishing_reward`, ghi epoch metrics và checkpoint cuối. Vì log console có thể làm tròn, chuỗi reward rất nhỏ thường được nhìn thấy dưới dạng `0.000`/`0.0000`.

Do đó:

- `adversarial_epochs=200` là trần kế hoạch, không phải số epoch bắt buộc phải tiêu hết.
- Một run full dừng ở epoch 11, 174 hoặc một epoch khác vẫn là **full configuration** nếu nó dùng dữ liệu/cấu hình full và kết thúc theo early-stop.
- Không được đánh dấu các run này là thiếu kịch bản; cần ghi `planned_epochs`, `actual_epochs` và `stop_reason`.
- Điều kiện đang theo dõi là reward của Discriminator. Nó là dấu hiệu collapse/vanishing training signal, nhưng không đồng nhất tuyệt đối với duplicate collapse của output; một run vẫn có thể có unique rate cao tại snapshot cuối.
- Có cờ `--disable-early-stop`, nhưng đây không phải mặc định của các lần chạy được tổng hợp. Ép chạy tiếp khi reward đã phẳng gần 0 chỉ hợp lý cho một thí nghiệm ablation riêng.

## Cài đặt

Môi trường hiện tại dùng Python 3.11. Cài dependency từ thư mục `GAN_for_SQLi`:

```powershell
python -m pip install -r requirements.txt
```

Các dependency chính gồm PyTorch, pandas, NumPy, scikit-learn, sqlparse, PyYAML, joblib và tqdm.

## Dữ liệu và fixed split

Nguồn gốc được giữ tại `data/SQLiV3.csv.zip`. Lệnh prepare sao chép nguồn vào `data/prepared/raw/SQLiV3.csv.zip` trước khi làm sạch hoặc tạo scenario, đồng thời lưu SHA-256 trong `dataset_manifest.json`.

```powershell
python scripts/research_pipeline.py prepare-data
python scripts/research_pipeline.py preflight-phase2a
```

Prepare thực hiện:

1. Đọc đúng CSV nằm trong ZIP bằng parser CSV chuẩn.
2. Chuẩn hóa label về `normal` hoặc `attack`.
3. Chuẩn hóa fingerprint bằng NFKC, casefold, quote và whitespace.
4. Loại duplicate cùng nhãn.
5. Cách ly toàn bộ group có conflict nhãn.
6. Phân family theo thứ tự ưu tiên `error -> time -> union -> boolean -> other`.
7. Chia cố định normal train/test và family train pool/holdout bằng seed 88.
8. Tạo Phase 1 mixed-attack dataset.
9. Chạy exact-count preflight cho sáu scenario Phase 2A.

Kết quả prepare hiện tại:

- 30.813 dòng sạch.
- 19.504 normal và 11.309 attack.
- 95 dòng duplicate chuẩn hóa bị loại.
- 2 group conflict gồm 10 dòng bị cách ly.
- Phân bố attack family: 4.586 boolean, 2.097 union, 1.482 time, 1.295 error và 1.849 other.
- SHA-256 nguồn: `5eba2294fba5e8c8f84d1f04b3e4fb1dfc4739fc086a19396fd5908440089933`.

Các split chính:

```text
data/prepared/splits/normal_train.csv
data/prepared/splits/normal_test.csv
data/prepared/splits/boolean_train_pool.csv
data/prepared/splits/boolean_holdout.csv
data/prepared/splits/union_train_pool.csv
data/prepared/splits/union_holdout.csv
data/prepared/splits/time_train_pool.csv
data/prepared/splits/time_holdout.csv
data/prepared/splits/error_train_pool.csv
data/prepared/splits/error_holdout.csv
```

## Sáu scenario

| ID | Cách chọn |
|---|---|
| A | Baseline theo thứ tự nguồn trong train pool |
| B | Shortest-first |
| C | Gần vùng độ dài modal nhất |
| D | Random không hoàn lại trong IQR Q1-Q3 |
| E | Uniform random không hoàn lại trên toàn pool |
| F | Greedy lexical diversity bằng character 3-gram Jaccard |

Target luôn là `floor(normal_train / ratio)`. Ordering của từng scenario là deterministic với seed 88; với các ratio số, tập có target nhỏ hơn là prefix nhất quán của cùng ordering.

## Năm phương pháp

### SMOTE

SMOTE nội suy giữa vector đặc trưng của attack train, sau đó tìm payload attack thật gần nhất trong không gian đã chuẩn hóa. Output chứa vector tổng hợp, payload được truy hồi, source ID và khoảng cách Euclidean chuẩn hóa.

### Vanilla GAN

Vanilla GAN học phân phối vector đặc trưng attack. Vector sinh được ánh xạ về một payload attack train gần nhất. Generator chỉ nhìn attack dataset được truyền vào, không chia lại dữ liệu và không chạy RF nội bộ.

### CTGAN

CTGAN học biểu diễn bảng có điều kiện trên attack train. Feature tổng hợp được inverse-transform, làm tròn và giữ trong `generated_feature_vectors.csv`; sau đó mỗi vector được ánh xạ về payload attack thật gần nhất trong cùng family bằng khoảng cách Euclidean trên feature đã chuẩn hóa. `generated_payloads.csv` chứa `retrieval_source_id` và `retrieval_distance`, nên CTGAN dùng retrieval collapse gate giống SMOTE và Vanilla GAN. Cấu hình nghiên cứu dùng 300 epoch và sinh cùng số output với các model còn lại.

### SeqGAN Master

Baseline là bản tái hiện PyTorch có thể chạy trên SQLi CSV. Code TensorFlow 1/Python 2 cũ chỉ sinh oracle integer token đã bị loại vì không tương thích pipeline. Baseline khóa các yếu tố:

- `raw_character`.
- Sequence length 20.
- Generator pretrain 120 epoch.
- SQL reward off.
- Discriminator profile original.
- Adversarial epoch tối đa 200; có thể kết thúc sớm khi mất tín hiệu reward.
- Seed 88.

### SeqGAN Improved

SeqGAN Improved dùng cùng engine để tránh khác biệt triển khai ngoài biến nghiên cứu. Hai biến còn thiếu trước đây đã trở thành tham số độc lập:

- `tokenizer_mode`: `raw_character` hoặc lossless `sql_aware`.
- `generator_reward_mode`: `off` hoặc `on`.

Khi SQL reward bật:

```text
R = 0.70 * R_discriminator + 0.30 * R_sql_structure
```

Việc bật reward không thay đổi `d_steps`, `d_epochs`, capacity hoặc lịch huấn luyện Discriminator.

Tokenizer SQL-aware giữ keyword, multi-character operator, comment và lexical unit ở mức atomic nhưng decode lossless. Nó không tự bơm literal variant để tạo diversity giả. `sequence_length` được hiểu theo token unit của tokenizer đang dùng, không luôn là số ký tự.

## Tám biến thể SeqGAN

| Variant | Sequence length | G pretrain | SQL reward | Tokenizer |
|---|---:|---:|---|---|
| V1 | 20 | 120 | Off | raw_character |
| V2 | 160 | 120 | Off | sql_aware |
| V3 | 20 | 160 | Off | sql_aware |
| V4 | 160 | 160 | Off | raw_character |
| V5 | 20 | 120 | On | sql_aware |
| V6 | 160 | 120 | On | raw_character |
| V7 | 20 | 160 | On | raw_character |
| V8 | 160 | 160 | On | sql_aware |

Đây là fractional factorial cân bằng: mỗi mức của từng yếu tố xuất hiện bốn lần.

## Metric chất lượng

`common/quality_metrics.py` tạo `quality_metrics.json` với ba nhóm chất lượng chính.

SQL structure:

- `sql_parse_rate`.
- `sql_structure_rate`.
- `family_motif_coverage`.
- `family_motif_hit_rate`.
- `garbage_rate`.
- Phân phối family suy luận cho Phase 1 mixed data.

`sql_parse_rate` chỉ cho biết sqlparse tạo được statement/token có ý nghĩa. Nó không chứng minh payload thực thi thành công trên một DBMS.

Novelty và overlap:

- `exact_input_overlap`.
- `normalized_input_overlap`.
- `holdout_overlap`.
- `normalized_holdout_overlap`.
- Mean, median và p90 nearest-input similarity.
- Character 3-gram Jaccard.
- Token Jaccard.
- Normalized edit similarity.
- Feature cosine similarity.

Diversity và collapse:

- `unique_rate` và normalized unique rate.
- Corrected character Self-BLEU, seed 88.
- `distinct_1`, `distinct_2`, `distinct_3`.
- Dominant payload share.
- Character, token, keyword, operator, function, comment-style và length-zone diversity.
- Retrieval nearest-payload coverage và distance distribution.

Training stability của SeqGAN được ghi riêng trong `training_metadata.json` và `logs/epoch_metrics.csv`:

- Generator/discriminator loss.
- Reward mean và variance.
- Generator/discriminator gradient norm.
- Unique rate, dominant share và collapse theo epoch.
- Stop reason và wall-clock time.

## Random Forest

`export/classifier_export/rf_eval.py` nhận bốn tập cố định và generated payload:

```text
normal_train + real_attack_train + generated_attack -> train
normal_test + family_holdout -> test
```

File `rf_metrics.json` báo cáo baseline, augmented và delta cho:

- Macro F1.
- Attack precision, recall và F1.
- Balanced accuracy.
- PR-AUC.

RF không tham gia ranking chính của Phase 2A. RF chỉ là viability signal ở Phase 2B và một nhóm riêng trong Phase 3.

## Ranking

### Phase 1

Bốn run mixed-attack được dùng để hiệu chỉnh threshold validity/collapse theo từng loại generator. Retrieval và direct-generation có gate riêng.

### Phase 2A

1. Validity gate kiểm tra completion, schema, số output, metric hữu hạn, SQL validity, garbage và collapse.
2. Xếp rank ngang nhau cho SQL, novelty và diversity.
3. Xếp sáu scenario riêng trong từng `family x method`.
4. Tổng hợp bốn method bằng Borda và median rank.
5. Chỉ scenario hợp lệ ở đủ bốn method mới được chọn top 2.

Không có `win_score`, không có công thức `70% quality + 30% F1`.

### Phase 2B

Một ratio chỉ được chọn nếu toàn bộ tám family-scenario cell và cả bốn baseline method vượt viability gate. Hệ thống chọn ratio số lớn nhất đạt điều kiện.

### Phase 3

Mỗi variant được xếp theo năm nhóm ngang nhau trên đủ tám frozen dataset:

- SQL structure.
- Novelty.
- Diversity.
- Training stability.
- RF utility.

Variant phải hợp lệ trên toàn bộ tám dataset, không thể thắng nhờ một family riêng lẻ.

## Trình tự chạy

### Phase 1: 4 run

```powershell
python scripts/research_pipeline.py matrix --phase phase1
python scripts/research_pipeline.py run-matrix --matrix results/phase1/run_matrix.csv --steps all --execute --resume
python scripts/research_pipeline.py calibrate-phase1
```

### Phase 2A: 96 run

Preflight lịch sử tại `1:20` trả exit code 2 vì dữ liệu không đủ. Sau bước kiểm tra nhẹ, Phase 2A được chốt chạy ở `1:50` trong `configs/experiment_config.yaml`:

```powershell
python scripts/research_pipeline.py preflight-phase2a
python scripts/research_pipeline.py matrix --phase phase2a
python scripts/research_pipeline.py run-matrix --matrix results/phase2a/run_matrix.csv --steps all --execute --resume
python scripts/research_pipeline.py rank-phase2a
```

Khi kiểm kê kết quả, phân biệt rõ ba trạng thái: `completed`, `vanishing_reward` và lỗi thật sự. `vanishing_reward` là kết thúc sớm có chủ đích, không phải cell chưa chạy.

### Phase 2B: 224 run kế hoạch

Sau khi Phase 2A có `top2_scenarios_per_family.csv`:

```powershell
python scripts/research_pipeline.py prepare-phase2b
python scripts/research_pipeline.py matrix --phase phase2b
python scripts/research_pipeline.py run-matrix --matrix results/phase2b/run_matrix.csv --steps all --execute --resume
python scripts/research_pipeline.py select-ratio
```

Cell không đủ attack cho một ratio được ghi `insufficient_pool` và không được chạy như thể ratio đó đã đạt.
SeqGAN có thể kết thúc trước trần epoch do early-stop; khi đó dùng `actual_epochs` và `stop_reason` trong metadata để phân loại, không yêu cầu phải có checkpoint của mọi epoch đến 200.

### Phase 3: 64 run

```powershell
python scripts/research_pipeline.py freeze-phase3
python scripts/research_pipeline.py matrix --phase phase3
python scripts/research_pipeline.py run-matrix --matrix results/phase3/run_matrix.csv --steps all --execute --resume
python scripts/research_pipeline.py rank-phase3
```

### So sánh cuối: tối đa 40 run

Chạy độc lập năm method trên tám frozen dataset:

```powershell
python scripts/research_pipeline.py matrix --phase final
python scripts/research_pipeline.py run-matrix --matrix results/final/run_matrix.csv --steps all --execute --resume
python scripts/research_pipeline.py finalize
```

Hoặc tái sử dụng 32 baseline run từ Phase 2B và 8 run của variant thắng Phase 3:

```powershell
python scripts/research_pipeline.py finalize --reuse
```

Kết quả được tách thành:

- `sql_structural_quality.csv`.
- `novelty_overlap.csv`.
- `diversity_collapse.csv`.
- `training_stability.csv`.
- `rf_utility.csv`.
- `final_comparison.csv`.

Không cộng toàn bộ metric thành một điểm duy nhất.

## Output contract

Một run hoàn chỉnh do `run-matrix --steps all --execute` điều phối có các artifact chung:

```text
run_manifest.json
training_metadata.json
generated_payloads.csv
generated_feature_vectors.csv
quality_metrics.json
rf_metrics.json
logs/
```

SeqGAN bổ sung `tokenizer.json`, `generator.pt`, `discriminator.pt` và `logs/epoch_metrics.csv`. Checkpoint theo epoch chỉ được tạo khi chạy standalone với `--checkpoint-dir` hoặc `--checkpoint-copy-dir`; orchestrator mặc định không bật cơ chế này. `run_manifest.json` chứa tập command đã chạy, seed, config hash, input hash, `started_at`, `ended_at`, status và failed step. `run-matrix --resume` chỉ bỏ qua run đã hoàn thành đủ artifact của các step được yêu cầu. Checkpoint là dữ liệu phục hồi, không phải nguồn duy nhất để xác định epoch hiện tại hay trạng thái hoàn tất; ưu tiên log và metadata. Run dừng vì `vanishing_reward` phải giữ model cuối, log và stop reason.

## WAF Docker Compose

Compose dùng image chính thức `owasp/modsecurity-crs:4.25.1-nginx-202607160307`, backend riêng trong internal network và chỉ publish WAF lên loopback. Image thực thi đã được xác nhận bằng digest:

```text
owasp/modsecurity-crs@sha256:a7d2e948d26ec310a127b261e4b9010ff2467b9f5f7eaed4921450bb7865ba08
```

Thay các placeholder trong đường dẫn input bằng family, scenario, ratio và variant thực tế đã được chọn:

```powershell
python scripts/research_pipeline.py waf-up
python scripts/research_pipeline.py evaluate-waf --input "results/final/seqgan_improved/<family>/<scenario>/R<ratio>/<variant>/generated_payloads.csv"
python scripts/research_pipeline.py waf-down
```

Evaluator gửi cả GET và POST, giữ duplicate/empty input, không theo redirect và ghi:

- `waf_probe_results.csv`.
- `waf_summary.json`.

Target không phải loopback bị từ chối mặc định. `--allow-remote` phải được chỉ định rõ nếu thực sự cần đánh giá một hệ thống được phép khác. Image và biến môi trường dựa trên repository chính thức của [OWASP Core Rule Set Docker](https://github.com/coreruleset/modsecurity-crs-docker).

### Campaign chỉ dùng payload Final/full

Campaign đã triển khai chỉ chọn entry khớp chính xác:

```text
result/final/**/generated_payloads.csv
```

Không trộn Phase 1, 2A, 2B, 3, smoke, mini, medium, checkpoint hay B6X. Sáu ZIP Final cung cấp 96 CSV nguồn, tương ứng `4 model x 3 ratio x 8 family-scenario cell`. File đầu vào WAF duy nhất có đúng một cột `payload`:

```text
result/waf/final_full/input/generated_payloads_final_full.csv
```

File chứa 192.000 payload, giữ nguyên 168.283 duplicate và 8 dòng rỗng. SHA-256:

```text
9444a386719235053f773567f03267beb2f8a8d6d0b10f25702e8504482e14d1
```

Mỗi dòng được gửi qua cả GET và POST, tổng cộng 384.000 probe. Kết quả:

| Nhóm | Probe | Bị chặn 403 | Qua WAF 200 | Block rate |
|---|---:|---:|---:|---:|
| Toàn bộ | 384.000 | 293.840 | 90.160 | 76,52% |
| CTGAN | 96.000 | 95.762 | 238 | 99,75% |
| Vanilla GAN | 96.000 | 95.954 | 46 | 99,95% |
| SeqGAN Master | 96.000 | 6.462 | 89.538 | 6,73% |
| SMOTE | 96.000 | 95.662 | 338 | 99,65% |

Không có network error. GET và POST cho cùng số block: mỗi phương thức chặn 146.920/192.000.

HTTP 200 chỉ được gọi là **ứng viên bypass WAF**, không chứng minh SQL injection đã khai thác thành công. Backend cục bộ chỉ echo request và không có DBMS. Đặc biệt, block rate thấp của SeqGAN Master phải được đọc cùng `sql_structure_rate`, garbage và collapse: output hỏng hoặc không còn cấu trúc SQL cũng có thể không khớp chữ ký CRS.

Các script tái lập:

```text
scripts/aggregate_waf_input.py
scripts/run_waf_campaign.py
scripts/summarize_waf_results.py
```

Campaign runner chạy song song, ghi kết quả liên tục và checkpoint mỗi 5.000 probe; dùng `--resume` nếu bị ngắt. Báo cáo đầy đủ nằm tại:

```text
result/waf/final_full/analysis/WAF_FINAL_FULL_REPORT.md
```

## Quyết định sau preflight 1:20

`1:20` từng được dùng ở bước kiểm tra khả thi nhưng không đủ capacity cho toàn bộ sáu scenario, đặc biệt `time/D` và `error/D`. Quyết định thực thi là giữ toàn bộ normal train, không sampling có hoàn lại và chuyển Phase 2A sang `1:50`. Cách này giữ nguyên định nghĩa scenario, tránh duplicate nhân tạo và phù hợp với mức ratio đã có trong grid Phase 2B.

Các bảng, notebook hoặc snapshot cũ còn ghi `1:20` phải được phân loại là **preflight/historical configuration**. Chúng không phải cấu hình full cuối và cũng không phải nguyên nhân của các run SeqGAN dừng sớm: các run đó dừng do `vanishing_reward`.

## Kiểm thử

```powershell
python -B -m unittest discover -s tests -v
python -m py_compile common/ingestion.py common/quality_metrics.py scripts/research_pipeline.py scripts/rank_combinations.py
docker compose -f docker/docker-compose.yml config --quiet
```

Test bao phủ conflict/dedup, fixed split, deterministic scenario, exact matrix count, metric, threshold, retrieval gate, Borda, ratio selection, SeqGAN tokenizer/reward/output và WAF loopback safety.

Docker Compose đã qua kiểm tra cấu hình. Container chưa được khởi động trong lần chuẩn hóa này vì Docker daemon trên máy đang tắt.

## Quy mô thiết kế nghiên cứu

| Giai đoạn | Run |
|---|---:|
| Phase 1 | 4 |
| Phase 2A | 96 |
| Phase 2B | 224 |
| Phase 3 | 64 |
| Tổng chính | 388 |
| Final độc lập, tùy chọn | 40 |
| Tổng tối đa | 428 |

Các con số trên là kích thước ma trận thiết kế, không phải cam kết rằng mọi SeqGAN sẽ chạy đủ trần 200 epoch. Quy trình thực tế đã benchmark bằng smoke/mini/medium trước khi chạy full. Khi báo cáo tiến độ, đếm kịch bản đã được khởi chạy/kết thúc riêng với số epoch đã tiêu thụ; không biến `vanishing_reward` thành “kịch bản còn thiếu”.
