# Final result — Phân tích toàn bộ quá trình thực nghiệm GAN cho SQLi

README này là tài liệu dẫn đường cho bộ kết quả tại `H:\My Drive\GAN\final_result`.
Nó giải thích từng phase dùng để trả lời câu hỏi nào, điều kiện chạy, kết quả quan
sát được, kết quả nào đã dẫn đến quyết định nào, và những giới hạn cần giữ khi
diễn giải.

> Kết luận quan trọng nhất: `phase3_seqgan_improved_test_medium` và
> `final_full/seqgan_improved_refinement` là hai campaign khác nhau. Phase 3 gồm
> 64 run test-medium tại R200; refinement gồm 33 run full tại R100/R200/R500.
> Không được gộp chúng chỉ vì các manifest lịch sử từng dùng nhãn `phase3`.

## 1. Phạm vi và tính toàn vẹn của bộ kết quả

| Campaign | Run | Vai trò |
|---|---:|---|
| `phase1_survey` | 4 | Khảo sát/calibration ban đầu cho bốn phương pháp |
| `phase2a_scenario_search` | 96 | So sánh sáu cách chọn dữ liệu A–F |
| `phase2b_ratio_search_medium` | 196 | Khảo sát độ mất cân bằng và chọn ratio vận hành |
| `phase3_seqgan_improved_test_medium` | 64 | Test 8 variant SeqGAN Improved ở cấu hình medium |
| `final_full/baselines` | 96 | Chạy full SMOTE, GAN, CTGAN, SeqGAN Master |
| `final_full/seqgan_improved_refinement` | 33 | Chạy full 11 target SeqGAN Improved tại ba ratio |
| **Tổng** | **489** | |

Bộ tổng hợp đã được kiểm tra:

- 489/489 `run_manifest.json`;
- 489/489 `training_metadata.json`;
- 489/489 `quality_metrics.json`;
- 489/489 `rf_metrics.json`;
- 5.729 file, khoảng 2,84 GB, tính cả README và provenance quyết định;
- 52 checkpoint phục hồi B6X, tổng 121.661.148 byte;
- không có run key trùng khi khóa định danh có thêm `campaign`;
- file nguồn không bị di chuyển hoặc xóa;
- SHA-256 của từng run artifact trong lần build nằm trong
  [`_index/artifact_inventory.csv`](_index/artifact_inventory.csv).

## 2. Cách đọc kết quả đúng

### 2.1. Không đồng nhất “run hoàn tất” với “mô hình học tốt”

Một run có thể hoàn tất pipeline và sinh đủ artifact nhưng dừng adversarial sớm
vì `vanishing_reward`. Khi đó:

- run vẫn là một quan sát thực nghiệm hợp lệ và phải được lưu;
- `planned_adv_epochs` là trần kế hoạch, không phải số epoch bắt buộc;
- `actual_adv_epochs` và `stop_reason` mới mô tả điều đã xảy ra;
- run có thể bị loại khỏi viability/ranking nhưng không được gọi là “chưa chạy”.

Thứ tự ưu tiên khi đọc trạng thái:

1. `run_manifest.json`: campaign, định danh, nguồn và trạng thái pipeline;
2. `training_metadata.json`: cấu hình thực thi, số epoch thực tế, stop reason;
3. `logs/epoch_metrics.csv`: diễn biến theo epoch;
4. `quality_metrics.json`: cấu trúc SQL, novelty, diversity, collapse;
5. `rf_metrics.json`: ảnh hưởng của augmentation lên Random Forest.

### 2.2. Retrieval và direct generation không cùng bản chất

SMOTE, Vanilla GAN và CTGAN trong pipeline sinh/biến đổi vector đặc trưng rồi
truy hồi payload attack thật gần nhất. Vì vậy:

- `normalized_input_overlap` có thể bằng 1,0 theo thiết kế;
- SQL structure thường rất cao vì output cuối là payload thật được truy hồi;
- unique rate thấp không nhất thiết là lỗi code, nhưng cho thấy retrieval
  collapse hoặc tập nguồn quá nhỏ.

SeqGAN Master và SeqGAN Improved sinh chuỗi trực tiếp. Với hai phương pháp này,
novelty cao chỉ có ý nghĩa khi đi cùng SQL structure đủ tốt và garbage đủ thấp.

Do đó không được kết luận “CTGAN tốt hơn SeqGAN” chỉ từ SQL structure, hoặc
“SeqGAN tốt hơn CTGAN” chỉ từ novelty.

