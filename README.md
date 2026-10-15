# RallyScope

Biến một rally pickleball (camera cố định, thấy cả sân) thành video phân tích và một trang tương tác. Trong đó có khung xương phát sáng cho 4 người chơi, vệt sáng của bóng, thời điểm và tốc độ từng cú đánh, cùng bảng điểm cho biết ai đánh chuyên nghiệp nhất và mỗi người cần sửa gì.

Mọi con số đều đo từ video. P1 đến P4 được đặt theo vị trí trên màn hình: P1 gần bên phải, P2 gần bên trái, P3 xa bên trái, P4 xa bên phải.

## Mở trang và tải video

Trong thư mục repo, chạy `node scripts/serve.mjs`, giữ cửa sổ lệnh đang chạy rồi mở **http://127.0.0.1:8000/**. Nếu cổng đã dùng, chạy `node scripts/serve.mjs 8001` và mở cổng được in ra. Server chỉ lắng nghe trên máy này và phục vụ các tài nguyên của trang; video người dùng chọn vẫn được phân tích trong trình duyệt.

Không mở trực tiếp `C:/.../template/index.html`: trình duyệt không cho trang `file://` tải các file AI bằng `fetch`, gây lỗi “Failed to fetch”. Lệnh trên phục vụ template, rally mẫu và thư mục `mp/` cùng một địa chỉ, không cần chép sang `site/`.

Trang công khai chạy trên GitHub Pages: mỗi lần push lên `main`, `.github/workflows/pages.yml` chạy `node scripts/build_site.mjs _site` (chép đúng các file `serve.mjs` phục vụ) rồi đăng thư mục đó. Cũng có thể đem `_site/` lên bất kỳ host tĩnh nào. Nút "Viết lại nhận xét bằng Claude" chỉ hiện khi trang chạy trong Claude Artifact.

Thư viện AI đã được đóng gói trong `mp/` (MediaPipe 0.10.21), không cần CDN. Nếu tự dựng thư mục trang, chép **toàn bộ `mp/`** gồm mô hình, runtime WASM, `vision_bundle.mjs`, `wasm/vision_wasm_internal.js` và thông tin giấy phép. Không chỉ chép hai file WASM. Khi triển khai dưới một đường dẫn con, đặt thư mục `mp/` cạnh `index.html`.

## Cài đặt

```bash
python3.12 -m venv rs_env
rs_env/bin/pip install mediapipe==0.10.21 opencv-python numpy scipy
curl -L -o pose_landmarker_heavy.task https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_heavy/float16/latest/pose_landmarker_heavy.task
npm i -g playwright   # cần thêm Chrome hoặc Chromium
```

## Các bước (W = thư mục làm việc)

```bash
# 1. Chuẩn bị video: chuyển sang 60 fps cố định, tách âm thanh mono
ffmpeg -i rally.mp4 -an -vf fps=60 -c:v libx264 -crf 16 -g 30 W/work60.mp4
ffmpeg -i rally.mp4 -vn -ac 1 -ar 48000 W/audio.wav

# 2. Lấy thời điểm cú đánh từ tiếng vợt
python scripts/audio_hits.py W/audio.wav W/audio_hits.json

# 3–4. Ảnh nền tĩnh, góc sân, phép đổi từ pixel sang mét (luôn mở ảnh check ra xem)
python scripts/court.py bg W/work60.mp4 W/bg.png
python scripts/court.py detect W/bg.png W/court.json          # hoặc --corners "x,y x,y x,y x,y"
python scripts/court.py check W/bg.png W/court.json W/court_check.png

# 3. Dò bóng: đo viền tối của bóng ở 2 vị trí đã biết, lấy ứng viên, rồi giải cả đường bay một lần
python scripts/ball_viterbi.py profile W/work60.mp4 --known "f,x,y f,x,y"
python scripts/ball_viterbi.py cands W/work60.mp4 W/bg.png W/cands.npz --court W/court.json --rim "y1:r1,y2:r2"
python scripts/ball_viterbi.py solve W/cands.npz W/ball_raw.json

# 5. Khung xương cho 4 người (seed = tâm hông ở frame 0, theo thứ tự P1..P4)
python scripts/pose_track.py track W/work60.mp4 W/court.json W/pose.npz --seeds "x,y x,y x,y x,y" --model pose_landmarker_heavy.task
python scripts/pose_track.py check W/work60.mp4 W/pose.npz W/pose_check.jpg

# 2 + 6. Chốt cú đánh (âm thanh + bóng đổi chiều + bóng ở gần tay), làm mượt bóng theo từng đoạn
python scripts/strikes.py merge W/audio_hits.json W/ball_raw.json W/pose.npz W/court.json W/strikes.json
python scripts/ball_viterbi.py smooth W/ball_raw.json W/strikes.json W/ball.json
python scripts/ball_viterbi.py check W/work60.mp4 W/ball.json W/ball_check.jpg

# 6–7. Cú đánh, nảy bóng, tốc độ, điểm số
python scripts/prep.py W/court.json W/ball.json W/strikes.json W/pose.npz W/prep.json

# 8. Viết nhận xét (sau khi đọc số liệu), dựng trang rồi quay video
python scripts/finalize.py draft W/prep.json W/texts.json      # rồi tự viết lại toàn bộ câu chữ
python scripts/finalize.py build W/prep.json W/texts.json page/data.json --video page/rally.mp4
node scripts/record.mjs page out.mp4
ffmpeg -i out.mp4 -i rally.mp4 -filter_complex "[1:a]apad[a]" -map 0:v -map "[a]" -c:v copy -c:a aac -shortest final.mp4
```

