# LH25 Free / Pro — hợp đồng tính năng và lộ trình thương mại

**Trạng thái:** Bản thiết kế để nhóm duyệt và triển khai theo giai đoạn; chưa phải tính năng đã có trên website.

**Nguồn:** Chủ dự án đồng ý lộ trình Free / Pro trong trao đổi tháng 10/2026.
**Liên quan:** [Luồng khách hàng và Telegram](LH25_CUSTOMER_CAPABILITY.md).

## Capability

Một khách hàng tự tạo tài khoản LH25, ghép Telegram, dùng gói Free với giới hạn rõ ràng, sau đó có thể mua Pro để mở quyền phân tích và giám sát tại nhà. Chủ dự án xem được người dùng, quyền gói, mức sử dụng và giao dịch; quyền Pro chỉ thay đổi khi có bằng chứng thanh toán hợp lệ hoặc thao tác quản trị được ghi audit.

**Tín hiệu thành công của pilot:** người mới hoàn tất ghép Telegram và phân tích video đầu tiên trong 10 phút; 10–20 hộ dùng thử; ít nhất 5 khách tự nguyện trả tiền và tiếp tục dùng tháng thứ hai. Đây là mục tiêu kiểm chứng, không phải dự báo doanh thu.

## 1. Lời hứa với khách hàng

LH25 hỗ trợ xem lại video và gửi cảnh báo Telegram có ảnh bằng chứng khi mô hình/rule phát hiện dấu hiệu té ngã, khói/lửa hoặc số người trong khung hình vượt mức người dùng đặt. Kết quả cần được người dùng kiểm tra. Sản phẩm chưa thay thế thiết bị báo cháy, dịch vụ y tế hoặc bảo vệ khẩn cấp. Không quảng cáo chức năng nghi bạo lực là phát hiện tấn công/vũ khí cho tới khi có bộ đánh giá độc lập đủ tốt.

Khách hàng có hai đường sử dụng: **phân tích video tải lên** và **webcam trực tiếp**. Free chứng minh giá trị bằng video; Pro Local mở giám sát webcam và lưu lịch sử phong phú trên máy khách. Pro Cloud là đợt sản phẩm riêng sau khi hạ tầng nhiều khách cùng chạy được.

## 2. Chính sách gói đề xuất cho pilot

Các mức giá và giới hạn dưới đây là **giả thuyết sản phẩm đã được đưa ra trong lộ trình**, cần đo chi phí và phản hồi khách trước khi công bố giá chính thức. Quyền thực tế phải được máy chủ kiểm tra, không dựa vào việc ẩn nút trên trình duyệt.

| Quyền / giới hạn | Free | Pro Local (pilot) | Pro Cloud Beta (chưa mở) |
|---|---|---|---|
| Giá thử nghiệm | 0đ | 29.000đ / 30 ngày cho đơn mới | 299.000–499.000đ / tháng, cần kiểm chứng chi phí |
| Tài khoản và Telegram riêng | Có | Có | Có |
| Video | 3 tác vụ mỗi tháng lịch; tối đa 2 phút mỗi video | Theo năng lực máy khách và giới hạn bảo vệ hệ thống | Theo quota tài nguyên được công bố |
| Tải lên | Giới hạn dung lượng riêng của Free, đề xuất 100 MB/file | Tối đa 1 GB/file theo cấu hình hiện tại | Giới hạn theo quota lưu trữ |
| Cảnh báo Telegram kèm ảnh | Có, cho tác vụ nằm trong quota | Có | Có |
| Webcam trực tiếp | Chưa mở | 1 phiên / giấy phép máy | 1 webcam, số giờ/tháng có giới hạn |
| Nghi ngã, khói/lửa, số người vượt `n` | Có trong video nếu model tương ứng sẵn sàng | Video và webcam | Video và webcam |
| Thư viện khuôn mặt ẩn danh theo ngày | Không lưu | Có, lưu cục bộ và cho phép xóa | Chỉ sau đánh giá riêng tư và chi phí |
| Lịch sử khả dụng | 24 giờ | Mặc định 30 ngày, cho phép xóa sớm hơn | Chưa chốt |
| Hỗ trợ | Tài liệu và email | Ưu tiên hỗ trợ trong giờ làm việc đã công bố | Chưa chốt |

Không gọi Pro Local là “AI không giới hạn”: một phiên webcam đang chạy hoặc hàng đợi bận vẫn có giới hạn tài nguyên và có thể tạm dừng. Giá theo chu kỳ 30 ngày là phương án pilot cấp quyền thủ công, **không tự gia hạn**. Không thu tiền định kỳ tự động khi chưa có hợp đồng và luồng hủy/gia hạn tương ứng.

