# Phân vùng kết quả WAF

Các thư mục `phase1_pilot_*` là artifact lịch sử/chẩn đoán của chiến dịch pilot
6.500 payload và 13.000 probe. Tên thư mục lịch sử có chữ `canonical` chỉ nói
đến cách tổng hợp pilot ở thời điểm tạo; nó không phải nguồn canonical cho các
bảng WAF trong luận văn cuối.

Nguồn của Bảng 3.19–3.21 và Hình 3.12 là chiến dịch `campaign/full`:

- 413.700 payload;
- 827.400 probe dự kiến;
- 825.899 yêu cầu hợp lệ đã gửi;
- 1.501 GET không gửi do đường dẫn dài;
- 585.661 yêu cầu bị chặn và 240.238 yêu cầu không bị WAF chặn.

Các trường `bypass` và `bypass_rate` trong artifact lịch sử là alias của
`not_blocked` và `waf_not_blocked_rate`; chúng không chứng minh khai thác DBMS.
