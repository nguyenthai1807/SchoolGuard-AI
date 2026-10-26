# LH25 — Lock Home 24 + 1 / 7

LH25 là bản giám sát **cục bộ tại nhà**: phân tích video trước, sau đó dùng cùng detector/rule engine cho webcam trực tiếp. Người dùng chọn YOLO8/9/10 (Free) hoặc YOLO11/12/26 (Pro Local) cho tác vụ phù hợp; model Pose hỗ trợ quy tắc nghi té ngã/nằm lâu, model riêng sàng lọc lửa/khói và ngưỡng số người thường có là `n`. Chức năng phát hiện hung khí đã được gỡ do nguy cơ báo nhầm. Cảnh báo có ảnh bằng chứng, lịch sử duyệt và tùy chọn gửi Telegram. Đây là **nghiên cứu hỗ trợ quan sát**, không phải hệ thống báo cháy/y tế được chứng nhận.

Lõi video và nhiều test được chuyển từ [SchoolGuard-6Astra-Test](https://github.com/nguyenthai1807/SchoolGuard-6Astra-Test) của cùng chủ repo; phần webcam, Telegram, cấu hình `n` và giao diện LH25 được thêm tại đây. Ứng dụng Home Monitor cũ vẫn nằm ở `main.py` để không phá dữ liệu/test trước đây; **entrypoint LH25 là `schoolguard.app:create_app`**, không phải `uvicorn main:app`.

## Bản Free công khai trên Firebase Spark

- [LH25 STORE](https://lh25-store-20261024.web.app/) là trang giới thiệu, chưa nhận thanh toán.
- [LH25](https://lh25-app-20261025.web.app/) cho đăng nhập Google, xác nhận điều khoản và mở **Phân tích trên thiết bị**. Video tối đa 2 phút/100 MB và webcam được xử lý trong trình duyệt bằng YOLO8n, YOLO9t hoặc YOLO10n; kết quả là số người trong khung hình lấy mẫu, không phải số người duy nhất trong video. Không tải video lên Firebase.
- Bản công khai hiện **không** có Pose/ngã/cháy, Telegram, thư viện khuôn mặt, Pro hay thu tiền. Các model YOLO11/12/26 cùng tính năng nâng cao chỉ chạy trên bản Python cục bộ khi tài khoản có quyền Pro Local. Không đồng bộ tài khoản hay dữ liệu giữa hai bản.

Mã nguồn giai đoạn tiếp theo đã đưa vỏ giao diện đăng nhập, sidebar và trang phân tích của bản Firebase về cùng thiết kế LH25 gốc. Thay đổi giao diện này **chưa phát hành lên URL công khai**; chủ dự án chọn chuẩn bị mã trước khi quyết định ngân sách backend. Xem [lộ trình chuyển LH25 nguyên bản lên web](docs/product/GOOGLE_CLOUD_RELEASE.md). Giữ nguyên giới hạn Free khi kiểm thử bản dựng này; việc giống giao diện không có nghĩa backend đã sẵn sàng.

FastAPI nguyên bản chủ động từ chối khởi động khi thấy môi trường Cloud Run (`K_SERVICE`) hoặc `LH25_DEPLOYMENT_TARGET=cloud`: SQLite, video và worker hiện chưa có kho bền vững. Chốt này phải được thay bằng adapter dữ liệu cloud cùng kiểm thử backup/restore, không lách bằng cách đổi cờ triển khai.

Để dựng lại gói tĩnh từ checkpoint chính thức trên máy phát hành: chạy `scripts/download_model_catalog.py`, `scripts/export_free_browser_models.py` bằng Python của `.venv`; chạy `npm ci` trong `tools/browser-runtime`; sau đó chạy `scripts/build_firebase_free.py` và `scripts/build_public_store.py`. Thư mục `hosting/firebase-spark/app` và `hosting/public` là đầu ra được giới hạn tệp; không đưa `.env`, video, CSDL hay key thanh toán vào Hosting. Kiểm thử trước khi deploy; Firebase Spark có hạn mức miễn phí, khi hết hạn mức dịch vụ có thể tạm dừng thay vì tự mở thanh toán.

## Chạy trên Windows PowerShell

Thành viên nhóm cài trên máy mới đọc [hướng dẫn chạy LH25 đầy đủ qua localhost](docs/product/TEAM_LOCAL_SETUP.md). GitHub chỉ đồng bộ mã nguồn, không đồng bộ `.env`, dữ liệu và model tự huấn luyện.

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

Mở <http://localhost:8770> để dùng ứng dụng hoặc <http://localhost:8770/store> để xem trang giới thiệu, đăng ký Free và yêu cầu Pro. Đăng nhập Google khi thử cục bộ cần dùng `localhost`, không dùng `127.0.0.1`. Tài khoản `admin`; LH25 dùng mật khẩu `LH25_ADMIN_PASSWORD` hoặc `SCHOOLGUARD_ADMIN_PASSWORD` trong `.env` khi tạo DB lần đầu. Nếu chưa có giá trị hợp lệ, mật khẩu ngẫu nhiên được lưu ở `runtime/admin-password.txt`. Không chia sẻ nội dung file này. DB LH25 ở `runtime/schoolguard.sqlite3`, **khác** DB của `main.py`; tài khoản chỉ được khởi tạo một lần, thay biến môi trường sau đó không tự đổi mật khẩu trong DB. Server chỉ bind `127.0.0.1`, một Uvicorn worker.

### Trang bán hàng pilot: Free và Pro Local

Trang `/store` dùng chung backend và phiên đăng nhập với LH25, nên khách đăng ký tại đây rồi vào thẳng ứng dụng. Mỗi tài khoản mới được cấp **Free**: tối đa 3 lần phân tích video/tháng, mỗi video tối đa 2 phút và file tải lên tối đa 100 MB. Cần kết nối Telegram thành công trước khi phân tích. Free không mở webcam hay lưu thư viện khuôn mặt. Tài khoản `operator` đã tồn tại trước lần nâng cấp CSDL này được giữ quyền **Pro Local pilot** để không làm gián đoạn nhóm kiểm thử; tài khoản do admin tạo sau này cũng là Pro pilot. Quyền Pro cũ không đồng nghĩa đã thanh toán.

Giá Pro Local pilot cho đơn mới là **29.000₫/30 ngày**. Trên bản LH25 chạy cục bộ, khách dùng tài khoản Google đã xác minh email có thể mở link payOS/QR riêng cho đơn nếu quản trị viên đã bật thanh toán; đây là giao dịch tiền thật. Sau khi khách thanh toán, Admin phải kiểm tra trạng thái giao dịch trên payOS, nhập mã tham chiếu thật và duyệt thủ công; Pro không tự mở từ lời báo của khách. Bản Firebase công khai hiện **không mở thanh toán hoặc Pro**. Đơn cũ không tự đổi giá; không xóa CSDL hoặc `runtime/` nếu muốn giữ tài khoản, đơn và lịch sử.

Đây **chưa phải website thương mại công khai**: email chưa xác minh, chưa có thanh toán tự động/hóa đơn, chưa có chính sách lưu trữ tự động, chưa có bảo đảm vận hành hoặc đánh giá an toàn đủ cho sản phẩm bảo vệ con người. URL Quick Tunnel chỉ dành cho thử nghiệm có kiểm soát; trước khi nhận khách trả tiền cần triển khai hạ tầng ổn định, sao lưu, chính sách quyền riêng tư/điều khoản, đánh giá model và rà soát giấy phép thương mại. Tránh public URL nếu chưa có bot Telegram được cấu hình: khách sẽ không thể hoàn tất kích hoạt.

Mã nguồn đã có **luồng xác minh email và adapter payOS dạng opt-in**, nhưng đang tắt vì chưa có tên miền/tài khoản dịch vụ. Không có giao dịch hay email thật nào được tạo bằng bản mặc định. Để xem điều kiện mở và các kiểm thử cần làm, đọc [hướng dẫn thương mại hóa](docs/product/COMMERCE_LAUNCH.md). Thanh toán tự động chỉ cấp Pro qua webhook hợp lệ, không dựa vào trang trả về của trình duyệt.

### Chia sẻ cho nhóm kiểm thử

Giữ LH25 chạy, rồi mở PowerShell thứ hai tại thư mục dự án và chạy `./share-lh25.ps1`. Script tải `cloudflared` từ repository chính thức của Cloudflare vào `tools/` (bị Git bỏ qua) và in một URL HTTPS `https://...trycloudflare.com` để gửi cho nhóm. Tunnel chỉ chuyển tiếp tới `127.0.0.1`; không cần mở cổng router. Giữ cả cửa sổ LH25 và tunnel mở; `Ctrl+C` ở cửa sổ tunnel sẽ ngắt link và lần chạy sau tạo URL mới. Quick Tunnel chỉ dành cho test, không có cam kết uptime. Không chia sẻ tài khoản admin: tạo một tài khoản `operator` riêng cho từng người ở mục **Hệ thống**.

Nếu không dùng bộ ShanghaiTech, bỏ `-Dataset`; video riêng có thể tải ở trang **Phân tích video** (tối đa 1 GB). `runtime/`, `.env`, model weights và video nghiên cứu không được commit.

## Telegram

1. Quản trị viên mở [@BotFather](https://t.me/BotFather), gửi `/newbot`, làm theo hướng dẫn rồi đặt **duy nhất bot token** trong `.env` trên máy chạy LH25:

   ```text
   LH25_TELEGRAM_BOT_TOKEN=...
   ```

2. Khởi động lại LH25. Admin tạo tài khoản **operator** cho khách ở mục **Hệ thống**. Khách đăng nhập, mở mục **Telegram**, điền tên và email liên hệ, rồi nhấn **Tạo liên kết Telegram**. Không cần nhập mật khẩu Telegram hay bot token của khách.
3. Khách mở bot LH25 qua liên kết được hiện, nhấn Start hoặc gửi lệnh `/start` đi kèm. Quay lại website, nhấn **Kiểm tra & xác minh**. Bot sẽ gửi một tin thử; chỉ khi gửi thành công LH25 mới đánh dấu Telegram đã kết nối. Khách chưa hoàn tất thông tin và Telegram sẽ không thể bắt đầu video/webcam. Phần hướng dẫn chi tiết nằm ngay dưới biểu mẫu trong mục **Telegram**.
4. Để thử: tải một video có té ngã ở **Phân tích video**, chọn model `yolo11n-pose`, bật **Nghi té ngã**, đặt thời lượng `0` giây (toàn video), rồi mở **Tác vụ xử lý** và **Cảnh báo**. Cảnh báo sự kiện sẽ gửi ảnh bằng chứng tới **chat đã xác minh của khách tạo tác vụ**, không gửi về chat của khách khác hoặc chat cũ của admin. Với webcam, mở **Webcam trực tiếp** và cấp quyền camera. Sau khi phân tích xong, kiểm tra trạng thái `Đã gửi` của từng cảnh báo; bot bị chặn/mất mạng vẫn có thể làm gửi thất bại.

`LH25_TELEGRAM_CHAT_ID` chỉ còn là cấu hình cũ *tùy chọn cho tài khoản admin local*; khách hàng không cần điền chat ID vào `.env`. Nếu admin muốn dùng cấu hình cũ, lấy chat ID bằng script `python -m scripts.telegram_chat_id` **trước khi dùng luồng ghép trên web**; không chạy script và website cùng đọc `getUpdates` của một bot. Khi gửi thất bại, lỗi không dừng phân tích và trạng thái được lưu trong cảnh báo. Operator/admin có thể gửi lại cảnh báo chưa tới; chưa có retry tự động. Telegram là dịch vụ ngoài và ảnh bằng chứng của cảnh báo sẽ đi qua máy chủ Telegram.

Không dán token vào issue, commit, ảnh màn hình hoặc chat. Nếu lộ token, tạo token mới trong BotFather.

Luồng khách hiện là **pilot chạy local**: khách có thể tự đăng ký Free tại `/store`, hoặc admin tạo `operator` pilot; khách tự điền thông tin và xác minh Telegram. Email chưa được xác minh, thanh toán/kích hoạt Pro vẫn thủ công. Xem [hợp đồng tính năng khách hàng](docs/product/LH25_CUSTOMER_CAPABILITY.md) trước khi triển khai công khai. Các clip URFD là dữ liệu nghiên cứu, không tự động có quyền dùng thương mại.

## Dùng video và webcam

- **Video cục bộ:** chọn nguồn ShanghaiTech hoặc tải MP4/AVI/MOV/MKV; vẽ đa giác nếu cần. Bộ chọn model có YOLO8/9/10 Free và YOLO11/12/26 Pro Local khi checkpoint sẵn có. Mặc định dùng Pose cho quy tắc nghi té ngã; khi chuyển sang model Person không có Pose, giao diện giữ lựa chọn và tắt các quy tắc cần Pose. `0` giây = cả clip. Xem tiến độ, video H.264 và cảnh báo ở **Tác vụ xử lý**.
- **Demo chỉ cho Admin:** trong **Phân tích video**, mục **★ Video demo đã duyệt** hiển thị tối đa năm nguồn cho mỗi chức năng. Các clip nghiên cứu có nhãn chỉ dùng học thuật nội bộ, không đưa vào STORE/quảng cáo; một số nhóm chưa đủ năm clip được kiểm chứng. Sao demo không phải số đo độ chính xác.
- **Webcam:** mở **Webcam trực tiếp**, chọn `n`, bật camera và cấp quyền trình duyệt. Trình duyệt gửi JPEG định kỳ về backend cùng máy; pose, lửa/khói và luật ngưỡng dùng cùng lõi với video. Webcam không được ghi video liên tục; khi bật nhận diện khuôn mặt, ảnh đại diện của từng khuôn mặt cũng được lưu trên máy. Dừng camera trước khi đóng tab để hoàn tất phiên trong nhật ký; nếu tab tắt đột ngột, phiên cũ sẽ được thu hồi khi mở phiên mới sau 45 giây không có frame. Camera trình duyệt cần `localhost` hoặc HTTPS.
- `n` là **số người đang quan sát trong khung**, không phải danh tính thành viên gia đình. Khi thấy `n+1` người liên tục ít nhất 3 giây, hệ thống báo `unexpected_person`. Người bị che khuất, ra/vào khung hoặc track ID đổi có thể làm sai số đếm.
- Quy tắc té ngã yêu cầu chuyển tư thế/độ cao qua thời gian; nằm lâu là tín hiệu riêng. Lửa/khói cần nhiều quan sát cùng vị trí; sự kiện cùng loại có cooldown 15 giây để tránh báo dồn. Không có cảnh báo **không** có nghĩa là an toàn.

## Khuôn mặt trong video và webcam

Chạy `python -m scripts.download_face_models` bằng Python của `.venv` trước khi bật tính năng. Script tải hai file ONNX đã ghim commit và SHA256 từ [OpenCV Zoo](https://github.com/opencv/opencv_zoo): YuNet để tìm mặt, SFace để so đặc trưng. Không cài thêm thư viện hay đưa ảnh lên dịch vụ bên ngoài. Sau khi tải, khởi động lại LH25.

- **Video:** bật **Lưu ảnh đại diện và gom khuôn mặt trùng nhau trong video** khi tạo tác vụ. Ở **Tác vụ xử lý**, mở video vừa phân tích: cột cạnh trình phát hiển thị tổng số, ảnh, số thứ tự và thời điểm xuất hiện đầu tiên của từng khuôn mặt. Tác vụ cũ chưa bật tính năng cần chạy lại. Clip có người nhưng không thấy rõ mặt vẫn có thể có kết quả bằng 0.
- **Người quay lưng:** video mới còn lưu ảnh vùng đầu/vai theo mã theo dõi YOLO, kể cả khi không thấy mặt. Mục **Người được theo dõi** hiển thị số người tối đa cùng lúc và ảnh của từng track (tối đa 500 track/video). Đây **không phải** nhận diện khuôn mặt hoặc danh tính; mất dấu có thể tạo hai track cho cùng một người. Video bật **Che mờ người** không lưu ảnh vùng đầu/vai. Tác vụ cũ cần phân tích lại để có thư viện ảnh track.
- **Webcam:** bật **Lưu khuôn mặt... theo ngày** trước khi mở camera. Ngay trong **Webcam trực tiếp**, góc phải hiển thị mặt đã lưu hôm nay, bên dưới có lịch sử chọn ngày và ảnh từng khuôn mặt. Có thể xem lịch sử ngay cả khi camera đã tắt. Dừng và bật lại camera trong cùng ngày vẫn dùng chung danh sách; sang ngày mới bắt đầu danh sách mới theo múi giờ của máy.
- Ảnh đại diện nằm ở `runtime/faces/`, đặc trưng nhận dạng ở `runtime/schoolguard.sqlite3`; cả hai bị loại khỏi Git. Chỉ tài khoản đã đăng nhập mới xem được. Ảnh khuôn mặt trong thư viện không được gửi Telegram. Tính năng này không tương thích với tùy chọn **Che mờ người** của video.

Đây là **gom nhóm khuôn mặt ẩn danh**, chưa gán tên hay xác minh danh tính. Mặt mờ, nhỏ, khuất, nghiêng hoặc xuất hiện giữa hai lần lấy mẫu có thể bị bỏ sót; cùng một người có thể thành hai mục, hai người có thể bị gộp. Số liệu là ước tính, không dùng để kết luận chính xác có bao nhiêu người trong nhà. Model lấy mẫu tối đa mỗi 0,5 giây trên video và mỗi 1 giây trên webcam.

**Xung đột:** tùy chọn **Nghi xung đột qua chuyển động mạnh** đang tắt mặc định. Quy tắc Pose chỉ sàng lọc động tác nhanh gần người khác, không xác định bạo lực hay hành vi tấn công. Một số clip sinh hoạt bình thường vẫn bị cảnh báo; vì độ đặc hiệu chưa đạt, kết quả này chỉ ở mức thử nghiệm và cần người xem lại. Xem kế hoạch đánh giá trong `docs/experiments/violence-screening.md`.

**Hung khí đã gỡ:** LH25 không còn cho tạo tác vụ mới với tùy chọn này; API từ chối yêu cầu cũ và không nạp detector trong worker. Tệp checkpoint và tài liệu thử nghiệm cũ chỉ giữ cục bộ để đối chiếu lịch sử, không phải tính năng đang bán hay phát hành.

## Dữ liệu, kiểm thử và giới hạn

`C:\Users\PCX\Downloads\splits\splits\shanghaitech` chứa video và chuỗi ảnh **anomaly**, không có nhãn bounding box người/cháy/té ngã đầy đủ; không dùng nhãn này để tuyên bố độ chính xác các sự kiện nhà ở. Kết quả fine-tune người trong `models/training-report.json` là thí nghiệm cũ trên campus; checkpoint không vượt baseline nên không tự động dùng.

Các script tải dữ liệu chỉ lấy mẫu có nguồn gốc rõ và giữ dưới `runtime/event-data/`:

```powershell
.\.venv\Scripts\python.exe -m scripts.prepare_event_data
.\.venv\Scripts\python.exe -m scripts.prepare_home_fire_eval
.\.venv\Scripts\python.exe -m scripts.smoke_home runtime\event-data\urfd\fall-02-cam0-rgb.mp4 --falls --faces
.\.venv\Scripts\python.exe -m scripts.smoke_home runtime\event-data\furg\house6.mp4 --fire --seconds 8
.\.venv\Scripts\python.exe -m pytest tests ai-service\tests test_api_be2.py --basetemp runtime\pytest-legacy
.\.venv\Scripts\python.exe -m pytest astra_tests --basetemp runtime\pytest-lh25
node --check schoolguard\static\app.js
```

Nguồn bổ sung: [UR Fall Detection](https://fenix.ur.edu.pl/~mkepski/ds/uf.html) (fall/ADL, nghiên cứu phi thương mại), [AIRTLab](https://github.com/airtlab/A-Dataset-for-Automatic-Violence-Detection-in-Videos) (hành vi dàn dựng), [Fire-Detection example](https://github.com/pedbrgs/Fire-Detection), [FURG fire dataset](https://github.com/steffensbola/furg-fire-dataset) (CC0, video mô hình nhà/bối cảnh ngoài trời và XML annotation). Không huấn luyện trên clip rồi báo cáo chính clip đó là test độc lập; chia theo cảnh/camera/người, không chia ngẫu nhiên frame liền kề. `scripts/prepare_home_fire_eval.py` ghim commit và lưu SHA256. [FIRESENSE](https://zenodo.org/records/836749) và [Indoor Fire and Smoke dataset](https://huggingface.co/datasets/shahriar-5/IFireSmoke) là ứng viên đánh giá sau; bản Indoor FS hiện yêu cầu quyền truy cập, nên chưa tải tự động.

Smoke test thực trên máy CPU: sau khi giữ mốc tư thế đứng ổn định qua giai đoạn hạ người và mất pose ngắn, replay dữ liệu đã lưu bắt được `fall-01/02/03` (mỗi clip một cảnh báo nghi ngã); `adl-01/02/03` không báo ngã. Chạy lại pipeline thật với `fall-03-cam0-rgb.mp4 --falls --faces` hoàn tất 215 frame, tạo một cảnh báo khẩn ở 6,1 giây và lưu một khuôn mặt xuất hiện trong 7 lần lấy mẫu; xử lý 7,17 giây video mất 52,4 giây trên CPU lần thử này. Clip `wildfire.mp4` có 1 cảnh báo khói. `house6.mp4` (video mô hình nhà, không phải cháy thật trong phòng) nhận khói trong 8 giây đầu, nhưng nhãn loại có thể sai. Cần thêm clip indoor thực, đối chứng cảnh sinh hoạt bình thường và đánh giá false alerts/giờ trước khi dùng như hệ thống cảnh báo chính. Các clip URFD này là smoke test phát triển, **không** phải bộ test độc lập đủ lớn để tuyên bố độ chính xác.

## Hướng phát triển hợp lý

Ưu tiên tiếp theo: bộ test indoor fire thực có nhãn và cảnh âm tính khó (bếp nấu, đèn, ánh nắng), đo thời gian tới cảnh báo và false alerts/giờ; gắn nhãn riêng các kiểu ngã/ngồi nhanh để huấn luyện temporal classifier; chế độ giờ nhà vắng/giờ ngủ; phát hiện camera mất tín hiệu; tùy chọn nút xác nhận khẩn cấp và chuỗi liên hệ dự phòng khi Telegram lỗi. Mở rộng campus/multi-camera để sau khi bản tại nhà được đánh giá độc lập.

Giấy phép: Ultralytics/weights có điều kiện [AGPL-3.0 hoặc Enterprise](https://www.ultralytics.com/license); model ONNX lửa/khói là thử nghiệm của [tác giả uploader](https://huggingface.co/fiacecson20/cctv-ai-fire-smoke). Kiểm tra cả giấy phép runtime/base weights và quyền dùng dữ liệu trước khi phân phối hoặc thương mại hóa.

YOLO26n/s và YOLO26n Pose là **lựa chọn thử nghiệm** cho video và webcam, không thay mặc định YOLO11. Xem [cách tải, fine-tune và đánh giá YOLO26](docs/YOLO26_EXPERIMENT.md); model COCO không tự nhận biết bạo lực hay cháy.


### Webcam: ID và vật thể

Webcam dùng ID ẩn danh liên tục trong mỗi phiên, ghép lại track bị đổi số khi vị trí còn khớp trong 2,5 giây và loại khung trùng gần như hoàn toàn. Số ID không phải danh tính người; mất dấu lâu hoặc che khuất vẫn có thể tạo số mới. Khuôn mặt có cửa sổ ghép phù hợp nhịp lấy mẫu webcam (tối đa 2,5 giây, cần khớp đặc trưng và vị trí).

Mặc định dùng `yolo11s.pt` để đếm người. Bật **Phát hiện vật thể** để tìm thêm các lớp COCO như ô tô, xe máy, xe tải trong cùng một lượt suy luận. Khi bật cảnh báo tư thế, dùng Pose cho người và model riêng cho vật thể. Vật thể không cộng vào số người. Có thể chọn ảnh suy luận 640 (nhanh hơn) hoặc 960 (người ở xa, chi tiết hơn). Nguồn mạng mặc định 960, webcam máy tính 640. Cảnh báo tư thế mặc định tắt để ưu tiên đếm người/lưu mặt; bật lại khi cần.


### Dùng camera điện thoại hoặc camera IP trên máy tính

Trên trang **Webcam trực tiếp**, chọn **Nguồn hình ảnh → Điện thoại / camera IP qua mạng**. Điền URL luồng rồi bấm **Bật camera & phân tích**. Máy tính kết nối trực tiếp với thiết bị và thực hiện nhận diện, lưu mặt, cảnh báo như nguồn webcam.

Nguồn webcam và camera mạng đều cần quyền Pro Local và Telegram đã kết nối. Thư viện khuôn mặt theo ngày được tách theo tài khoản; một khách hàng không thể xem hoặc xóa khuôn mặt của khách hàng khác.

- Điện thoại: kết nối cùng Wi-Fi với máy tính, bật tính năng/app phát camera qua HTTP/MJPEG hoặc RTSP, rồi nhập đúng URL luồng do thiết bị cung cấp (ví dụ `http://192.168.1.20:8080/video`). Giữ ứng dụng phát camera mở.
- Camera IP: bật RTSP trong cấu hình camera và lấy URL từ hướng dẫn của chính thiết bị (ví dụ `rtsp://192.168.1.30:554/stream1`). Có thể nhập tài khoản trong URL nếu camera yêu cầu. URL không được lưu trong cấu hình tác vụ hoặc phản hồi API.
- Dùng địa chỉ IP riêng trong LAN, không nhập URL trang quản trị, đường dẫn tệp hoặc URL Internet. Máy tính phải truy cập được IP/cổng của thiết bị; Wi-Fi khách có thể chặn các thiết bị kết nối nhau.
- Chế độ này không yêu cầu mở cổng web SchoolGuard ra mạng hoặc dùng webcam máy tính. Điện thoại mở trực tiếp trang SchoolGuard trong trình duyệt để phát camera chưa được hỗ trợ trong chế độ này; điện thoại cần phát luồng camera.
- Hiện phân tích một nguồn trực tiếp mỗi lần; bấm **Dừng camera** để đổi thiết bị. Chỉ ảnh mặt và ảnh cảnh báo được lưu, không ghi video liên tục. Hình trực tiếp lấy ảnh mới nhất độc lập với AI, không xếp hàng khung hình. Mở **Kết quả AI** dưới hình để xem các khung nhận diện gắn với đúng ảnh đã phân tích; ảnh này cập nhật theo tốc độ AI.


Điện thoại có thể chọn **Hướng hình** (giữ nguyên / xoay trái / xoay phải / 180°) và **Lật ngang như camera selfie** trước khi kết nối hoặc dùng nút xoay/lật dưới hình ngay trong phiên. Đổi hướng sẽ xóa liên kết vị trí cũ nhưng giữ thư viện mặt đã lưu. Phép xoay/lật áp dụng lên ảnh đầu vào AI nên ảnh mặt lưu, ảnh cảnh báo và khung nhận diện cùng hướng. Không tự suy ra tư thế cầm điện thoại khi luồng không truyền metadata xoay. Ảnh dọc giữ cạnh dài tối đa 1280 px; bộ đọc liên tục bỏ khung cũ, chỉ giữ ảnh mới nhất. Bộ tìm mặt thử thêm vùng đầu của tối đa hai người bị bỏ sót mỗi lượt, luân phiên giữa những người trong khung. Danh sách ảnh mặt tải riêng để không chặn vòng đọc camera.


### Đếm cơ thể và huấn luyện từ video Drive

Khung **xanh dương** là người, khung **cam** là vật thể. Số “Người đang thấy” chỉ đếm detection lớp person, độc lập với lưu mặt. Người đã được xác nhận vẫn được giữ khi có detection cơ thể thật với độ tin cậy giảm xuống một nửa ngưỡng ban đầu (tối thiểu 0,1), trong cửa sổ 2,5 giây. Không tạo thêm người từ vị trí dự đoán khi không còn detection; người bị che kín hoàn toàn không được tính như một quan sát chắc chắn.

Đợt `phone-body-v2` dùng một clip đại diện của mỗi cảnh trong 13 cảnh ShanghaiTech từ thư mục Drive người dùng cung cấp. Train ở cảnh 1/2/3/5/6/10/13, validation ở 4/8/11, test ở 7/9/12. Có 114 ảnh train (gốc, crop bỏ đầu, che thân giả lập), 9 validation và 9 test. Nhãn train/validation chủ yếu do YOLO11s tạo; các nhãn người trên test được rà soát, loại phản chiếu kính và khung trùng. Đây là thử nghiệm nhỏ ngoài trời, chưa đại diện cho quán đông người.

Các lệnh tái tạo, chạy từ thư mục dự án:

```powershell
.venv/Scripts/python.exe -m pip install -r requirements-training.txt
.venv/Scripts/python.exe -m scripts.fetch_phone_training
.venv/Scripts/python.exe -m scripts.prepare_phone_training
.venv/Scripts/python.exe -m scripts.apply_phone_label_review
.venv/Scripts/python.exe -m scripts.train_phone_people --epochs 6
.venv/Scripts/python.exe -m scripts.evaluate_phone_body
```

Script giữ nguyên dataset/run đã tồn tại; không ghi đè trọng số model đang dùng. Bản rà soát trong `docs/phone-body-test-review.json` chỉ áp dụng nếu SHA256 ảnh và nhãn khớp. Checkpoint lưu ở `runtime/training-runs/phone-body-v2/weights/best.pt`; báo cáo ở `runtime/phone-training/report.json`. Trang **Dữ liệu & đánh giá** hiển thị tiến độ và so sánh với YOLO11s. Chỉ cân nhắc thay mặc định nếu precision/recall/F1, sai số đếm và độ trễ đạt điều kiện; đánh giá crop thân người được ghi riêng.