Thư mục `page/` gồm `index.html` (chép từ `template/`), `data.json`, `rally.mp4` (H.264), `rally.webm` (VP9, dành cho Chromium không có H.264) và toàn bộ `mp/` nếu dùng nút tải video lên. Mở trang qua một web server, ví dụ `python -m http.server` trong thư mục `page/`, không mở bằng cách double-click.

Bộ theo dõi chỉ xuất tối đa một vị trí bóng mỗi frame. Trước khi chọn quỹ đạo, Python và trang tải video loại các điểm gần như đứng yên trong ít nhất 80% cửa sổ khoảng 0,4 giây (bán kính ở chiều rộng 1920: Python 3 pixel, trình duyệt 8 pixel). Trình duyệt còn lọc hình dạng, tương phản và đoạn quỹ đạo ngắn/ít dịch chuyển để giảm nhiễu LED và giày. Vùng nền có màu bóng tăng ngưỡng thay đổi màu, thay vì che tuyệt đối bóng đi ngang qua. Cách này dành cho camera cố định; bóng đứng yên lâu, bị nhòe hoặc vật khác cùng màu đang di chuyển vẫn có thể gây mất dấu/nhận nhầm. Vùng tìm bóng có khoảng đệm quanh và phía trên sân để giữ bóng bay cao. Python tự đọc `court.json` cạnh ảnh nền nếu có; dùng `--court` để chỉ định rõ. Chạy lại bước `cands` và `solve`, hoặc tải video lên lại, để áp dụng bộ lọc mới cho kết quả cũ.

Luồng tải video yêu cầu tìm đủ bốn người trước khi chạy. Khởi tạo và tìm lại người đều kiểm tra vị trí theo sân, độ tin cậy chân và kích thước cơ thể; vẫn có khoảng đệm cho người giao bóng ngoài baseline. Màu áo/quần giúp giữ ID khi đồng đội che nhau. Tự dò sân chỉ đề xuất góc khi có bằng chứng cả hai vạch kitchen. Khi cần kéo tay, đặt hai góc xa tại **baseline xa**, tránh đặt ở chân lưới; kiểm tra cả vạch kitchen và lưới dự kiến trùng ảnh. Đây là hiệu chỉnh thuật toán, không huấn luyện lại mô hình.

Kiểm thử: `node --test tests/court_tracking_test.mjs`, `node tests/ball_tracking_test.mjs` và `python -m unittest discover -s tests -p test_ball_tracking.py` (cần NumPy, OpenCV, SciPy). Trên Windows có Playwright cài toàn cục, thêm `--browser` vào lệnh test bóng để kiểm tra trong Chromium.

Kiểm thử toàn bộ upload: `node tests/upload_test.mjs <site> <clip.webm> <out-prefix> [court.json]`. File góc tùy chọn có dạng `{width, height, corners}`, thứ tự xa trái → xa phải → gần phải → gần trái; test kéo từ vị trí chấm đang hiển thị và kiểm tra tọa độ sau từng lần kéo. `tests/fixtures/vietnam_court.json` chỉ dành cho video Việt Nam–Australia 1920×1080 trong lần kiểm chứng này. Có thể đặt `PLAYWRIGHT_MODULE` tới thư mục Playwright đã cài, `BROWSER_CHANNEL=chrome` và `BROWSER_GPU=1` để dùng Chrome/GPU thật. Cách chuẩn bị thư mục site ghi ở đầu file test. Xem phạm vi và giới hạn kiểm chứng tại [tests/TRACKING_VALIDATION.md](tests/TRACKING_VALIDATION.md).

Test đường dẫn và lỗi tải AI: `node --test tests/runtime_loading_test.mjs tests/serve_test.mjs`. Upload test dùng đường dẫn mặc định và chặn CDN; đặt `RALLYSCOPE_URL=http://127.0.0.1:8000/` để kiểm tra trực tiếp launcher đang chạy.

## Cách chấm điểm

Tổng = vị trí 35% + cú đánh 25% + tư thế 20% + di chuyển 20%.

- **Vị trí:** khoảng cách trung bình đứng sau vạch kitchen, tính từ lúc luật cho phép lên lưới (đội nhận giao tính từ cú trả giao, đội giao tính từ cú thứ ba). Cách 0.6 m được 100 điểm, mỗi mét xa hơn trừ 20.
- **Cú đánh:** đối thủ phải đỡ bóng ở xa lưới đến đâu (2.5 m được 0, 6.5 m được 100, trọng số 0.65) và bị kéo ngang bao xa (2 m được 100, trọng số 0.35).
- **Tư thế:** góc gối trung vị (178° được 0, mỗi độ thấp hơn cộng 5, trọng số 0.6) và cổ tay cao hơn hông bao nhiêu lần chiều dài thân (0.625 được 100, trọng số 0.4).
- **Di chuyển:** số mét tiến về vạch kitchen trong 60 frame sau cú đánh của chính mình (1.5 m được 100, trọng số 0.5) và tốc độ trung bình cả rally (1.3 m/s được 100, trọng số 0.5).
