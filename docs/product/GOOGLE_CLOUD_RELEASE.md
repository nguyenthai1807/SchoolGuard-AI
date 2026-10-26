# LH25: chuyển nguyên ứng dụng lên web

Trạng thái 2026-10-26: hai site Firebase Spark đã có địa chỉ HTTPS cố định dạng
`*.web.app`. LH25 công khai có giao diện gốc và Free YOLO8/9/10 chạy trong trình
duyệt. Bản đầy đủ FastAPI ở máy nhóm vẫn dùng SQLite, thư mục `runtime`, worker
và model cục bộ; **chưa có backend cloud**. Pro, Telegram và lưu video lâu dài
trên website công khai vẫn tắt. Chủ dự án chưa chốt ngân sách hằng tháng, vì vậy
chưa bật Cloud Billing/Blaze hay tạo dịch vụ có phí.

## Mục tiêu và ranh giới

- Giữ một giao diện LH25 xuyên suốt từ đăng nhập đến phân tích, webcam, cảnh báo,
  Telegram, gói và quản trị. Store ở site riêng; không tạo một sản phẩm thứ hai.
- Browser Free hiện tại được giữ như chế độ xử lý tại thiết bị. Khi backend cloud
  thực sự sẵn sàng, UI mới mở chế độ video/webcam xử lý ở máy chủ và kết quả lưu
  theo tài khoản.
- Không copy nguyên `.env`, SQLite, video riêng, dataset hoặc model thiếu giấy
  phép lên Firebase Hosting hay image công khai. Không giả vờ rằng UI đã đồng bộ
  tài khoản/Pro khi máy chủ chưa có dữ liệu bền vững.
- Không khôi phục chức năng phát hiện hung khí; yêu cầu này đã được rút khỏi sản phẩm.

## Kiến trúc đích

```text
Trình duyệt — Firebase Hosting (LH25 UI gốc, STORE)
       │ Google/Firebase Auth ID token
       ▼
FastAPI trên Cloud Run — xác minh token, quyền, quota, đơn hàng, webhook
       ├── CSDL bền vững: tài khoản, đơn hàng, trạng thái job, cảnh báo, audit
       ├── kho đối tượng riêng: video, ảnh bằng chứng, ảnh khuôn mặt, model
       ├── tác vụ xử lý bền vững: nhận video → model → lưu kết quả → Telegram
       └── email và payOS: secret phía server, webhook xác minh và idempotent
```

