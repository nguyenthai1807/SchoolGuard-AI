"""Credential-free checks; distinguish local pilot setup from public release."""

import os

from .commerce import valid_public_url


def release_report(settings, payos_available, email_available, worker_alive=None):
    local_checks = [
        {"id": "local_database", "ok": (settings.runtime / "schoolguard.sqlite3").is_file(),
         "label": "Dữ liệu LH25 trên máy", "next_step": "Khởi động LH25 rồi sao lưu thư mục runtime định kỳ."},
        {"id": "worker", "ok": worker_alive,
         "label": "Bộ xử lý video", "next_step": "Mở LH25 và kiểm tra mục Hệ thống; nếu worker dừng, khởi động lại server."},
        {"id": "model", "ok": any((settings.models / f"{name}.pt").is_file()
                                     for name in ("yolov8n", "yolo11n", "yolo26n")),
         "label": "Model phát hiện người", "next_step": "Tải checkpoint được hỗ trợ vào models và kiểm tra mục Hệ thống."},
        {"id": "google", "ok": bool(settings.google_client_id),
         "label": "Đăng nhập Google cục bộ", "next_step": "Cấu hình LH25_GOOGLE_CLIENT_ID và origin localhost:8770 trên Google OAuth."},
        {"id": "google_admin", "ok": bool(settings.google_admin_subjects),
         "label": "Quyền Admin Google", "next_step": "Chỉ định đúng Google subject chủ dự án trong LH25_GOOGLE_ADMIN_SUBS."},
        {"id": "telegram", "ok": bool(os.environ.get("LH25_TELEGRAM_BOT_TOKEN", "").strip()),
         "label": "Bot Telegram", "next_step": "Đặt LH25_TELEGRAM_BOT_TOKEN trên máy; từng khách vẫn phải tự ghép và xác minh chat."},
        {"id": "payos_local", "ok": bool(payos_available),
         "label": "Khóa payOS cho link thanh toán", "next_step": "Chạy configure-commerce.ps1 trên máy; không đưa khóa lên Git."},
        {"id": "smtp_local", "ok": bool(email_available),
         "label": "SMTP gửi hướng dẫn Pro", "next_step": "Cấu hình SMTP trong .env và dùng scripts/check_smtp.py để thử kết nối, không gửi mật khẩu vào chat."},
    ]
    configured_next_steps = {
        "local_database": "Đã có dữ liệu cục bộ; hãy sao lưu thư mục runtime định kỳ.",
        "worker": "Worker đang chạy; kiểm tra một video ngắn để xác minh xử lý thực tế.",
        "model": "Đã thấy checkpoint; vẫn cần thử trên video có nhãn để đánh giá kết quả.",
        "google": "Đã có Client ID; xác minh đăng nhập bằng tài khoản thử nghiệm trên localhost.",
        "google_admin": "Đã có ánh xạ Admin; kiểm tra đúng tài khoản chủ dự án vào được trang quản trị.",
        "telegram": "Đã có token; mỗi khách vẫn cần tự ghép chat và kiểm tra tin nhắn thử.",
        "payos_local": "Đã có khóa; thử tạo link theo đúng mã đơn và đối soát một giao dịch nhỏ.",
        "smtp_local": "Đã có cấu hình; dùng scripts/check_smtp.py --connect để kiểm tra đăng nhập SMTP.",
    }
    for item in local_checks:
        if item["ok"] is True:
            item["next_step"] = configured_next_steps[item["id"]]
    checks = [
        {"id": "https", "ok": valid_public_url(settings.public_base_url),
         "label": "Địa chỉ HTTPS cố định", "next_step": "Cần tên miền và hosting cố định; localhost hoặc tunnel tạm không đạt."},
        {"id": "payos", "ok": bool(payos_available),
         "label": "Khóa payOS", "next_step": "Cấu hình khóa riêng trên máy chủ, rồi kiểm thử giao dịch thật và webhook."},
        {"id": "email", "ok": bool(email_available), "label": "Dịch vụ gửi email",
         "next_step": "Cấu hình SMTP và xác minh khả năng gửi/nhận từ môi trường triển khai."},
        {"id": "verification", "ok": settings.email_verification_required,
         "label": "Yêu cầu xác minh email", "next_step": "Chỉ bật sau khi SMTP và HTTPS cố định đã được kiểm thử."},
        {"id": "payments", "ok": settings.payment_enabled, "label": "Thanh toán tự động",
         "next_step": "Hiện có thể duyệt tay; chỉ bật webhook tự động sau khi có HTTPS cố định và kiểm thử đối soát."},
        {"id": "cloud_database", "ok": False, "label": "CSDL bền vững và migration",
         "next_step": "Chuyển SQLite cục bộ sang dịch vụ DB có backup, migration và kiểm soát truy cập trước khi public."},
        {"id": "cloud_storage", "ok": False, "label": "Kho video riêng và hàng đợi bền vững",
         "next_step": "Triển khai storage riêng theo người dùng, retention và worker bền vững trước khi mở cho nhiều khách."},
        {"id": "admin_mfa", "ok": False, "label": "MFA cho Admin",
         "next_step": "Bổ sung xác thực nhiều lớp ở tầng ứng dụng hoặc nhà cung cấp danh tính; chưa thể tự bật từ localhost."},
    ]
    return {"production_ready": all(item["ok"] for item in checks), "checks": checks,
            "local_checks": local_checks,
            "yolo26": {name: (settings.models / f"{name}.pt").is_file()
                       for name in ("yolo26n", "yolo26s", "yolo26n-pose")},
            "note": "Dấu Có cấu hình chỉ xác nhận có cấu hình/tệp, không chứng minh email, payOS hay model hoạt động chính xác. Local pilot không đồng nghĩa sẵn sàng công khai."}
