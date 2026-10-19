# SchoolGuard AI — Home Monitor MVP

SchoolGuard AI hiện tập trung vào một ứng dụng chạy trên máy tính cá nhân: người dùng
đăng nhập, chọn video hoặc bật webcam, tự khoanh vùng cần theo dõi và nhận cảnh báo
khi có người ở trong vùng đủ lâu. Mô hình nhiều camera/campus được giữ cho hướng phát
triển sau MVP.

## Những phần đã đồng bộ

- **FE-1:** đăng nhập, bố cục và thẻ tổng quan sự kiện.
- **FE-2:** phát video, webcam, khoanh vùng, vẽ bounding box và cảnh báo trực tiếp.
- **BE-1:** YOLO + ByteTrack cho video, luật vùng cấm/dwell time, ảnh minh chứng,
  video chú thích và metadata.
- **BE-2:** FastAPI, xác thực, SQLite, lưu sự kiện, ảnh bằng chứng và cấu hình thông báo.
- **TEST-1/TEST-2:** checklist kiểm thử và ba video mẫu trong `videos/`.
- **FE-3:** quy trình xác nhận cảnh báo, trạng thái xử lý, ghi chú và lịch sử thao tác.
  Phần giao diện campus dùng dữ liệu mẫu đã được chuyển sang nhật ký sự kiện thật của
  bản Home Monitor, không dùng `localStorage` hay dữ liệu giả.

Giao diện chính được FastAPI phục vụ tại cùng địa chỉ với API. Mã nguồn chế độ FE-2
chạy AI hoàn toàn trong trình duyệt vẫn được giữ lại, nhưng `/local` bị tắt mặc định
vì chế độ này tải TensorFlow.js và COCO-SSD từ CDN. Chỉ đặt
`ENABLE_BROWSER_ONLY_MODE=true` khi chấp nhận rủi ro phụ thuộc CDN.

## Chạy trên Windows PowerShell

Yêu cầu Python 3.11 trở lên. Từ thư mục dự án:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt
Copy-Item .env.example .env
```

Mở `.env`, đổi `SCHOOLGUARD_ADMIN_PASSWORD` thành mật khẩu riêng dài ít nhất 12 ký
tự, sau đó chạy:

```powershell
uvicorn main:app --host 127.0.0.1 --port 8000
```

Truy cập <http://127.0.0.1:8000>. Tài khoản mặc định là `admin`; mật khẩu là giá trị
đã đặt trong `.env`. Server chỉ bind vào máy cục bộ trong lệnh trên.

Lần đầu phân tích, Ultralytics có thể tải trọng số `yolo11n.pt`. Có thể đặt đường dẫn
model đã tải trong `YOLO_MODEL` để chạy hoàn toàn offline. Backend nhận tối đa một
job video cùng lúc, video tối đa ba phút/Full HD và giữ tối đa 10 video kết quả trong
24 giờ (điều chỉnh bằng `MAX_VIDEO_RESULTS`, `VIDEO_RESULT_TTL_HOURS`).

### Giấy phép mô hình

Ultralytics và các model YOLO tải qua thư viện này mặc định chịu giấy phép AGPL-3.0.
Bản hiện tại chỉ nhắm tới học tập và demo chạy cục bộ. Trước khi đóng mã nguồn, cung
cấp dưới dạng dịch vụ hoặc dùng thương mại, nhóm phải đánh giá nghĩa vụ AGPL-3.0 hay
mua giấy phép Enterprise theo chính sách chính thức của Ultralytics:
<https://www.ultralytics.com/license>.

## Kiểm tra video và webcam

### Video mẫu

1. Đăng nhập và chọn `Video1.mp4`, `Video2.mp4` hoặc `Video3.mp4` ở mục video mẫu.
2. Bấm **Nạp video mẫu**.
3. Giữ lựa chọn **Người**, bật chế độ khoanh vùng rồi kéo trên khung video.
4. Bấm Play để xem nhận diện theo từng khung, hoặc bấm **Phân tích video** để tạo
   video chú thích và lưu sự kiện.

Video có vùng chỉ chọn **Người** dùng worker BE-1 (YOLO + ByteTrack). Các lựa chọn
phương tiện hiện được giữ ở pipeline tương thích của BE-2 và chưa phải trọng tâm MVP.

### Webcam

1. Bấm **Bật camera** và cho phép trình duyệt sử dụng webcam.
2. Giữ lựa chọn **Người**, khoanh một vùng trên hình webcam.
3. Khi một người ở trong vùng đủ thời gian `ZONE_DWELL_SECONDS`, ứng dụng lưu ảnh
   minh chứng và thêm sự kiện vào nhật ký.

Khung hình webcam thông thường không được lưu; chỉ ảnh bằng chứng của sự kiện được
lưu trong thư mục `uploads/`. Dữ liệu này và SQLite đều đã được `.gitignore` loại khỏi
Git.

### Xử lý sự kiện

Trong **Lịch sử sự kiện vùng**, chọn một trong các trạng thái `Chưa xử lý`,
`Đã xác nhận`, `Đang xử lý`, `Đã hoàn tất` hoặc `Cảnh báo sai`, nhập ghi chú rồi bấm
**Lưu xử lý**. Mỗi lần cập nhật được lưu vào SQLite cùng thời gian và tài khoản thực
hiện; mở **Lịch sử xử lý** trên thẻ sự kiện để xem lại.

## Kiểm thử

```powershell
python -m pytest tests ai-service/tests
```

Các test gốc của worker không tải model thật. Smoke test YOLO với video thật:

```powershell
python ai-service/scripts/smoke_yolo.py --image C:\duong-dan\anh-co-nguoi.jpg --model yolo11n.pt
```

## Cấu trúc chính

- `main.py`: web/API, xác thực, DB, video upload và webcam.
- `home_video_analysis.py`: adapter nối vùng chữ nhật của FE-2 với worker BE-1.
- `video_analysis.py`: pipeline BE-2 và nhận diện khung hình trực tiếp.
- `ai-service/`: worker BE-1 độc lập.
- `index.html`: ứng dụng tích hợp.
- `local/`, `app.js`, `style.css`: chế độ AI chạy trong trình duyệt của FE-2.
- `videos/`: video mẫu phục vụ kiểm thử nội bộ.

## Phạm vi sau MVP

Hỗ trợ nhiều camera, sơ đồ campus, phân quyền nhiều người dùng, hàng đợi xử lý, triển
khai server tập trung và WebSocket là hướng phát triển tiếp theo; chúng chưa nằm trong
tiêu chí hoàn thành của bản chạy tại nhà này.