## 3. Ràng buộc từ hệ thống hiện tại

- `users.role` hiện chỉ có `admin`, `operator`, `viewer`; chưa có plan, subscription hoặc quota. `operator` là quyền thao tác, **không đồng nghĩa Pro**. Cần tách quyền thao tác khỏi gói thương mại.
- Tài khoản hiện do admin tạo ở `/api/users`; email trong `customer_profiles` chỉ là liên hệ, chưa xác minh; chưa có tự đăng ký, quên mật khẩu hoặc thanh toán.
- `require_recipient()` hiện bắt khách lưu hồ sơ và ghép bot Telegram trước khi bắt đầu video/webcam. Yêu cầu này áp dụng cho cả Free và Pro trong thiết kế mới. Khách không cung cấp bot token hoặc mật khẩu Telegram.
- Mã hiện tại nhận file tới 1 GB, hàng đợi chung tối đa 10 job và `live_sessions` trong bộ nhớ chỉ cho **một webcam trên toàn server**, không phải một webcam mỗi tài khoản. Không thể mở Pro Cloud nhiều người chỉ bằng cách đổi nhãn gói.
- CSDL SQLite, job worker và ghép Telegram bằng `getUpdates` phù hợp pilot một tiến trình. Website public nhiều khách cần kiến trúc production, xác thực và tách dữ liệu được đánh giá lại.
- `admin` cục bộ hiện được miễn bước ghép Telegram để demo; quyền này không được tính là gói Pro và không được cấp cho khách qua tự đăng ký.
- Dữ liệu cũ không có chủ sở hữu chứng minh được tiếp tục chỉ admin xem; không gán mặc định vào tài khoản mới.

## 4. Vai trò và giao diện

**Khách Free/Pro:** đăng ký, xác minh email, đăng nhập, ghép Telegram, xem “Gói của tôi”, tải video, xem tác vụ/cảnh báo; Pro Local thêm webcam và thư viện khuôn mặt. Có thể xem mức đã dùng, thời điểm reset, hạn Pro và cách hủy/gia hạn. Khi hết quota, giao diện nói rõ khi nào sử dụng lại được và cho nút nâng cấp.

**Admin LH25:** danh sách khách, gói hiện tại, hạn dùng, số tác vụ, trạng thái Telegram, lịch sử cấp/gỡ quyền, đơn hàng và công cụ hỗ trợ. Admin không xem mật khẩu, bot token, ảnh/video khách chỉ để phục vụ báo cáo thương mại; quyền xem nội dung nhạy cảm cần lý do và audit riêng.

**Website giới thiệu / bán hàng:** trang tính năng, bảng giá, giới hạn kỹ thuật, chính sách lưu/xóa dữ liệu, FAQ, tạo tài khoản và nâng cấp. Dùng cùng thương hiệu LH25; landing page có thể là một route của ứng dụng trước khi cần website riêng.

**API dự kiến:** đăng ký/xác minh email/khôi phục mật khẩu; `/api/me/entitlements`, `/api/me/usage`, `/api/orders`, `/api/billing/*`, `/api/admin/customers/*`. Tên đường dẫn chỉ là hợp đồng thiết kế, chưa tồn tại. API phân tích hiện có phải kiểm tra entitlement/quota trước khi xếp job hoặc mở webcam.

## 5. Trạng thái và chuyển tiếp

```text
Tài khoản: pending_email -> active -> suspended -> deleted
Telegram: unlinked -> pending -> verified -> disconnected
Gói: free -> pro_active -> pro_expired -> free
Đơn hàng pilot: created -> awaiting_payment -> paid_verified -> provisioned
                                      \-> expired | cancelled | rejected
Video: uploaded -> quota_reserved -> queued -> running -> completed | failed | cancelled
```

- `active` + Telegram `verified` mới được bắt đầu phân tích. Nếu Telegram ngắt, ngăn tác vụ/phiên mới; phiên webcam đang chạy có chính sách tạm dừng và thông báo rõ, cần chốt trước khi triển khai.
- Pro bắt đầu khi thanh toán được **xác minh ở server**; ảnh chuyển khoản hoặc trang redirect thành công không đủ. Admin pilot xác minh thủ công bằng giao dịch ngân hàng, nhập mã tham chiếu và ghi audit.
- Gói hết hạn chuyển về Free ở lần kiểm tra quyền tiếp theo; không xóa dữ liệu Pro ngay. Người dùng có thời gian xuất/xóa dữ liệu trước lịch dọn dẹp đã công bố.
- Hủy quyền do hoàn tiền/gian lận cần audit và thông báo; đơn hàng bị gửi callback lặp không được cấp Pro hai lần.
- Nếu dịch vụ Telegram hoặc cổng thanh toán lỗi, giữ trạng thái chưa xác minh/chưa thanh toán, cho thử lại an toàn và hiển thị lý do; không cấp Pro tạm theo kết quả phía trình duyệt.