### 2.3. Ý nghĩa các metric chính

| Metric | Cách đọc |
|---|---|
| `sql_parse_rate` | Parser tạo được statement/token có nghĩa; không chứng minh khai thác DBMS thành công |
| `sql_structure_rate` | Tỷ lệ payload còn hình dạng SQL injection có ích |
| `garbage_rate` | Phần output không đạt cấu trúc mong đợi; thấp hơn là tốt hơn |
| `unique_rate` | Tỷ lệ payload khác nhau; cao chưa đủ nếu phần lớn là rác |
| `dominant_payload_share` | Mức một payload chiếm ưu thế; cao là dấu hiệu collapse |
| `normalized_input_overlap` | Trùng với tập huấn luyện sau chuẩn hóa |
| `self_bleu` | Tương đồng nội bộ; cao thường nghĩa là diversity thấp |
| `delta_macro_f1` | Macro-F1 sau augmentation trừ baseline |
| `delta_attack_recall` | Attack recall sau augmentation trừ baseline |

RF là tín hiệu utility phụ trợ, không phải bằng chứng rằng payload khai thác SQLi
thành công. Một tập payload rác vẫn có thể thay đổi decision boundary của RF.

## 3. Điều kiện cố định của toàn nghiên cứu

- Seed: `88`.
- Fixed split: normal train/test và attack train-pool/holdout theo family.
- Family: `boolean`, `error`, `time`, `union`.
- Sáu scenario:

| Scenario | Quy tắc chọn attack train |
|---|---|
| A | Thứ tự nguồn ban đầu |
| B | Payload ngắn trước |
| C | Gần vùng độ dài modal |
| D | Random không hoàn lại trong IQR Q1–Q3 |
| E | Uniform random không hoàn lại trên toàn pool |
| F | Greedy lexical diversity theo character 3-gram Jaccard |

- Phase 2A thực thi ở R50. R20 chỉ là preflight lịch sử không đủ capacity.
- Phase 2B khảo sát `full`, R10, R20, R50, R100, R200, R500.
- Final/full tập trung vào R100, R200, R500.
- Output sinh giữ nguyên duplicate; không deduplicate trước khi tính diversity.
- Holdout không được dùng để tạo scenario hoặc train generator.

## 4. Chuỗi thực nghiệm và quyết định

```text
Phase 1: khảo sát và hiệu chỉnh gate
    ↓
Phase 2A: so sánh A–F → giữ hai scenario/family
    ↓
Phase 2B: quét ratio → dùng R200 làm ratio vận hành cho Phase 3
    ↓
Phase 3 medium: test V1–V8 trên 8 frozen cell
    ↓
V8 làm anchor + local champion theo cell
    ↓
Final full:
  - 96 baseline tại R100/R200/R500
  - 33 SeqGAN Improved refinement tại R100/R200/R500
```

Chuỗi trên là trình tự vận hành thực tế. Một số bước selection không đạt đúng
gate “đủ bốn method” của thiết kế lý tưởng; các ngoại lệ đó được ghi rõ trong
từng mục bên dưới.

---

## 5. Phase 1 — Survey và calibration

### Mục đích

Phase 1 không nhằm tìm mô hình thắng. Nó dùng dữ liệu mixed-attack để:

- xác minh ingestion, schema và output contract;
- quan sát collapse đặc trưng của retrieval và direct generation;
- đặt ngưỡng validity/viability ban đầu;
- quyết định metric nào phải được tách riêng giữa retrieval và direct.

### Quy mô và profile thực tế

Có bốn run, mỗi method một run. Đây là “best available”, không phải bốn run có
ngân sách giống hệt nhau:

| Method | Profile | Payload | SQL structure | Garbage | Unique | Input overlap | RF macro-F1 |
|---|---|---:|---:|---:|---:|---:|---:|
| CTGAN | full | 2.000 | 0,970 | 0,030 | 0,663 | 1,000 | 0,998 |
| GAN | full | 2.000 | 0,992 | 0,008 | 0,241 | 1,000 | 0,998 |
| SeqGAN Master | medium | 500 | 0,558 | 0,442 | 0,364 | 0,194 | 0,998 |
| SMOTE | full | 2.000 | 0,978 | 0,022 | 0,852 | 1,000 | 0,998 |

### Gate được tạo từ nhánh SeqGAN

Artifact `validity_thresholds.json` tìm thấy trong nhánh
`results_seqgan_phase2b_phase3` ghi:

