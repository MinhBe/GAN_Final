# Hệ thống sinh và đánh giá payload SQL Injection

Repository này triển khai pipeline nghiên cứu có thể truy vết từ dữ liệu gốc đến family, scenario, ratio, generator, chất lượng SQL, novelty, diversity, Random Forest và kiểm tra WAF. Toàn bộ cấu hình nghiên cứu nằm tại `configs/experiment_config.yaml`.

## Trạng thái hiện tại

Code cho Phase 1, Phase 2A, Phase 2B, Phase 3, so sánh cuối và WAF đã được triển khai. Các model và pipeline chưa được chạy full.

Preflight trên dữ liệu thật đang chặn Phase 2A vì tỷ lệ đã chốt `1:20` không khả thi nếu sáu scenario phải có cùng số payload:

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

Pipeline không cap hoặc lấy mẫu có hoàn lại. Ma trận Phase 2A vẫn có đúng 96 run kế hoạch: 88 run có cell đủ dữ liệu nhưng bị khóa do exact-count preflight toàn cục không đạt, và 8 run thuộc `time/D` hoặc `error/D` thiếu dữ liệu. Báo cáo chi tiết nằm tại `data/prepared/phase2a/preflight.csv`.

## Quy tắc cố định

- Seed duy nhất: `88`.
- Phase 2A dùng ratio `1:20`.
- Phase 2B kiểm tra `full`, `1:10`, `1:20`, `1:50`, `1:100`, `1:200`, `1:500`.
- Không còn `budget_fraction`, `search_fraction`, `scale_int` hoặc cơ chế scale epoch.
- Mỗi model nhận toàn bộ attack train đã chọn. Model không tự chia train/test.
- Random Forest luôn dùng `normal_train`, `normal_test`, attack train và family holdout đã đóng băng.
- Scenario chỉ đọc từ family train pool. Holdout không bao giờ được đưa vào scenario hay generator.
- Output sinh giữ nguyên duplicate. Diversity không được tính trên tập đã deduplicate.
- Retrieval model được đánh giá bằng collapse riêng, không bị loại chỉ vì overlap với train cao.

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
- Adversarial epoch 200.
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

Lệnh preflight hiện trả exit code 2 vì dữ liệu không đủ tại `1:20`. Hai lệnh sau chỉ tạo và kiểm tra kế hoạch, không train model:

```powershell
python scripts/research_pipeline.py preflight-phase2a
python scripts/research_pipeline.py matrix --phase phase2a
python scripts/research_pipeline.py run-matrix --matrix results/phase2a/run_matrix.csv --steps all
```

Sau khi giải quyết blocker và chạy lại `prepare-data`, toàn bộ Phase 2A mới được thực thi và ranking theo thứ tự:

```powershell
python scripts/research_pipeline.py matrix --phase phase2a
python scripts/research_pipeline.py run-matrix --matrix results/phase2a/run_matrix.csv --steps all --execute --resume
python scripts/research_pipeline.py rank-phase2a
```

### Phase 2B: 224 run kế hoạch

Sau khi Phase 2A có `top2_scenarios_per_family.csv`:

```powershell
python scripts/research_pipeline.py prepare-phase2b
python scripts/research_pipeline.py matrix --phase phase2b
python scripts/research_pipeline.py run-matrix --matrix results/phase2b/run_matrix.csv --steps all --execute --resume
python scripts/research_pipeline.py select-ratio
```

Cell không đủ attack cho một ratio được ghi `insufficient_pool` và không được chạy như thể ratio đó đã đạt.

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

SeqGAN bổ sung `tokenizer.json`, `generator.pt`, `discriminator.pt` và `logs/epoch_metrics.csv`. Checkpoint theo epoch chỉ được tạo khi chạy standalone với `--checkpoint-dir` hoặc `--checkpoint-copy-dir`; orchestrator mặc định không bật cơ chế này. `run_manifest.json` chứa tập command đã chạy, seed, config hash, input hash, `started_at`, `ended_at`, status và failed step. `run-matrix --resume` chỉ bỏ qua run đã hoàn thành đủ artifact của các step được yêu cầu.

## WAF Docker Compose

Compose dùng image chính thức `owasp/modsecurity-crs:4.25-lts-nginx`, backend riêng trong internal network và chỉ publish WAF lên loopback.

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

## Xử lý blocker 1:20

Không có lựa chọn nào dưới đây tương đương về phương pháp luận. Cần chốt một lựa chọn trước khi chạy Phase 2A:

1. Giữ toàn bộ normal train và đổi Phase 2A sang ít nhất `1:30`, khi đó `floor(15.604 / 30) = 520` không vượt capacity nhỏ nhất là 522. `1:50` là mức gần nhất đã có trong grid Phase 2B.
2. Giữ `1:20` nhưng cap `normal_train` tối đa 10.459 để `floor(normal_train / 20) <= 522`, đưa 5.145 normal còn lại vào reserve. Điều này làm thay đổi giả định sử dụng toàn bộ dữ liệu train.
3. Bổ sung và kiểm chứng thêm payload `time/error`, đặc biệt error payload nằm trong IQR.
4. Định nghĩa lại Scenario D hoặc cho phép sampling có hoàn lại. Hai cách này thay đổi biến nghiên cứu và không được pipeline thực hiện mặc định.

Phương án có hoàn lại không được khuyến nghị vì làm tăng duplicate, làm sai diversity và khiến Scenario D không còn so sánh công bằng với A-F.

## Kiểm thử

```powershell
python -B -m unittest discover -s tests -v
python -m py_compile common/ingestion.py common/quality_metrics.py scripts/research_pipeline.py scripts/rank_combinations.py
docker compose -f docker/docker-compose.yml config --quiet
```

Test bao phủ conflict/dedup, fixed split, deterministic scenario, exact matrix count, metric, threshold, retrieval gate, Borda, ratio selection, SeqGAN tokenizer/reward/output và WAF loopback safety.

Docker Compose đã qua kiểm tra cấu hình. Container chưa được khởi động trong lần chuẩn hóa này vì Docker daemon trên máy đang tắt.

## Quy mô nghiên cứu

| Giai đoạn | Run |
|---|---:|
| Phase 1 | 4 |
| Phase 2A | 96 |
| Phase 2B | 224 |
| Phase 3 | 64 |
| Tổng chính | 388 |
| Final độc lập, tùy chọn | 40 |
| Tổng tối đa | 428 |

428 run là khả thi về kiến trúc nhưng chưa đủ cơ sở để cam kết thời gian. Cần đo wall-clock của một cell đại diện cho từng model trước khi chạy full matrix. SeqGAN với rollout 16 và CTGAN 300 epoch là hai thành phần cần benchmark trước.