Hiện ứng dụng khởi tạo `Database(settings.runtime / "schoolguard.sqlite3")` và
`Worker` trong `schoolguard/app.py`. Cloud Run có hệ tệp không bền vững và có thể
khởi động nhiều instance; vì vậy **không triển khai FastAPI hiện tại nguyên xi**
cho người dùng thật. Xem [runtime contract](https://docs.cloud.google.com/run/docs/container-contract).
Firebase Hosting có thể chuyển tiếp `/api` tới Cloud Run, nhưng request qua
Hosting giới hạn 60 giây. Phân tích video phải trả `job_id` sớm và chạy nền, không
giữ kết nối upload/phân tích chờ hết clip.

## Kiểm kê trước di chuyển (không xuất dữ liệu cá nhân)

Chạy `\.venv\Scripts\python.exe -m scripts.audit_cloud_migration` từ thư mục
repository. Lệnh chỉ đọc SQLite và đếm tệp; không tạo bản sao, không tải lên
cloud và không in email, đường dẫn hay tên video. Dùng lại ngay trước mỗi lần
di chuyển vì số liệu có thể thay đổi khi LH25 đang chạy. Kiểm kê ngày
26/10/2026: SQLite ~0,62 MiB, 3 user, 77 job, 172 alert, 78 face, 1 order;
media trong `uploads`, `jobs`, `faces` tổng ~569 MiB. SQLite `quick_check` đạt,
không có vi phạm khóa ngoại ở thời điểm kiểm tra.

| Nguồn | Số bản ghi | Kết luận sơ bộ |
| --- | ---: | --- |
| `uploaded` | 4 | Tệp trong runtime còn đủ; chỉ chuyển khi đã xác định chủ sở hữu, quyền dùng và thời hạn lưu. |
| `live` | 12 | Không còn tệp nguồn; chỉ cân nhắc metadata/ảnh bằng chứng có quyền, không quảng cáo rằng có thể phát lại video. |
| `research` | 28 | Dùng demo học thuật nội bộ; không mặc định chuyển vào dịch vụ bán gói. |
| `testing` | 107 | Trỏ ra ngoài runtime; cần kiểm tra quyền sử dụng, không tự động copy. |
| `training` | 330 | Trỏ ra ngoài runtime; không tự động copy dataset lên cloud. |

Kiểm kê không phải backup nhất quán của SQLite WAL đang hoạt động. Trước khi
di chuyển thật, cần chốt bảng ánh xạ từng tài khoản sang Firebase `uid` bằng
xác minh chủ sở hữu (không ghép chỉ theo email), phân loại từng tệp theo quyền
và mức giữ lại, tạo backup có kiểm tra phục hồi, rồi chạy dry-run trên staging.
Không chuyển `sessions`, mật khẩu cũ, token xác minh, mã ghép Telegram tạm,
hoặc bí mật thanh toán vào kho công khai. Trạng thái đơn hàng/Pro phải được
đối soát độc lập trước khi kích hoạt quyền trên hệ thống mới.

## Thứ tự triển khai và chốt nghiệm thu

1. **Tài khoản:** server xác minh Firebase ID token; ánh xạ bằng `uid`, tuyệt đối
   không gộp tài khoản cũ chỉ vì email giống nhau. Tách quyền Admin/Free/Pro ở
   server, bổ sung MFA Admin và thử truy cập chéo hai tài khoản.
2. **CSDL:** chọn Firestore (ít chi phí cố định hơn nhưng phải viết lại SQL) hoặc
   PostgreSQL quản lý (gần schema hiện tại hơn nhưng có chi phí nền). Chốt sau
   khi có ngân sách. Di chuyển users, subscriptions, orders, jobs, alerts,
   notification_reads và audit bằng migration có kiểm tra số bản ghi, backup và
   diễn tập phục hồi.
3. **Kho video:** bucket riêng, không public; quyền theo `uid`, URL ký ngắn hạn
   hoặc proxy API, thời hạn lưu theo gói, tác vụ xóa và thử khôi phục. Không lưu
   ảnh mặt/video trong Firestore document. Di chuyển ảnh bằng chứng cùng metadata.
4. **Worker:** API tạo job và trả ngay; tác vụ nền lấy media từ bucket, dùng model
   được cấp phép, ghi kết quả bền vững, retry an toàn và không xử lý lại đơn/cảnh
   báo đã hoàn tất. Giới hạn độ dài, kích thước, số job đồng thời và ngân sách
   CPU/GPU theo gói. Chạy bộ video có nhãn để đo độ chính xác thật.
5. **Webcam:** browser camera cần HTTPS và quyền người dùng; gửi frame/stream
   có kiểm soát tới backend nếu chọn chế độ cloud. Camera IP trong LAN
   `192.168.x.x` không truy cập trực tiếp từ Cloud Run; cần edge agent chủ động
   kết nối ra hoặc chỉ dùng camera trình duyệt. Webcam 24/7 cần quota riêng.
6. **Thông báo và bán hàng:** mỗi người tự ghép chat Telegram và kiểm tra tin
   thử; khóa bot/payOS/SMTP chỉ ở secret server. payOS webhook phải kiểm chữ ký,
   mã đơn, số tiền, trạng thái, chống phát lại; email cấp Pro chỉ sau giao dịch
   hợp lệ hoặc duyệt tay có audit. Không bật thanh toán trước khi Pro cloud dùng
   được và điều khoản/giới hạn hiện rõ.
7. **Phát hành:** staging với tài khoản/video thử nghiệm, kiểm thử phân quyền,
   backup/restore, thất bại worker, webhook lặp, rollback và giám sát; sau đó
   mở production theo từng nhóm nhỏ. Không dùng video/ảnh nghiên cứu giới hạn
   quyền cho marketing thương mại.

### Phần mã đã chuẩn bị cho bước 1

`schoolguard/cloud_auth.py` là ranh giới xác thực cho backend tương lai. Nó dùng
Firebase Admin SDK ghim ở `requirements-cloud.txt`, project ID phải lấy từ cấu
hình triển khai và Application Default Credentials của môi trường máy chủ, không
đóng gói JSON service account. Token do Firebase Web SDK lấy bằng `getIdToken()`
phải được gửi qua HTTPS trong header `Authorization: Bearer …`. Server kiểm chữ
ký, đúng project, thời hạn, trạng thái thu hồi/vô hiệu hóa và yêu cầu tài khoản
Google có email đã xác minh. Kết quả chỉ là Firebase `uid` và email để hiển thị;
**không** lấy quyền Admin/Pro từ email, token client tự thêm hay hồ sơ Firestore
do client ghi. Module này chưa được nối vào app FastAPI cục bộ hoặc phát hành;
chưa có API khách hàng cloud nào được mở. Khi nối vào API thật phải tra quyền ở
kho server-side theo `uid`, giới hạn tốc độ trên kho dùng chung và kiểm tra tài
nguyên thuộc đúng `uid` trước mọi thao tác.

`schoolguard/cloud_access.py` chuẩn bị lớp đọc quyền. Tài liệu Free tại
`/users/{uid}` do client tạo chỉ chứng minh đồng ý điều khoản; code yêu cầu một
**phiên bản điều khoản cloud mới** (đuôi `-cloud`), nên điều khoản Free xử lý tại
máy hiện tại không tự mở upload/lưu trữ video. `cloud_entitlements/{uid}` và
`cloud_admins/{uid}` là bản ghi chỉ backend được ghi; Firestore rules hiện tại
đã từ chối client truy cập mọi collection ngoài `/users`. Pro cần grant có mã
đơn, nguồn duyệt đáng tin và hạn dùng còn hiệu lực. Admin cần grant riêng **và**
chứng thực MFA độc lập; chỉ có ID token Google chưa đủ. Đây là schema dự thảo,
chưa tạo collection hay cấp quyền trên Firebase. Trước khi dùng thật cần thêm
migration schema riêng, thủ tục cấp/thu hồi có audit, kiểm thử Firestore Rules
bằng emulator và IAM tối thiểu cho service account. Admin SDK phía server bỏ
qua Firestore Security Rules, nên IAM và kiểm tra quyền trong API là bắt buộc.
Đầu đọc từ chối Firestore client trỏ sai Firebase project so với trình xác minh
token, tránh ghép nhầm danh tính với quyền của dự án khác.

`schoolguard/cloud_api.py` ghép hai lớp trên thành API **thăm dò tài khoản**
`GET /api/cloud/me` cho staging. Nó chỉ trả về `uid`, gói hiệu lực và quyền đã
xác nhận, không có endpoint video, Telegram, quản trị hoặc thanh toán. Lỗi token
trả 401, chưa đồng ý điều khoản cloud trả 403, lỗi xác minh/Firestore trả 503;
không có chế độ tự cấp Free khi kho quyền lỗi. Chưa có entrypoint, cấu hình CORS,
gateway rate limit, giám sát hay deployment cho API này; không coi `/healthz`
thành chứng nhận sẵn sàng thương mại. Cần tạo điều khoản cloud thật và chốt quy
trình MFA trước khi nối người dùng thật.

## Chi phí và quyền kích hoạt

Cloud Run và Cloud Storage for Firebase cần liên kết Billing; khi liên kết dự
án Spark có thể chuyển sang Blaze. Hạn mức miễn phí không phải cam kết hóa đơn
0 đồng, nhất là khi xử lý video/webcam. Chủ dự án sẽ quyết định ngân sách trước
khi bật Billing. Cấu hình cảnh báo/spend cap (nếu sản phẩm hỗ trợ) phải được
kiểm tra; cảnh báo ngân sách thông thường không tự dừng chi phí. Không đưa API
key, token, mật khẩu hoặc giấy tờ qua chat hay Git.

Tới khi các bước 1–7 qua kiểm thử, `schoolguard/release.py` phải tiếp tục báo
`production_ready: false`; không dùng cờ môi trường để lách các chốt dữ liệu,
MFA hoặc thanh toán.
