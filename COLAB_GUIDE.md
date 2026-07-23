# Chạy GAN for SQLi trên Google Colab từ VS Code

Notebook điều khiển nằm tại `GAN_SQLi_Colab.ipynb`. Cấu hình nghiên cứu gốc không bị thay đổi; `configs/colab_smoke_config.yaml` chỉ dùng để kiểm tra nhanh việc triển khai.

## Chuẩn bị một lần

1. Cài extension VS Code `google.colab` và mở thư mục project này.
2. Mở `GAN_SQLi_Colab.ipynb`, chọn `Select Kernel > Colab > New Colab Server`, rồi chọn runtime GPU.
3. Trong VS Code Explorer, nhấp phải thư mục `GAN_for_SQLi`, chọn `Upload to Colab`.
4. Chạy notebook từ trên xuống. Khi được hỏi, cấp quyền mount Google Drive cho đúng tài khoản Colab Pro+.

Thư mục upload phải xuất hiện tại `/content/GAN_for_SQLi`. Nếu extension tạo tên khác, sửa biến `PROJECT_DIR` trong notebook.

## Nơi lưu bền vững

Notebook tạo hai cấu hình runtime ở `/content/colab_configs`:

- Smoke test ghi vào `/content/drive/MyDrive/GAN_SQLi_Colab/results_smoke`.
- Chạy thật ghi vào `/content/drive/MyDrive/GAN_SQLi_Colab/results`.

Code và dependency được đặt trên ổ nhanh `/content`; artifact được ghi thẳng vào Drive. Sau khi Colab ngắt, upload lại project, mount Drive, tạo lại runtime config và dùng `--resume`.

## Trình tự an toàn

1. Kiểm tra GPU và cài dependency.
2. Chạy unit test.
3. Chạy một GAN smoke test 2 epoch.
4. Chạy Phase 1 bằng cấu hình nghiên cứu thật và calibrate threshold.
5. Không chạy Phase 2A cho đến khi chốt cách xử lý blocker tỷ lệ `1:20` đã ghi trong README.

Không dùng runtime Colab cho Docker/WAF. Phần WAF cần Docker daemon và phù hợp hơn khi chạy trên máy local hoặc VM riêng.
