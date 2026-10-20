# LH25 — Home Safety Studio

LH25 là bản giám sát **cục bộ tại nhà**: phân tích video trước, sau đó dùng cùng detector/rule engine cho webcam trực tiếp. Ứng dụng phát hiện người bằng YOLO11 Pose + ByteTrack, nghi té ngã/nằm lâu, số người quan sát vượt mức thường trú `n`, và nghi lửa/khói bằng ONNX riêng. Cảnh báo có ảnh bằng chứng, lịch sử duyệt và tùy chọn gửi Telegram. Đây là **nghiên cứu hỗ trợ quan sát**, không phải hệ thống báo cháy/y tế được chứng nhận.

Lõi video và nhiều test được chuyển từ [SchoolGuard-6Astra-Test](https://github.com/nguyenthai1807/SchoolGuard-6Astra-Test) của cùng chủ repo; phần webcam, Telegram, cấu hình `n` và giao diện LH25 được thêm tại đây. Ứng dụng Home Monitor cũ vẫn nằm ở `main.py` để không phá dữ liệu/test trước đây; **entrypoint LH25 là `schoolguard.app:create_app`**, không phải `uvicorn main:app`.

## Chạy trên Windows PowerShell

Yêu cầu Python 3.11+; đã thử với Python 3.12. Từ thư mục repo:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
.\.venv\Scripts\python.exe scripts\download_models.py
.\.venv\Scripts\python.exe -m scripts.download_fire_model
.\.venv\Scripts\python.exe -m scripts.download_face_models
.\start-lh25.ps1 -Dataset 'C:\Users\PCX\Downloads\splits\splits\shanghaitech'
```

Mở <http://127.0.0.1:8770>. Tài khoản `admin`; LH25 dùng mật khẩu `LH25_ADMIN_PASSWORD` hoặc `SCHOOLGUARD_ADMIN_PASSWORD` trong `.env` khi tạo DB lần đầu. Nếu chưa có giá trị hợp lệ, mật khẩu ngẫu nhiên được lưu ở `runtime/admin-password.txt`. Không chia sẻ nội dung file này. DB LH25 ở `runtime/schoolguard.sqlite3`, **khác** DB của `main.py`; tài khoản chỉ được khởi tạo một lần, thay biến môi trường sau đó không tự đổi mật khẩu trong DB. Server chỉ bind `127.0.0.1`, một Uvicorn worker.

Nếu không dùng bộ ShanghaiTech, bỏ `-Dataset`; video riêng có thể tải ở trang **Phân tích video** (tối đa 1 GB). `runtime/`, `.env`, model weights và video nghiên cứu không được commit.

## Telegram

1. Trên Telegram, mở [@BotFather](https://t.me/BotFather), gửi `/newbot` và làm theo hướng dẫn; giữ kín token như mật khẩu.
2. Mở bot vừa tạo, gửi `/start` hoặc một tin nhắn. Lấy `chat.id` từ `getUpdates` theo [Bot API](https://core.telegram.org/bots/api#getupdates), hoặc dùng script dưới đây; script **chỉ in chat ID**, không in token:

   ```powershell
   .\.venv\Scripts\python.exe -m scripts.telegram_chat_id
   ```

3. Điền vào `.env` trên máy:

   ```text
   LH25_TELEGRAM_BOT_TOKEN=...
   LH25_TELEGRAM_CHAT_ID=...
   ```

4. Khởi động lại LH25. Trang **Hệ thống** hiển thị trạng thái cấu hình. Video và webcam gửi ảnh **mỗi sự kiện đã xác nhận qua nhiều frame** bằng `sendPhoto`; lỗi gửi không dừng phân tích và trạng thái được lưu trong bản ghi cảnh báo. Ở trang **Cảnh báo**, operator/admin có thể gửi lại các cảnh báo chưa tới Telegram; cảnh báo đã gửi không được gửi lặp bằng nút này. Không có bot/chat ID thì ứng dụng vẫn chạy, trạng thái là `telegram_not_configured`. Telegram là dịch vụ ngoài: ảnh bằng chứng của cảnh báo được gửi tới Telegram khi bật. Chưa có cơ chế retry tự động khi mạng gián đoạn; hãy kiểm tra trạng thái giao hàng.

Không dán token vào issue, commit, ảnh màn hình hoặc chat. Nếu lộ token, tạo token mới trong BotFather.

## Dùng video và webcam

- **Video:** chọn nguồn ShanghaiTech hoặc tải MP4/AVI/MOV/MKV; vẽ đa giác nếu cần. Mặc định YOLO11n Pose, nghi té ngã, lửa/khói khi model sẵn sàng, và `n=1`. `0` giây = cả clip. Xem tiến độ, video H.264 và cảnh báo ở **Tác vụ xử lý**.
- **Webcam:** mở **Webcam trực tiếp**, chọn `n`, bật camera và cấp quyền trình duyệt. Trình duyệt gửi JPEG định kỳ về backend cùng máy; pose, lửa/khói và luật ngưỡng dùng cùng lõi với video. Webcam không được ghi video liên tục; khi bật nhận diện khuôn mặt, ảnh đại diện của từng khuôn mặt cũng được lưu trên máy. Dừng camera trước khi đóng tab để hoàn tất phiên trong nhật ký; nếu tab tắt đột ngột, phiên cũ sẽ được thu hồi khi mở phiên mới sau 45 giây không có frame. Camera trình duyệt cần `localhost` hoặc HTTPS.
- `n` là **số người đang quan sát trong khung**, không phải danh tính thành viên gia đình. Khi thấy `n+1` người liên tục ít nhất 3 giây, hệ thống báo `unexpected_person`. Người bị che khuất, ra/vào khung hoặc track ID đổi có thể làm sai số đếm.
- Quy tắc té ngã yêu cầu chuyển tư thế/độ cao qua thời gian; nằm lâu là tín hiệu riêng. Lửa/khói cần nhiều quan sát cùng vị trí; sự kiện cùng loại có cooldown 15 giây để tránh báo dồn. Không có cảnh báo **không** có nghĩa là an toàn.

## Khuôn mặt trong video và webcam

Chạy `python -m scripts.download_face_models` bằng Python của `.venv` trước khi bật tính năng. Script tải hai file ONNX đã ghim commit và SHA256 từ [OpenCV Zoo](https://github.com/opencv/opencv_zoo): YuNet để tìm mặt, SFace để so đặc trưng. Không cài thêm thư viện hay đưa ảnh lên dịch vụ bên ngoài. Sau khi tải, khởi động lại LH25.

- **Video:** bật **Lưu ảnh đại diện và gom khuôn mặt trùng nhau trong video** khi tạo tác vụ. Góc phải trang chi tiết video hiển thị ảnh, số thứ tự và thời điểm xuất hiện đầu tiên của từng khuôn mặt. Video đã xử lý trước khi bật tính năng cần phân tích lại.
- **Webcam:** bật **Lưu khuôn mặt... theo ngày** trước khi mở camera. Góc phải hiển thị số khuôn mặt khác nhau trong ngày; trang **Khuôn mặt theo ngày** cho phép mở lại từng ngày. Dừng và bật lại camera trong cùng ngày vẫn dùng chung danh sách; sang ngày mới bắt đầu danh sách mới theo múi giờ của máy.
- Ảnh đại diện nằm ở `runtime/faces/`, đặc trưng nhận dạng ở `runtime/schoolguard.sqlite3`; cả hai bị loại khỏi Git. Chỉ tài khoản đã đăng nhập mới xem được. Ảnh khuôn mặt trong thư viện không được gửi Telegram. Tính năng này không tương thích với tùy chọn **Che mờ người** của video.

Đây là **gom nhóm khuôn mặt ẩn danh**, chưa gán tên hay xác minh danh tính. Mặt mờ, nhỏ, khuất, nghiêng hoặc xuất hiện giữa hai lần lấy mẫu có thể bị bỏ sót; cùng một người có thể thành hai mục, hai người có thể bị gộp. Số liệu là ước tính, không dùng để kết luận chính xác có bao nhiêu người trong nhà. Model lấy mẫu tối đa mỗi 0,5 giây trên video và mỗi 1 giây trên webcam.

## Dữ liệu, kiểm thử và giới hạn

`C:\Users\PCX\Downloads\splits\splits\shanghaitech` chứa video và chuỗi ảnh **anomaly**, không có nhãn bounding box người/cháy/té ngã đầy đủ; không dùng nhãn này để tuyên bố độ chính xác các sự kiện nhà ở. Kết quả fine-tune người trong `models/training-report.json` là thí nghiệm cũ trên campus; checkpoint không vượt baseline nên không tự động dùng.

Các script tải dữ liệu chỉ lấy mẫu có nguồn gốc rõ và giữ dưới `runtime/event-data/`:

```powershell
.\.venv\Scripts\python.exe -m scripts.prepare_event_data
.\.venv\Scripts\python.exe -m scripts.prepare_home_fire_eval
.\.venv\Scripts\python.exe -m scripts.smoke_home runtime\event-data\urfd\fall-02-cam0-rgb.mp4 --falls
.\.venv\Scripts\python.exe -m scripts.smoke_home runtime\event-data\furg\house6.mp4 --fire --seconds 8
.\.venv\Scripts\python.exe -m pytest tests ai-service\tests test_api_be2.py --basetemp runtime\pytest-legacy
.\.venv\Scripts\python.exe -m pytest astra_tests --basetemp runtime\pytest-lh25
node --check schoolguard\static\app.js
```

Nguồn bổ sung: [UR Fall Detection](https://fenix.ur.edu.pl/~mkepski/ds/uf.html) (fall/ADL, nghiên cứu phi thương mại), [AIRTLab](https://github.com/airtlab/A-Dataset-for-Automatic-Violence-Detection-in-Videos) (hành vi dàn dựng), [Fire-Detection example](https://github.com/pedbrgs/Fire-Detection), [FURG fire dataset](https://github.com/steffensbola/furg-fire-dataset) (CC0, video mô hình nhà/bối cảnh ngoài trời và XML annotation). Không huấn luyện trên clip rồi báo cáo chính clip đó là test độc lập; chia theo cảnh/camera/người, không chia ngẫu nhiên frame liền kề. `scripts/prepare_home_fire_eval.py` ghim commit và lưu SHA256. [FIRESENSE](https://zenodo.org/records/836749) và [Indoor Fire and Smoke dataset](https://huggingface.co/datasets/shahriar-5/IFireSmoke) là ứng viên đánh giá sau; bản Indoor FS hiện yêu cầu quyền truy cập, nên chưa tải tự động.

Smoke test thực trên máy CPU: sau khi giảm cửa sổ xác nhận chuyển động nhanh từ 0,2 xuống 0,1 giây, replay detections bắt được `fall-01` và `fall-02`, còn `fall-03` vẫn bị bỏ sót; cả 3 clip `adl-01/02/03` không báo ngã. Clip `wildfire.mp4` có 1 cảnh báo khói. `house6.mp4` (video mô hình nhà, không phải cháy thật trong phòng) nhận khói trong 8 giây đầu, nhưng nhãn loại có thể sai. Cần thêm clip indoor thực, đối chứng cảnh sinh hoạt bình thường và đánh giá false alerts/giờ trước khi dùng như hệ thống cảnh báo chính. Các clip URFD này là smoke test phát triển, **không** phải bộ test độc lập đủ lớn để tuyên bố độ chính xác.

## Hướng phát triển hợp lý

Ưu tiên tiếp theo: bộ test indoor fire thực có nhãn và cảnh âm tính khó (bếp nấu, đèn, ánh nắng), đo thời gian tới cảnh báo và false alerts/giờ; gắn nhãn riêng các kiểu ngã/ngồi nhanh để huấn luyện temporal classifier; chế độ giờ nhà vắng/giờ ngủ; phát hiện camera mất tín hiệu; tùy chọn nút xác nhận khẩn cấp và chuỗi liên hệ dự phòng khi Telegram lỗi. Mở rộng campus/multi-camera để sau khi bản tại nhà được đánh giá độc lập.

Giấy phép: Ultralytics/weights có điều kiện [AGPL-3.0 hoặc Enterprise](https://www.ultralytics.com/license); model ONNX lửa/khói là thử nghiệm của [tác giả uploader](https://huggingface.co/fiacecson20/cctv-ai-fire-smoke). Kiểm tra quyền dùng dữ liệu/model trước khi phân phối hoặc thương mại hóa.