- calibration run: 1;
- calibration method: `seqgan_master`;
- margin: 0,05;
- generated count tối thiểu: 500 và phải đủ 100% số yêu cầu;
- `sql_parse_rate ≥ 0,95`;
- `sql_structure_rate ≥ 0,508`;
- `family_motif_coverage ≥ 0,2833`;
- `garbage_rate ≤ 0,492`;
- direct generation:
  - `unique_rate ≥ 0,314`;
  - `dominant_payload_share ≤ 0,184`;
  - `normalized_input_overlap ≤ 0,244`;
- RF:
  - macro-F1 drop không quá 0,10;
  - attack-recall drop không quá 0,15.

`vanishing_reward` nằm trong danh sách severe stop reason của viability gate.
Điều này không mâu thuẫn với việc vẫn lưu run: nó có thể là kết quả hoàn chỉnh
về mặt thực nghiệm nhưng không đủ điều kiện đi tiếp trong automatic selection.

### Kết quả dẫn đến quyết định gì?

- Retrieval methods có SQL structure cao nhưng overlap 1,0, chứng minh cần một
  gate riêng cho retrieval thay vì dùng overlap của direct generation.
- GAN chỉ đạt unique 0,241, cho thấy dấu hiệu retrieval collapse dù SQL
  structure 0,992.
- SeqGAN Master có novelty tốt hơn retrieval nhưng garbage 0,442, sát trần
  0,492; điều này dẫn đến việc Phase 2A/2B phải đánh giá đồng thời structure,
  diversity và stability.

### Giới hạn

Threshold artifact thực tế được calibration từ một SeqGAN Master run, không
phải bốn method. Bảng bốn run cũng trộn profile full và medium. Vì vậy Phase 1
chỉ cung cấp gate vận hành và chẩn đoán, không cung cấp ranking công bằng.

---

## 6. Phase 2A — Tìm scenario

### Mục đích

So sánh sáu cách chọn dữ liệu A–F trong từng family, tránh chạy toàn bộ ratio và
variant trên các scenario kém triển vọng.

### Thiết kế

```text
4 method × 4 family × 6 scenario = 96 run
```

- Ratio: R50.
- Profile: mini.
- Mỗi run sinh 200 payload.
- Bốn method: SMOTE, GAN, CTGAN, SeqGAN Master.

### Top-2 được chốt

| Family | Hạng 1 | Hạng 2 | Tập cell chuyển sang Phase 2B/3 |
|---|---|---|---|
| Boolean | E | D | `boolean/E`, `boolean/D` |
| Error | D | B | `error/D`, `error/B` |
| Time | A | D | `time/A`, `time/D` |
| Union | D | F | `union/D`, `union/F` |

### Điều gì dẫn đến quyết định?

Artifact `top2_scenarios_per_family.csv` ghi nguồn quyết định là
`smote_ctgan_borda_R50_mini`. Nghĩa là quyết định vận hành top-2 được tạo từ
Borda mini của SMOTE + CTGAN, sau đó được dùng để đóng băng tám cell:

```text
boolean: E, D
error:   D, B
time:    A, D
union:   D, F
```

Scenario D xuất hiện ở cả bốn family, nên về sau được dùng như một anchor để
so sánh xuyên family. Scenario còn lại là local candidate của từng family.

### Giới hạn

Thiết kế lý tưởng yêu cầu Borda trên đủ bốn method. File quyết định thực tế chỉ
ghi SMOTE + CTGAN. Vì vậy đây là **selection vận hành**, không phải bằng chứng
rằng top-2 đã thắng trên đủ bốn method. Kết quả Phase 2A mini cũng không được
dùng thay cho chất lượng full.

---

## 7. Phase 2B — Khảo sát ratio

### Mục đích

Đánh giá mức mất cân bằng normal:attack trên tám cell đã chọn, kiểm tra:

- capacity dữ liệu ở từng ratio;
- viability của bốn baseline method;
- chất lượng cấu trúc, collapse và RF utility khi attack train giảm.

### Kế hoạch và số run thực tế

Kế hoạch đầy đủ:

```text
8 cell × 7 ratio × 4 method = 224 run
```

Kết quả thực tế là 196 run:

| Ratio | Cell/method có dữ liệu | Tổng run | Trạng thái capacity |
|---|---:|---:|---|
| full | 8 | 32 | Đủ |
| R10 | 3 | 12 | Thiếu 5 cell/method |
| R20 | 6 | 24 | Thiếu 2 cell/method |
| R50 | 8 | 32 | Đủ |
| R100 | 8 | 32 | Đủ |
| R200 | 8 | 32 | Đủ |
| R500 | 8 | 32 | Đủ |

