# LH25 đầy đủ trên máy thành viên (Windows)

Tài liệu này dành cho **bản FastAPI chạy tại `http://localhost:8770`**, không phải
hai trang Firebase Spark. `localhost` luôn chỉ chính máy đang mở trình duyệt.
Mỗi thành viên có cơ sở dữ liệu và cấu hình riêng; GitHub chỉ đồng bộ mã nguồn.

## 1. Lấy mã và cài môi trường

Cài Git và Python 3.12 (64-bit), sau đó mở PowerShell:

```powershell
git clone --branch codex/lh25-team-local https://github.com/nguyenthai1807/SchoolGuard-AI.git
Set-Location SchoolGuard-AI
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
Copy-Item .env.example .env
```

Không sao chép `.env` của chủ dự án. File mới chỉ là mẫu; tuyệt đối không commit
token Telegram, khóa payOS, mật khẩu SMTP, mật khẩu Admin hay thông tin khách.
`runtime/`, video riêng và checkpoint tự huấn luyện cũng không nằm trong Git.

## 2. Tải các model cần thử

Chạy lệnh cho chức năng cần dùng; lần đầu cần Internet và dung lượng ổ đĩa:

```powershell
.\.venv\Scripts\python.exe scripts\download_models.py
.\.venv\Scripts\python.exe -m scripts.download_model_catalog
.\.venv\Scripts\python.exe -m scripts.download_yolo26
.\.venv\Scripts\python.exe -m scripts.download_fire_model
.\.venv\Scripts\python.exe -m scripts.download_face_models
```

Các model công khai này không thay thế checkpoint `phone-body-v2` nhóm huấn luyện
riêng. Bộ demo học thuật, lịch sử mặt, kết quả video và tài khoản trên máy chủ
dự án **không** tự xuất hiện ở máy mới.

## 3. Chạy LH25

```powershell
.\start-lh25.ps1
```

Mở `http://localhost:8770`. Lần chạy đầu, tài khoản Admin cục bộ là `admin`;
nếu chưa đặt mật khẩu riêng, đọc `runtime/admin-password.txt` **trên chính máy
đó**. Không gửi file này qua chat hoặc GitHub. Giữ cửa sổ PowerShell chạy; dùng
`Ctrl+C` để dừng. Nếu cổng 8770 bận, dùng `start-lh25.ps1 -Port 8771` và mở đúng
cổng vừa chọn.

Muốn thử đăng nhập Google trên máy riêng, chủ dự án cần cho phép tài khoản thử
trong cấu hình OAuth, và máy thành viên cần Client ID phù hợp trong `.env`.
Không chia sẻ mật khẩu Google. Với Telegram, mỗi máy nên dùng bot thử nghiệm
riêng; nhiều LH25 cùng đọc một bot bằng `getUpdates` có thể tranh bản tin.
Giữ payOS **tắt** khi chỉ kiểm thử mã để không tạo giao dịch tiền thật.

Admin có thể cấp Pro miễn phí cho thành viên đã đăng nhập Google hoặc tạo quyền
chờ trước lần đăng nhập đầu bằng `python -m scripts.grant_team_pro email@example.com`.
Chỉ email đã được Google xác minh mới nhận quyền; lệnh không tạo đơn hàng hay
ghi nhận thanh toán. Quyền này nằm trong database của **máy chạy lệnh**, không
tự đồng bộ sang các bản LH25 trên máy thành viên. Nếu OAuth còn ở chế độ Testing,
Admin phải cho phép các email thử nghiệm trong Google Cloud trước khi họ đăng nhập.

## 4. Cùng sửa mã

Mỗi người tạo nhánh riêng từ `codex/lh25-team-local`, commit thay đổi,
push nhánh đó rồi gửi Pull Request để nhóm review. Không push trực tiếp dữ liệu
trong `.env`, `runtime/`, `models/*.pt`, `models/*.onnx` hoặc video. Một commit
GitHub không tự cập nhật server đang chạy: người vận hành phải lấy mã mới, kiểm
thử rồi khởi động lại LH25.

Ví dụ khi sửa một chức năng:

```powershell
git switch -c feature/ten-chuc-nang
# Sửa mã và chạy test trước khi commit.
git add -- duong-dan-tep-da-sua
git commit -m "feat(lh25): mo ta thay doi"
git push -u origin feature/ten-chuc-nang
```

Trên GitHub, chọn **Compare & pull request**, đặt nhánh đích là
`codex/lh25-team-local` và nhờ một thành viên khác xem lại. Không dùng
`git add .` nếu chưa kiểm tra danh sách tệp, vì máy có thể chứa dữ liệu riêng.

Nếu chỉ muốn **cùng xem một phiên LH25 đầy đủ**, chạy bản trên một máy trung tâm
và dùng `share-lh25.ps1` để tạo URL HTTPS tạm cho buổi test nội bộ. URL đó không
cho phép sửa mã, thay đổi sau mỗi lần mở tunnel và không thích hợp để nhận tiền
hoặc đưa dữ liệu khách thật vào.