## 6. Hợp đồng dữ liệu và hạn mức

| Thực thể dự kiến | Trường chính / mục đích |
|---|---|
| `accounts` hoặc mở rộng `users` | email chuẩn hóa duy nhất, trạng thái xác minh, role kỹ thuật; mật khẩu hash; không lưu mật khẩu Telegram |
| `plans` / cấu hình phiên bản | mã Free, Pro Local, quyền và giới hạn theo phiên bản; snapshot chính sách lúc kích hoạt để hóa đơn/lịch sử không đổi ngầm |
| `subscriptions` | user, plan, trạng thái, bắt đầu/hết hạn UTC, nguồn cấp quyền, đơn hàng liên quan |
| `orders` | user, số tiền VND, trạng thái, mã tham chiếu duy nhất, provider, thời điểm xác minh; không lưu số thẻ |
| `usage_periods` | user, khoảng tháng theo Asia/Ho_Chi_Minh, số tác vụ video đã giữ chỗ/đã dùng, thời điểm reset |
| `devices` | giấy phép Pro Local gắn một máy theo cơ chế thay máy có hỗ trợ; cách định danh và thời gian offline còn mở |
| `audit` | ai cấp/thu hồi quyền, số đơn, thời gian và lý do; không ghi bí mật thanh toán/Telegram |

Free reset quota lúc 00:00 ngày 1 hằng tháng theo `Asia/Ho_Chi_Minh`; lưu mốc UTC trong CSDL. Kiểm tra quota và giữ chỗ **trong cùng giao dịch** trước khi tạo job để hai tab không vượt hạn mức. Video quá 2 phút phải báo lỗi trước khi xếp job; tệp quá dung lượng phải chặn trước khi lưu hoàn chỉnh. Nếu job bị lỗi hệ thống trước khi xử lý, trả quota; nếu người dùng hủy sau khi đã xử lý, tính là đã dùng. Quy tắc cuối cùng phải hiển thị trên giao diện.

Toàn bộ nguồn, job, cảnh báo, ảnh bằng chứng, ảnh khuôn mặt và Telegram gắn với chủ tài khoản. Không lấy `user_id` do trình duyệt gửi để quyết định chủ sở hữu. Dữ liệu Free hết hạn phải được dọn khỏi CSDL **và** file; có lịch dọn, khả năng retry và nhật ký kết quả. Backup cũng cần thời hạn lưu/xóa. Lưu 30 ngày của Pro là **mặc định đề xuất**, cần kiểm tra khả năng đĩa trên máy khách trước khi hứa.

## 7. Thanh toán và cấp quyền

**Pilot 10–20 khách:** tạo đơn có mã tham chiếu; khách chuyển khoản/QR; admin đối chiếu sao kê và đánh dấu đã thu; hệ thống tạo subscription Pro 30 ngày. Có thông báo email/Telegram về kích hoạt, ngày hết hạn, cách gia hạn/hủy và kênh hỗ trợ. Không tự mở quyền dựa vào ảnh biên lai khách tải lên.

**Sau pilot:** chọn cổng thanh toán phù hợp pháp nhân và thị trường; tích hợp sandbox, kiểm tra chữ ký callback, idempotency theo transaction ID, đối soát đơn/tiền và quy trình hoàn tiền. Chỉ mở tự gia hạn khi cổng và chính sách khách hàng hỗ trợ rõ. Cần nêu phí giao dịch, thuế và chi phí vận hành trong giá bán.

## 8. Bảo mật, quyền riêng tư và điều kiện phát hành