28 run không xuất hiện vì `insufficient_pool`, không phải do Colab ngắt.

### Tóm tắt quan sát theo ratio

Bảng dưới là trung bình mô tả trên các run hiện có. Nó trộn retrieval và direct
generation, nên không phải bảng ranking chính thức.

| Ratio | Run | SQL structure | Garbage | Unique | Δ macro-F1 | Δ attack recall |
|---|---:|---:|---:|---:|---:|---:|
| full | 32 | 0,905 | 0,095 | 0,411 | 0,000 | 0,000 |
| R10 | 12 | 0,896 | 0,105 | 0,418 | +0,004 | +0,012 |
| R20 | 24 | 0,936 | 0,065 | 0,325 | +0,001 | +0,003 |
| R50 | 32 | 0,867 | 0,133 | 0,271 | +0,004 | +0,012 |
| R100 | 32 | 0,880 | 0,120 | 0,254 | +0,004 | +0,014 |
| R200 | 32 | 0,768 | 0,232 | 0,319 | +0,002 | +0,008 |
| R500 | 32 | 0,751 | 0,249 | 0,279 | −0,023 | −0,045 |

Ở R500, trung bình RF giảm. Phân tích theo method cho thấy:

- SMOTE: Δ attack recall +0,020;
- CTGAN: −0,055;
- GAN: −0,084;
- SeqGAN Master: −0,062.

R500 vì vậy là vùng stress-test rõ rệt, không phải ratio mặc nhiên tốt hơn.

### Điều kiện chọn ratio trong thiết kế lý tưởng

Một ratio chỉ được chọn khi:

- đủ tám cell;
- đủ bốn method;
- mọi cell/method vượt viability gate;
- chọn ratio số lớn nhất vẫn đạt toàn bộ điều kiện.

### Quyết định thực tế

`selected_global_ratio.json` ghi:

```text
selected_global_ratio = 200
selection_method = auto_composite_score
```

Ghi chú trong chính file này nói ratio được chọn từ composite
`family_motif_hit_rate + unique_rate - garbage_rate - model_collapse_rate` trên
SeqGAN Master và đã **bypass** `select-ratio` chính thức vì chưa có đủ kết quả
bốn method tại thời điểm ra quyết định.

Do đó:

- R200 là ratio vận hành dùng để tạo Phase 3 medium;
- không được mô tả R200 là ratio đã thắng gate chính thức trên đủ bốn method;
- R100/R200/R500 tiếp tục được giữ trong Final để kiểm tra độ nhạy.

---

## 8. Phase 3 — Test-medium SeqGAN Improved

### Mục đích

Kiểm tra nhanh tám variant SeqGAN Improved trên tám frozen cell trước khi bỏ chi
phí full. Đây là campaign chẩn đoán stability/collapse, không phải final full.

### Thiết kế

```text
8 cell × 8 variant = 64 run
```

- Ratio: R200.
- Payload yêu cầu: 500.
- Batch: 64.
- G-pretrain: 60 hoặc 80 tùy variant.
- D-pretrain: 30 × 3.
- Adversarial tối đa: 60 epoch.
- Rollout: 8.

### Tám variant

| Variant | Length | G-pretrain full tương ứng | SQL reward | Tokenizer |
|---|---:|---:|---|---|
| V1 | 20 | 120 | Off | raw character |
| V2 | 160 | 120 | Off | SQL-aware |
| V3 | 20 | 160 | Off | SQL-aware |
| V4 | 160 | 160 | Off | raw character |
| V5 | 20 | 120 | On | SQL-aware |
| V6 | 160 | 120 | On | raw character |
| V7 | 20 | 160 | On | raw character |
| V8 | 160 | 160 | On | SQL-aware |

G-pretrain trong Phase 3 medium được hạ còn 60/80; bảng trên mô tả định nghĩa
variant ở cấu hình full.

### Kết quả trung bình trên tám cell

