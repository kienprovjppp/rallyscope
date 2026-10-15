# Kiểm chứng luồng tải video · 2026-10-15

Nguồn: `VIETNAM vs AUSTRALIA - The World Cup Battle (1m26-2m26, khong tieng).mp4`, 1920×1080, 60 fps, 60 giây, không tiếng. Góc đo tại kích thước phân tích 1280×720 nằm trong `fixtures/vietnam_court.json`; không đưa góc riêng của video vào sản phẩm. Mô hình MediaPipe và hai file WASM giữ nguyên.

## Sửa lỗi mở trực tiếp file / tải AI

Sau lần kiểm chứng tracker, người dùng báo “Failed to fetch” khi mở `C:/Users/tamki/rallyscope/template/index.html`. Tái hiện bằng Chrome với `file://`: trang không thể tải tài nguyên AI bằng `fetch`; bản test cũ còn che một vấn đề khác vì đặt URL MediaPipe local thay cho cấu hình CDN của sản phẩm.

- Thêm `node scripts/serve.mjs` để phục vụ template, rally mẫu và AI tại `http://127.0.0.1:8000/`; server chỉ cho đọc các tài nguyên công khai định trước, không mở toàn bộ repo.
- Đóng gói hai file JS nguyên bản của MediaPipe 0.10.21 trong `mp/`, kiểm tra SHA-512 gói npm. Runtime WASM khớp SHA-256 với bản đã có, không thay mô hình hoặc WASM.
- Mở bằng `file://` nay dừng trước khi xử lý video và hướng dẫn mở localhost. Lỗi tải mô hình qua HTTP nêu file thiếu và mã trạng thái.
- Kiểm chứng Chrome đúng đường dẫn `file://` đã thấy thông báo mới, không gọi tải AI. Upload clip Việt Nam 5 giây qua launcher hoàn tất với **cấu hình mặc định, CDN bị chặn, không đặt `__MP_BASE`/`__MP_DIR`**. Cả bốn tài nguyên JS/mô hình/runtime được tải từ `/mp/` cùng origin. Log không có `pageerror`; vẫn có cảnh báo nội bộ MediaPipe.
- Test thêm: `runtime_loading_test.mjs` (đường dẫn mặc định, hướng dẫn file://, lỗi mạng/404); `serve_test.mjs` (tài nguyên, range video, HEAD, chặn file ngoài danh sách và POST).

Bằng chứng bổ sung nằm trong `out_vietnam/local_runtime_*` và `out_vietnam/file_protocol_fixed.png`. Lần này chỉ sửa cách mở/tải tài nguyên, không thay thuật toán tracking; số đo tracker ở dưới giữ nguyên phạm vi kiểm chứng trước đó.

## Lỗi đã tái hiện và sửa

- Test kéo từ góc mặc định khi tự dò đã đổi vị trí; màn giới thiệu còn che thao tác đầu. Test nay đóng màn giới thiệu, đọc bốn tâm chấm thực sự được vẽ, kéo bằng chuột và xác nhận từng tọa độ.
- Nửa sân gần có thể thành một tứ giác hợp lệ. Tự dò nay yêu cầu ít nhất 35% mẫu dọc mỗi vạch kitchen dự kiến khớp vạch ảnh, trong khoảng dung sai theo độ phân giải. Video Việt Nam yêu cầu hiệu chỉnh tay; sân rally B vẫn được tự dò.
- Khung xương gần bị cắt chân có confidence chân 0,479/0,437 vẫn được khởi tạo thành người xa. Khởi tạo nay yêu cầu cả hai chân ≥0,55; tiếp tục track dùng ≥0,4.
- So màu chỉ giữa hai đội không chặn đổi ID đồng đội. Nay so cả bốn người, lấy màu áo và phần trên quần/váy, giảm ảnh hưởng độ sáng. Test gồm đồng đội cùng áo, mất dấu, đổi chỗ và áo đỏ đổi độ sáng.
- Che nền quanh bảng màu bóng làm mất bóng thật ở cạnh bảng. Nay tăng ngưỡng thay đổi màu trong vùng này thay vì loại tuyệt đối.
- Giới hạn diện tích 180 pixel quy về chiều rộng 1920 loại một bóng thật 102 pixel ở ảnh 1280×720 tại giây 30. Nâng giới hạn lên 260, vẫn loại mảng LED 12×9 ở ảnh test 960×540.

## Cách chạy

```powershell
node --test tests/court_tracking_test.mjs
node tests/ball_tracking_test.mjs
.venv/Scripts/python.exe -m unittest discover -s tests -p test_ball_tracking.py

$env:PLAYWRIGHT_MODULE = (Resolve-Path out_vietnam/tools/node_modules/playwright).Path
$env:BROWSER_CHANNEL = 'chrome'
$env:BROWSER_GPU = '1'
node tests/upload_test.mjs site out_vietnam/vietnam5.webm out_vietnam/vietnam_verified tests/fixtures/vietnam_court.json
node tests/upload_test.mjs site test9.webm out_vietnam/rallyB_verified
```

Trong sandbox Windows, nếu thư mục tạm hệ thống không ghi được, đặt `TEMP` và `TMP` vào một thư mục tạm trong workspace trước khi chạy Python. Python 3.12 và venv có sẵn đã chạy được trong phiên này.

## Kết quả bản cuối

- 17 test người/sân/bóng trong `court_tracking_test.mjs`: qua; các ca mới đã được thấy thất bại trước sửa. `ball_tracking_test.mjs` và 4 test Python cũng qua. `git diff --check` không báo lỗi khoảng trắng.
- Chrome headless, MediaPipe thật, GPU: upload clip Việt Nam 5 giây có hiệu chỉnh tay và rally B 9 giây dùng góc tự dò đều chạy tới kết quả, không có `pageerror`. Log còn cảnh báo của MediaPipe và hai tài nguyên phụ trả 404 trong thư mục site thử; không phải console sạch hoàn toàn.
- Lấy 600 frame tại 10 fps trải 60 giây, 518 frame được bộ lọc cảnh chấp nhận. Số frame có landmark P1–P4: **482, 444, 311, 359**; tổng 815 ứng viên bóng, quỹ đạo chọn 341 frame. Đây là số quan sát, không phải nhãn đúng/sai.
- Đối chiếu bằng mắt 12 ảnh tại 0, 5, 10, 15, 25, 30, 35, 40, 45, 50, 55 và 58,9 giây: không thấy khung xương chuyển sang khán giả hoặc đổi ID trong các khung xương được nhận. Vẫn thiếu nhiều khung xương, nhất là phía xa và lúc ngã/che khuất. Hai ca đổi ID tại 45/55 giây của bản trước không còn trong ảnh cuối.
- Bốn bóng thật đối chiếu tại 10, 25, 30 và 50 giây đều có ứng viên; bản cuối chọn quỹ đạo tại cả bốn mốc. Hai bản lọc trước bỏ bóng cạnh LED ở 25 giây và bóng lớn ở 30 giây. Đây là mẫu kiểm tra lỗi cụ thể, không đại diện độ chính xác toàn video.
- Bảy cú đánh trong 9 giây đầu rally B khớp người đánh với nhãn `strikes_nat.json` khi ghép thời điểm gần nhất. Sai lệch thời điểm tuyệt đối 0,016–0,267 giây; chưa đánh giá đủ 16 cú trong toàn rally hoặc xác minh tốc độ/điểm tự động.

Bằng chứng cuối: `out_vietnam/verified_pass.json`, `verified_prep.json`, `verified_audit_*.png`, `vietnam_verified_summary.json`, `rallyB_verified_summary.json` và các log/ảnh cùng tiền tố. `after_short_pass.json` là kiểm tra phụ 360 frame ở 60 fps, diễn ra trước lần chuẩn hóa màu áo/quần cuối; không dùng làm kết quả giữ ID của bản cuối.

## Giới hạn

Upload hoàn tất chỉ xác nhận luồng mở video → hiệu chỉnh → MediaPipe → xử lý → hiển thị kết quả. Không xác nhận độ chính xác cú đánh, tốc độ hoặc điểm số. Đoạn Việt Nam đầu clip gồm cả chuẩn bị giao; bộ phát hiện cú đánh vẫn có thể nhận nhầm động tác thả/nảy bóng là cú đánh.

Kiểm tra lấy mẫu 10 fps không thay thế kiểm tra đủ 3.600 frame gốc. Frame bị chuyển cảnh/zoom bị bỏ khỏi tracker. Số frame có landmark là độ hiện diện, không phải độ chính xác. Màu đồng phục giống nhau, thay đổi ánh sáng, che khuất và chuyển cảnh vẫn có thể làm mất hoặc đổi ID.

Bóng thật bị nhòe/nhập vào vùng màu khác vẫn có thể bị loại. Tại 4,5 giây, vùng màu quanh bóng và nền/người lân cận rộng 33×17, diện tích 181 pixel ở ảnh 1280×720, vượt ngưỡng mới và có độ đặc thấp. Một quan sát thật đơn lẻ tại 5,5 giây còn có thể bị bộ lọc đoạn ngắn loại. Không suy độ chính xác bóng từ số ứng viên giảm. Cần nhãn theo từng frame trước khi dùng số đo tự động như kết quả đã kiểm chứng.

Các ảnh, landmark, ứng viên và log kiểm tra nằm trong `out_vietnam/` (đã bị gitignore); dữ liệu rally B đã xác minh trong `runs/ppa_trim_rally_b/` không bị ghi đè.
