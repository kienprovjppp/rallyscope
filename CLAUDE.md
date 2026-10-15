# CLAUDE.md

Ghi chú cho Claude khi làm việc trong repo này. Người dùng (Kien) giao tiếp bằng tiếng Việt: trả lời bằng tiếng Việt, ngắn gọn, nói rõ cái gì đã kiểm tra và cái gì chưa.

## Repo gồm gì

Repo này tách từ kienprovjppp/dink-radar (branch claude/rallyscope-analysis-video-bnrc0m, commit abf0081).

Bộ **RallyScope** biến một rally pickleball (camera cố định) thành video phân tích, trang tương tác và bảng điểm.

- `scripts/`: pipeline Python + Node (xem `README.md`).
- `template/index.html`: trang 1920×1080 (sân hologram, khung xương, vệt bóng, bảng bên phải, thẻ báo cáo). Trang này có thêm nút **Tải video lên** (phân tích ngay trong trình duyệt) và 4 nút bật/tắt lớp phủ.
- `runs/ppa_trim_rally_b/`: lần chạy rally B (PPA Chicago Cup): dữ liệu đã đo, trang đã dựng, `runs/ppa_trim_rally_b/HANDOFF.md` (trạng thái và việc còn lại).
- `tests/upload_test.mjs`: test headless cho luồng tải video lên.
- `mp/pose_model.wasm` và `mp/vision_wasm_internal.wasm`: mô hình MediaPipe cho nút **Tải video lên**. `pose_model.wasm` là pose landmarker bản *full* (file .task đổi đuôi), `vision_wasm_internal.wasm` là runtime WASM của `@mediapipe/tasks-vision@0.10.21`. Không sửa hai file này.

## Quy tắc khi phân tích

- Mọi con số đều phải đo từ video. Không bịa tốc độ, góc hay số cú đánh.
- Gọi người chơi là P1–P4 theo vị trí trên màn hình: P1 gần phải, P2 gần trái, P3 xa trái, P4 xa phải. Không đoán tên, danh tính hay giới tính.
- Luôn nêu cỡ mẫu (số cú đánh, số giây) và giới hạn đo.
- Python: dùng venv riêng với `mediapipe==0.10.21`, `opencv-python`, `numpy`, `scipy` (Python 3.12).

## Những điều đã học từ rally B

- Video 29,97 fps: đo trên frame gốc rồi nội suy lên 60 fps (`scripts/resample.py`). Frame nhân đôi làm hỏng mô hình vận tốc của bóng.
- Bóng không có viền tối như quy trình gốc mô tả: dò ứng viên với `--chan yellow`.
- Hệ số chiều cao người theo phối cảnh phụ thuộc camera (`--kh`). Rally B dùng 0.25.
- Theo dõi người: gán 4 người cùng lúc, kiểm tra bên sân bằng hông chứ không bằng mắt cá, phân biệt người bằng màu áo, khi mất dấu thì quét lưới 9 điểm (không phóng to khung cắt), rồi chạy `pose_track.py refine` để lấp khoảng trống.
- Tiếng trong bản phát sóng trễ hình 2–3 frame: thời điểm chạm bóng lấy theo hình. Cú đánh và lần nảy của rally B đã được kiểm chứng bằng mắt.

## Môi trường cloud (Claude Code on the web)

- Mạng chặn `cdn.jsdelivr.net`, YouTube và `sketchry.app`. Mở được `registry.npmjs.org`, `pypi.org`, `storage.googleapis.com` và GitHub.
- Muốn test MediaPipe JS trong cloud: `npm pack @mediapipe/tasks-vision@0.10.21`, phục vụ bản local, rồi đặt `window.__MP_BASE` và `window.__MP_DIR` qua `page.addInitScript` (xem `tests/upload_test.mjs`).
- Chromium của Playwright không giải mã được H.264: test bằng file VP9 `.webm`. Chạy headless không có GPU nên chỉ khoảng 0,3 frame/giây.
- Đừng dùng `pkill -f <mẫu>` nếu mẫu đó nằm ngay trong lệnh shell đang chạy, vì nó sẽ tự giết chính shell đó. Lọc theo tên tiến trình bằng `ps -eo pid,comm,args`.

## Trang công khai (Artifact)

- Bản 7 (2026-10-15): intro mới (mắt hologram nhiều lớp, lao qua con ngươi, bóng xoáy lốc rồi hóa thành logo/nút/ô/chữ của màn hình chính, khoảng 4,2 giây). Intro giữ yên ở frame đầu cho tới khi trang tải xong, font, màn hình chính và video nền sẵn sàng (tối đa 8 giây), có vẽ nháp từng đoạn để GPU chuẩn bị trước. Nguồn intro là `template/intro-demo.html` (demo tua được: https://claude.ai/artifact/3quqCaC4ZMmsWhnWQTASUq), chép sang `template/index.html` nguyên khối.
- Bản 8 (2026-10-15): đúng `template/index.html` của repo (commit 45f6bbc + tiêu đề màn hình chính "Play smarter <em>Not Harder</em>"): dò sân và theo dõi người/bóng mới, MediaPipe tải từ `mp/` cùng trang thay vì jsdelivr. Trước khi đăng đã chạy `tests/upload_test.mjs` trên chính bản đăng với jsdelivr bị chặn: chạy hết (7 cú đánh, 4 người); chưa thử tải video bằng trình duyệt trên chính link.
- Link: https://claude.ai/artifact/5ewsNu7BQSqZeeTtQZLNvM (đang để "ai có link cũng xem được"; bản 6 đăng ngày 2026-10-15: video nền màn hình chính `bg.mp4` (nguồn template/bg.mp4: 18 giây từ giây 36 của "Pickleball Cinematic | Sony a7IV", 1080p H.264, 5 MB; trang chạy được khi thiếu file), intro con mắt khoảng 3,5 giây mỗi lần tải trang (bấm hoặc nhấn phím để bỏ qua, không chạy khi ?record hoặc reduced motion), mọi ô bo tròn, trang mở đầu chỉ có ô thả video, rally mẫu nằm sau một ô riêng, bước điền tên người chơi thay P1–P4; tính năng tải video chưa được thử trên chính link này). Title (tên tab) là "RALLYSCOPE" (đổi từ "Chicago Cup Rally B" ở bản 9). Khi chỉ sửa trang thì chỉ cần đăng lại trang, các file kèm theo đã có sẵn trên link.
- Khi đăng lại: bỏ `<!doctype>`, `<html>`, `<head>`, `<body>` khỏi file. Gửi kèm `data.json`, `rally.mp4`, `rally.webm` và **`mp/pose_model.wasm`, `mp/vision_wasm_internal.wasm`, `mp/vision_bundle.mjs`, `mp/wasm/vision_wasm_internal.js`** (bắt buộc cho tính năng tải video; hai file JS khai báo `contentType: "text/javascript"`), cùng `mp/LICENSE-2.0.txt` và `mp/THIRD_PARTY_NOTICES.md` (Apache-2.0). Tất cả đã có trên link từ bản 8. Khai báo `capabilities: {sample: {}}` cho nút "Viết lại nhận xét bằng Claude".
- Commit vào branch được giao. Không tạo PR nếu Kien không yêu cầu.
