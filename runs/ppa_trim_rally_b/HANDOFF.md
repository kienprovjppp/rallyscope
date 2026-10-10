# Rally B · PPA Chicago Cup — trạng thái phiên làm việc

**Trang tương tác (riêng tư):** https://claude.ai/artifact/5ewsNu7BQSqZeeTtQZLNvM
**Video nguồn:** GitHub Release `rally-video`, file `PPA.-.Trim.mp4`. Rally B nằm ở đoạn 0:38.21 đến 0:58.41 (20,2 giây).

## Đã xong

| Bước | Kết quả | File |
|---|---|---|
| 1. Chuẩn bị | Cắt rally B. Camera đứng yên (lệch < 0,1 px). Video gốc 29,97 fps: đo trên frame gốc rồi nội suy lên 60 fps | `page/rally.mp4`, `page/rally.webm` |
| 4. Sân | 4 góc fit từ vạch trắng; kitchen, đường giữa và lưới khớp ảnh | `court.json`, `checks/court_check_crop.png` |
| 3. Bóng | Dò ứng viên + beam search: 437/606 frame, không đoạn nào bị kẹt | `ball_raw.json`, `ball_nat.json` |
| 5. Người chơi | 4 khung xương, gán theo màu áo + bên sân, quét lưới khi mất dấu, bước refine lấp khoảng trống: P1 97%, P2 95%, P3 100%, P4 100% | `pose.npz`, `checks/pose_check.jpg` |
| 2 + 6. Cú đánh | 46 ứng viên (tiếng + bóng đổi hướng), 8 agent kiểm chứng trên ảnh, 16 cú đánh + 13 lần nảy | `strikes_nat.json`, `strike_verification.json` |
| 7. Điểm | P1 83 · P2 73 · P4 62 · P3 62 | `prep.json` |
| 8. Trang | Lớp phủ, bảng bên phải, timeline, thẻ báo cáo cuối, báo cáo viết tiếng Việt | `page/`, `texts.json` |

## Đang làm dở: nút tải video lên + nút bật/tắt lớp phủ (CHƯA TEST XONG)

Đã có trong `rallyscope/template/index.html`. Trang công khai (link ở trên) **vẫn là bản 1** và chưa có hai tính năng này.

- **Bật/tắt lớp phủ**: 4 nút (Khung xương, Đường bóng, Bảng tên, Mặt sân) và nút Tắt hết / Bật hết; lựa chọn được nhớ trong trình duyệt. Đã chụp màn hình thấy nút hiện đúng, nhưng chưa bấm thử từng nút.
- **Tải video lên** (phân tích ngay trong trình duyệt, video không gửi đi đâu): mở video, dựng ảnh nền, tự tìm sân, màn hình kiểm tra 4 góc sân và chọn đoạn (Từ/Đến), tải MediaPipe, tìm 4 người, theo dõi người + bóng từng frame (có xem trước trực tiếp), tiếng vợt, cú đánh, nảy, tốc độ, điểm, nhận xét tự động. Có thêm nút "Viết lại nhận xét bằng Claude" (capability `sample`).
- **Đã kiểm tra** (Chromium headless, clip 9 giây của rally B dạng webm): trang mẫu vẫn chạy, tự tìm sân đúng 4 góc, 4 khung xương bám đúng người trong màn hình xem trước. Test dừng ở 76% bước theo dõi theo yêu cầu.
- **Chưa kiểm tra**: phần sau bước theo dõi (ghép đường bóng, phát hiện cú đánh tự động, chấm điểm, nạp kết quả vào màn hình), nút "Viết lại nhận xét bằng Claude", nút "Xem rally mẫu", trình duyệt thật có GPU, video H.264.

### Việc còn lại theo thứ tự

1. Chạy lại test đầy đủ: `node rallyscope/tests/upload_test.mjs <site> test9.webm out` (cách dựng thư mục `site` ghi ở đầu file), đọc `out_summary.json` và các ảnh `out_t*.png`, sửa lỗi nếu có.
2. So kết quả tự động với 16 cú đã kiểm chứng của rally B (`strikes_nat.json`) để biết độ chính xác của bước phát hiện cú đánh tự động.
3. Bấm thử từng nút lớp phủ và nút "Xem rally mẫu".
4. Đăng lại Artifact cùng link: bỏ thẻ skeleton, gửi kèm `mp/pose_model.wasm`, `mp/vision_wasm_internal.wasm` và khai báo `capabilities: {sample: {}}` (xem `CLAUDE.md`).
5. Nhờ Kien thử trên Chrome/Edge máy Legion với một video MP4 thật.

## Chưa làm (dừng theo yêu cầu)

1. **Quay video MP4 60 fps** (bước 8):
   ```bash
   node rallyscope/scripts/record.mjs rallyscope/runs/ppa_trim_rally_b/page out.mp4
   ffmpeg -i out.mp4 -i <rally B cắt từ video gốc, có tiếng> -filter_complex "[1:a]apad[a]" -map 0:v -map "[a]" -c:v copy -c:a aac -shortest final.mp4
   ```
2. **Kiểm tra bước 9 đầy đủ**: chụp màn hình lúc giao bóng, một cú phía xa, một cú phía gần, cú cuối và thẻ báo cáo (`node rallyscope/scripts/shots.mjs <page> qa 0.9 6.1 9.2 17.7 end+4`), rồi so 3 frame của MP4 với trang.

## Những điều cần biết khi làm tiếp

- Tiếng trong bản phát sóng trễ hình khoảng 2–3 frame, nên thời điểm chạm bóng được đọc từ hình.
- Bóng trong video không có viền tối, nên `ball_viterbi.py cands` chạy với `--chan yellow` (độ vàng của bóng).
- Hệ số chiều cao người theo phối cảnh của camera này là `--kh 0.25` (quy trình gốc dùng 0.42 cho camera khác).
- P2 mất khung xương khoảng 1 giây khi lao người (frame gốc 260–284). Trang hiển thị là "POSE LOST".
- Vị trí 5 lần nảy bị che được ước lượng từ đường bay (các mục dạng `[frame, x, y]` trong `strikes_nat.json`).

## Chạy lại từ dữ liệu đã lưu

```bash
python rallyscope/scripts/resample.py ball_nat.json pose.npz strikes_nat.json --src-fps 29.97 --frames 1212 --out-dir .
python rallyscope/scripts/prep.py court.json ball60.json strikes60.json pose60.npz prep.json --end 1101
python rallyscope/scripts/finalize.py build prep.json texts.json page/data.json --video page/rally.mp4
```