| Variant | SQL structure | Garbage | Unique | Dominant share | Input overlap | Δ attack recall | Median adv epoch | Stop reason |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| V1 | 0,060 | 0,940 | 0,975 | 0,015 | 0,000 | +0,040 | 3,5 | 8 vanishing |
| V2 | 0,603 | 0,397 | 0,981 | 0,011 | 0,000 | +0,104 | 3 | 8 vanishing |
| V3 | 0,845 | 0,155 | 0,505 | 0,111 | 0,357 | +0,048 | 35,5 | 4 completed, 4 vanishing |
| V4 | 0,397 | 0,603 | 0,955 | 0,035 | 0,000 | +0,058 | 3 | 8 vanishing |
| V5 | 0,797 | 0,203 | 0,992 | 0,005 | 0,001 | +0,076 | 3 | 8 vanishing |
| V6 | 0,317 | 0,683 | 0,987 | 0,011 | 0,000 | +0,025 | 3 | 8 vanishing |
| V7 | 0,433 | 0,567 | 0,780 | 0,165 | 0,000 | +0,043 | 6 | 2 completed, 6 vanishing |
| V8 | 0,849 | 0,151 | 0,990 | 0,007 | 0,000 | +0,079 | 3 | 8 vanishing |

### Điều gì dẫn đến V8 làm anchor?

Trong dữ liệu medium:

- V8 có SQL structure cao nhất nhóm (0,849, gần V3 0,845);
- V8 giữ unique 0,990, trong khi V3 chỉ 0,505;
- dominant share của V8 thấp 0,007;
- input overlap gần 0;
- RF attack-recall tăng trung bình +0,079.

V5 cũng là candidate cân bằng với unique 0,992 và structure 0,797. V3 mạnh về
structure nhưng overlap/diversity kém hơn. V1 có novelty cao nhưng 94% garbage,
nên không phù hợp làm winner chỉ vì unique cao.

V8 vì vậy được dùng làm **anchor** cho refinement. Tuy nhiên toàn bộ tám V8 run
dừng vì `vanishing_reward` sau median 3 epoch adversarial. Kết quả tốt của
snapshot cuối không xóa vấn đề stability.

### Cảnh báo về `selected_variant = V1`

Các bundle baseline Final có file `selected_seqgan_variant.json` ghi V1, nhưng
file tự ghi chú:

```text
Placeholder để final_matrix() chạy được; file này KHÔNG chạy seqgan_improved.
```

Đây không phải kết quả ranking Phase 3. Không được trích V1 là variant thắng.
Không tìm thấy artifact ranking chính thức khép kín trên đủ năm nhóm metric.
Refinement dùng V8 anchor và local champion theo thiết kế bổ sung, không dùng
placeholder V1.

---

## 9. Final/full baselines — 96 run

### Mục đích

Tạo baseline full để so sánh với SeqGAN Improved trong cùng tám cell và ba mức
mất cân bằng chính:

```text
4 method × 8 cell × 3 ratio = 96 run
```

### Cấu hình full

| Method | Cấu hình |
|---|---|
| SMOTE | 2.000 payload, `k=5` |
| GAN | 2.000 payload, 100 epoch, batch 64 |
| CTGAN | 2.000 payload, 300 epoch, batch 500 |
| SeqGAN Master | 2.000 payload, G-pretrain 120, adversarial tối đa 200, rollout 16 |

### Kết quả theo method và ratio

| Method | Ratio | SQL structure | Garbage | Unique | Input overlap | Δ macro-F1 | Δ attack recall |
|---|---:|---:|---:|---:|---:|---:|---:|
| CTGAN | R100 | 1,000 | 0,000 | 0,062 | 1,000 | +0,001 | +0,002 |
| CTGAN | R200 | 1,000 | 0,000 | 0,035 | 1,000 | +0,002 | +0,006 |
| CTGAN | R500 | 1,000 | 0,000 | 0,015 | 1,000 | +0,024 | +0,059 |
| GAN | R100 | 1,000 | 0,000 | 0,007 | 1,000 | +0,002 | +0,006 |
| GAN | R200 | 1,000 | 0,000 | 0,004 | 1,000 | +0,005 | +0,015 |
| GAN | R500 | 1,000 | 0,000 | 0,003 | 1,000 | −0,026 | −0,051 |
| SeqGAN Master | R100 | 0,383 | 0,617 | 0,288 | 0,000 | +0,014 | +0,045 |
| SeqGAN Master | R200 | 0,320 | 0,680 | 0,452 | 0,000 | +0,014 | +0,046 |
| SeqGAN Master | R500 | 0,002 | 0,998 | 0,699 | 0,000 | −0,016 | −0,032 |
| SMOTE | R100 | 0,999 | 0,001 | 0,077 | 1,000 | +0,001 | +0,004 |
| SMOTE | R200 | 0,999 | 0,001 | 0,038 | 1,000 | +0,004 | +0,012 |
| SMOTE | R500 | 0,997 | 0,003 | 0,015 | 1,000 | +0,024 | +0,061 |