- HTTPS trên domain ổn định, quản lý secret, CSRF/session/cookie phù hợp HTTPS, rate limit đăng ký/đăng nhập/upload, kiểm soát file, sao lưu và phục hồi, giám sát lỗi. Link Quick Tunnel hiện tại chỉ phục vụ thử nhóm.
- Kiểm thử phân quyền chéo tài khoản trên mọi API và file; khách không thể đổi role, plan, quota hoặc xem order của người khác qua request tự tạo.
- Đồng ý xử lý video/khuôn mặt có thể rút lại; có quy trình xuất/xóa dữ liệu. Công khai bên thứ ba nhận dữ liệu cảnh báo (Telegram) và thời gian lưu. Cần rà soát yêu cầu pháp lý tại nơi bán trước khi public.
- Kiểm tra quyền sử dụng thương mại của Ultralytics/weights và các bộ video nghiên cứu; không dùng clip nghiên cứu thiếu quyền để quảng cáo hoặc huấn luyện bản thương mại.
- Đo trên video ngoài tập huấn luyện: tỉ lệ bỏ sót, cảnh báo sai/giờ webcam, thời gian từ sự kiện đến Telegram. Chỉ nêu số liệu có phương pháp đo và tập kiểm thử công khai trong tài liệu sản phẩm.

## 9. Thứ tự triển khai và tiêu chí nghiệm thu

1. **Nền tảng tài khoản:** tự đăng ký, xác minh email, khôi phục mật khẩu, đồng ý điều khoản, tách role khỏi plan. Nghiệm thu: tài khoản mới mặc định Free; không thể tự cấp admin/Pro; tài khoản cũ hoạt động theo chính sách chuyển đổi được duyệt.
2. **Free thật:** entitlement API, quota giao dịch, giới hạn video, màn hình mức dùng, dọn dữ liệu hết hạn. Nghiệm thu: 3 video <=2 phút/tháng, tab song song không vượt quota, job lỗi hệ thống hoàn quota, người khác không xem nội dung.
3. **Pro Local pilot:** webcam 1 máy, khuôn mặt theo ngày, lịch sử, đơn hàng và admin cấp quyền sau đối soát; trang “Gói của tôi”. Nghiệm thu: Free bị chặn webcam ở server; Pro được mở sau thanh toán; hết hạn quay về Free mà không mất dữ liệu ngay.
4. **Website bán hàng và vận hành:** bảng giá, FAQ, điều khoản, hỗ trợ, hoàn tiền, đo tỉ lệ hoàn thành onboarding và chuyển đổi. Nghiệm thu: khách mới tự đi từ trang giới thiệu tới video Free, rồi nâng cấp Pro, với trạng thái rõ ở mỗi bước.
5. **Pro Cloud Beta:** thiết kế lại xử lý đa người dùng và webcam, lưu trữ đối tượng, queue/worker, bot webhook, đo giờ camera và chi phí. Chỉ mở sau kiểm thử tải, phục hồi và phân quyền; không dùng `live_sessions` một tiến trình làm bản cloud trả tiền.

## 10. Ngoài phạm vi đợt đầu

Nhận diện danh tính người, phân loại vũ khí/tấn công chính xác, tự gọi công an/cứu hỏa, cam kết cấp cứu, multi-camera campus, tự gia hạn thẻ, hộ gia đình nhiều tài khoản quản trị và Pro Cloud công khai.

## 11. Quyết định còn mở

1. Chủ dự án bán Pro Local dưới dạng ứng dụng cài trên máy khách hay dịch vụ cài đặt/hỗ trợ từ xa? Cách cấp phép và hỗ trợ khác nhau.
2. Khách mục tiêu, pháp nhân, khu vực bán, phương thức thanh toán và quy trình hóa đơn/thuế là gì?
3. Thời gian lưu ảnh bằng chứng, video gốc, khuôn mặt và backup cụ thể là bao lâu; ai được quyền xóa/xuất?
4. Cơ chế đổi máy, mất mạng/offline, hoàn tiền và ngừng Telegram giữa phiên webcam xử lý ra sao?
5. Giá 29.000đ/30 ngày và giới hạn Free có phù hợp sau pilot không? Cần đo chuyển đổi và chi phí hỗ trợ.
6. Cần luật sư/chuyên gia phù hợp xác nhận câu chữ bán hàng và yêu cầu xử lý dữ liệu tại thị trường triển khai.

## Handoff

**Sẵn sàng thực hiện:** tài khoản/entitlement Free, quota video và giao diện mức dùng trong pilot local, sau khi chốt chính sách chuyển đổi tài khoản cũ.

**Cần review kiến trúc:** giấy phép Pro Local, tự đăng ký trên Internet, thanh toán, Pro Cloud, dữ liệu và xử lý đồng thời nhiều webcam.

**Cần quyết định sản phẩm:** sáu mục ở phần 11 trước khi công bố gói bán chính thức.
**Bước tiếp theo:** chia thành PR nhỏ theo mục 9, bắt đầu với thiết kế migration tài khoản và quyền gói; kiểm thử phân quyền/quota là điều kiện merge.
