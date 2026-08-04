# Final result — GAN for SQLi

Đây là thư mục tổng hợp theo **campaign**, không gộp nhầm Phase 3 medium với
SeqGAN Improved full refinement.

## Quy mô

| Campaign | Run |
|---|---:|
| `phase1_survey` | 4 |
| `phase2a_scenario_search` | 96 |
| `phase2b_ratio_search_medium` | 196 |
| `phase3_seqgan_improved_test_medium` | 64 |
| `final_full/baselines` | 96 |
| `final_full/seqgan_improved_refinement` | 33 |
| **Tổng** | **489** |

## Quy tắc

- Phase 3 medium: 64 run, R200, 500 payload, tối đa 60 adversarial epoch.
- Full refinement: 33 run, 11 cấu hình × R100/R200/R500, 2.000 payload,
  tối đa 200 adversarial epoch.
- 13 B6X là phần phục hồi của full refinement, không phải Phase 2B.
- 96 baseline full gồm SMOTE, GAN, CTGAN và SeqGAN Master.
- Mọi nguồn gốc được ghi trong `_index/run_index.csv`.
- SHA-256 của từng artifact được ghi trong `_index/artifact_inventory.csv`.
- 52 checkpoint `.pt` của B6X nằm trong `_recovery_checkpoints` của từng run.
- Manifest nguồn bị gắn phase lịch sử được giữ tại `_provenance`; manifest ở
  thư mục run là manifest canonical theo campaign.
- Không có file nguồn nào bị di chuyển hoặc xóa.