### Diễn giải

- CTGAN/GAN/SMOTE giữ SQL structure gần 1 vì output là retrieval payload thật,
  nhưng novelty giảm mạnh khi ratio tăng.
- GAN collapse nặng nhất: unique trung bình chỉ 0,004 trên 24 run.
- SMOTE/CTGAN tại R500 vẫn tăng RF recall, dù unique chỉ khoảng 0,015.
- SeqGAN Master có overlap 0 và novelty cao hơn, nhưng garbage trung bình 0,765.
- Ở R500, SeqGAN Master đạt unique 0,699 nhưng SQL structure chỉ 0,002; đây là
  ví dụ rõ rằng novelty cao không đồng nghĩa payload tốt.
- SeqGAN Master: 10/24 run dừng `vanishing_reward`; 14/24 run completed.

### Quyết định

Không có một baseline thắng trên mọi trục:

- retrieval methods mạnh về structure nhưng yếu về novelty;
- SeqGAN Master sinh trực tiếp và mới hơn nhưng stability/structure yếu;
- Final comparison phải giữ riêng structure, novelty/diversity, stability và RF,
  không cộng thành một “điểm tổng” duy nhất.

---

## 10. Final/full SeqGAN Improved refinement — 33 run

### Đây là campaign gì?

Đây là targeted refinement độc lập, không phải Phase 3 lần hai:

```text
11 (family, scenario, variant) × 3 ratio = 33 run
```

- R100, R200, R500;
- 2.000 payload/run;
- adversarial tối đa 200;
- rollout 16;
- G-pretrain 120 hoặc 160;
- 20 run hoàn tất trong lượt đầu, 13 run còn lại được phục hồi bằng B6X.

### 11 target và vai trò

| Family/scenario/variant | Vai trò |
|---|---|
| `boolean/D/V8` | Anchor |
| `boolean/D/V7` | Local champion boolean/D |
| `boolean/E/V2` | Local champion boolean/E |
| `error/D/V4` | Local champion error/D |
| `error/B/V8` | Local champion đồng thời là anchor |
| `error/D/V8` | Anchor |
| `time/A/V8` | Anchor đồng thời là local champion |
| `time/D/V8` | Anchor đồng thời là local champion |
| `union/D/V8` | Anchor |
| `union/D/V2` | Local champion union/D |
| `union/F/V3` | Local champion union/F |

### Kết quả theo ratio

| Ratio | Run | SQL structure | Garbage | Unique | Dominant | Δ macro-F1 | Δ attack recall | Median adv epoch | Stop reason |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| R100 | 11 | 0,808 | 0,192 | 0,698 | 0,194 | +0,021 | +0,067 | 11 | 4 completed, 7 vanishing |
| R200 | 11 | 0,865 | 0,135 | 0,785 | 0,109 | +0,024 | +0,081 | 3 | 2 completed, 9 vanishing |
| R500 | 11 | 0,790 | 0,210 | 0,772 | 0,122 | +0,041 | +0,111 | 200 | 11 completed |

R200 có cân bằng trung bình tốt nhất giữa structure và garbage. R500 có RF
delta lớn nhất và toàn bộ run completed, nhưng không được quy nguyên nhân chỉ
cho ratio vì profile chạy bị confound với B6X.

### Kết quả trung bình của từng target qua ba ratio

| Target | SQL structure | Garbage | Unique | Dominant | Δ attack recall | Median adv epoch | Stop reason |
|---|---:|---:|---:|---:|---:|---:|---|
| `boolean/D/V7` | 0,911 | 0,089 | 0,864 | 0,035 | +0,217 | 11 | 1 completed, 2 vanishing |
| `boolean/D/V8` | 0,865 | 0,135 | 0,840 | 0,020 | +0,172 | 3 | 1 completed, 2 vanishing |
| `boolean/E/V2` | 0,645 | 0,355 | 0,934 | 0,010 | +0,048 | 200 | 2 completed, 1 vanishing |
| `error/B/V8` | 0,933 | 0,067 | 0,829 | 0,024 | +0,048 | 8 | 1 completed, 2 vanishing |
| `error/D/V4` | 0,532 | 0,468 | 1,000 | 0,001 | +0,084 | 3 | 1 completed, 2 vanishing |
| `error/D/V8` | 0,886 | 0,114 | 0,572 | 0,340 | +0,085 | 3 | 1 completed, 2 vanishing |
| `time/A/V8` | 0,862 | 0,138 | 0,684 | 0,088 | +0,060 | 6 | 1 completed, 2 vanishing |
| `time/D/V8` | 0,971 | 0,029 | 0,664 | 0,333 | +0,071 | 200 | 2 completed, 1 vanishing |
| `union/D/V2` | 0,717 | 0,283 | 0,880 | 0,024 | +0,068 | 200 | 3 completed |
| `union/D/V8` | 0,997 | 0,003 | 0,675 | 0,023 | +0,099 | 80 | 1 completed, 2 vanishing |
| `union/F/V3` | 0,711 | 0,289 | 0,327 | 0,661 | −0,004 | 200 | 3 completed |

### Điều gì có thể rút ra?

- `union/D/V8` mạnh nhất về structure (0,997) và giữ dominant thấp.
- `time/D/V8` và `error/B/V8` cũng có structure cao.
- `boolean/D/V7` cân bằng hơn `boolean/D/V8` trên trung bình ba ratio và có RF
  recall delta lớn nhất (+0,217).
- `error/D/V4` đạt unique 1,0 nhưng structure chỉ 0,532: novelty cao chưa đủ.
- `error/D/V8` và `time/D/V8` có dominant share cao, cần đọc theo từng ratio để
  xác định collapse tập trung ở đâu.
- `union/F/V3` có unique thấp 0,327, dominant 0,661 và RF delta âm; đây là target
  yếu rõ rệt dù hoàn thành đủ epoch.
- V8 là anchor hợp lý về cấu trúc, nhưng local champion vẫn cần thiết; không có
  một variant duy nhất thắng mọi family/scenario.

### 13 B6X và confound cần ghi nhớ

Lượt đầu hoàn tất 20 run; Colab ngắt 13 run còn lại. B6X:

- dùng batch 384 thay vì 64;
- giữ cấu hình full còn lại;
- resume/hoàn tất đến epoch tổng hợp 200;
- có checkpoint bền vững trong `_recovery_checkpoints`;
- được phân loại là `full_resume_b6x`, không phải Phase 2B.

Phân bố B6X không đều:

| Ratio | Run gốc hoàn tất | B6X |
|---|---:|---:|
| R100 | 8 | 3 |
| R200 | 10 | 1 |
| R500 | 2 | 9 |

Vì 9/11 run R500 là B6X, khác biệt giữa R500 và R100/R200 đồng thời chứa hiệu
ứng của ratio, batch size, resume và thời lượng thực tế. Không được kết luận
“R500 giúp SeqGAN hội tụ 200 epoch” nếu chưa có rerun đối chứng cùng batch.

So sánh mô tả theo profile:

| Profile | Run | SQL structure | Garbage | Unique | Δ attack recall | Median adv epoch |
|---|---:|---:|---:|---:|---:|---:|
| Full gốc | 20 | 0,840 | 0,160 | 0,744 | +0,091 | 4,5 |
| Full resume B6X | 13 | 0,791 | 0,209 | 0,764 | +0,078 | 200 |

Hai hàng này không phải thí nghiệm A/B ngẫu nhiên vì thành phần target/ratio khác
nhau.

---

## 11. Bảng truy vết quyết định

| Bước | Bằng chứng thực tế | Quyết định | Mức độ |
|---|---|---|---|
| Phase 1 | Bốn survey run; threshold artifact từ 1 SeqGAN Master run | Tách gate retrieval/direct, dùng threshold ban đầu | Calibration vận hành |
| Phase 2A | 96 mini run; file top-2 ghi SMOTE+CTGAN Borda | Giữ E/D, D/B, A/D, D/F | Selection vận hành, chưa đủ bốn method |
| Phase 2B | 196/224 run; R10/R20 thiếu capacity | Loại cell không đủ pool | Quyết định dữ liệu chắc chắn |
| Phase 2B | Composite SeqGAN Master | Dùng R200 cho Phase 3 | Bypass gate chính thức |
| Phase 3 | 64 medium run | V8 làm anchor, giữ local champion | Thiết kế refinement, không phải winner chính thức |
| Final baseline | 96 full run | So sánh tách biệt structure/novelty/stability/RF | Kết quả full |
| Refinement | 20 full gốc + 13 B6X | Hoàn tất grid 33 run | Full nhưng có confound B6X |

## 12. Kết luận được phép và không được phép

### Có thể kết luận

- Retrieval baselines giữ cấu trúc SQL tốt nhưng novelty thấp và overlap cao.
- SeqGAN Master có novelty trực tiếp nhưng chất lượng cấu trúc suy giảm mạnh khi
  ratio cực lệch.
- Trong Phase 3 medium, V8/V5 cho cân bằng structure–diversity tốt hơn V1/V4/V6.
- Trong full refinement, hiệu quả phụ thuộc family/scenario; V8 không thống trị
  tuyệt đối.
- `vanishing_reward` là vấn đề stability phổ biến của SeqGAN, đặc biệt ở
  Phase 3 medium và 20 run full gốc.
- R500 là stress region; kết quả refinement R500 bị confound mạnh bởi B6X.

### Không được kết luận

- SQL parse/structure cao không chứng minh khai thác SQLi thành công.
- HTTP/WAF bypass, nếu được đánh giá ở campaign khác, không chứng minh DBMS đã
  bị khai thác.
- Unique cao không chứng minh payload hữu ích.
- V1 không phải winner; file V1 chỉ là placeholder.
- R200 chưa thắng gate chính thức đủ bốn method.
- B6X không phải Phase 2B và không phải phương pháp khoa học mới.
- Không được so trực tiếp metric mini/medium với full như cùng ngân sách.

## 13. Cấu trúc thư mục và truy vết

```text
final_result/
├── phase1_survey/
├── phase2a_scenario_search/
├── phase2b_ratio_search_medium/
├── phase3_seqgan_improved_test_medium/
├── final_full/
│   ├── baselines/
│   └── seqgan_improved_refinement/
├── _index/
└── _provenance/
```

Các file chỉ mục:

- [`_index/run_index.csv`](_index/run_index.csv): 489 run, campaign, profile,
  nguồn và đường dẫn đích;
- [`_index/artifact_inventory.csv`](_index/artifact_inventory.csv): SHA-256,
  kích thước và nguồn từng artifact;
- [`_index/cross_campaign_overlaps.csv`](_index/cross_campaign_overlaps.csv):
  các scientific ID giống nhau nhưng thuộc campaign khác nhau;
- [`_index/summary.json`](_index/summary.json): tổng kiểm kê;
- [`_BUILD_COMPLETE.json`](_BUILD_COMPLETE.json): xác nhận build hoàn tất.

Nguồn notebook/README dùng để giải thích campaign nằm trong
`_provenance/source_definitions/`. Manifest lịch sử của refinement/B6X được giữ
trong `_provenance` của từng run; `run_manifest.json` ở cấp run là manifest
canonical theo campaign.

Artifact quyết định gốc đã được chép vào `_provenance/decision_artifacts/`:

- [`phase1_validity_thresholds_seqgan_branch.json`](_provenance/decision_artifacts/phase1_validity_thresholds_seqgan_branch.json);
- [`phase2a_top2_scenarios_operational.csv`](_provenance/decision_artifacts/phase2a_top2_scenarios_operational.csv);
- [`phase2b_selected_global_ratio_operational.json`](_provenance/decision_artifacts/phase2b_selected_global_ratio_operational.json);
- [`phase3_selected_variant_PLACEHOLDER.json`](_provenance/decision_artifacts/phase3_selected_variant_PLACEHOLDER.json).

## 14. Khuyến nghị nếu tiếp tục nghiên cứu

1. Chạy lại formal Phase 2A Borda trên đủ bốn method nếu cần tuyên bố top-2 chính
   thức.
2. Chạy `select-ratio` đúng gate trên đủ 8 cell × 4 method; không dùng file R200
   bypass làm kết luận cuối.
3. Xây ranking Phase 3 chính thức trên năm nhóm ngang nhau: SQL structure,
   novelty, diversity, stability, RF.
4. Rerun đối chứng một subset R100/R200/R500 với cùng batch 384 hoặc cùng batch
   64 để tách hiệu ứng ratio khỏi B6X.
5. Báo cáo đồng thời planned epoch, actual epoch và stop reason.
6. Với payload ứng viên tốt, đánh giá WAF/DBMS trong môi trường được phép; không
   suy diễn exploit success từ metric offline.

---

README này mô tả dữ liệu hiện có, không sửa metric gốc và không biến quyết định
vận hành thành kết luận mạnh hơn bằng chứng cho phép.
