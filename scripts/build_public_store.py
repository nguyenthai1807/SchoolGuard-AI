"""Build an allowlisted, informational Store; never publish backend or secrets."""
from pathlib import Path
import re
import shutil

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "hosting" / "public"
STATIC_ASSETS = (
    "store.css", "store-ribbon.css", "brand.css", "store-i18n.js",
    "favicon-store.png", "brand-lh25-original.jpg", "brand-store-wordmark.png",
    "store-group-consented.webp", "demo-library.webp", "demo-plan.webp",
    "elderly-home-fall-feature.png", "child-home-observation.png",
    "yolo-person-illustration.webp", "yolo-pose-illustration.webp",
)


def build():
    source = ROOT / "schoolguard" / "static"
    html = (source / "store.html").read_text(encoding="utf-8")
    html = html.replace('href="/store"', 'href="/"')
    html = html.replace(
        'Dùng thử Free hoặc yêu cầu Pro Local.',
        'Đăng ký Free để phân tích người trong video hoặc webcam trên thiết bị; Pro chưa mở thanh toán.',
    )
    html = re.sub(r'<script src="/static/(?:store|google-signin)\.js(?:\?[^"]*)?" defer></script>', '', html)
    html = re.sub(
        r'<section id="start".*?</section>',
        '''<section id="start" class="section start-section"><div class="wrap">
        <span class="overline">LH25 / TRẠNG THÁI DỊCH VỤ</span>
        <h2>Free phân tích người ngay trong trình duyệt.</h2>
        <p>Đăng nhập Google tại LH25 để thử đếm người trong video ngắn hoặc webcam. Chọn YOLO8, YOLO9 hoặc YOLO10 chạy trên thiết bị của bạn; video không tải lên Firebase. Chưa có cảnh báo ngã/cháy, Telegram, thư viện khuôn mặt hoặc Pro trên bản công khai. Backend đầy đủ của nhóm chạy riêng trên máy thử nghiệm.</p>
        <p>Chưa thu tiền trên hai trang Firebase. Pro bên dưới chỉ là lộ trình dự kiến; không chuyển khoản theo tin nhắn hay ảnh chụp.</p>
        <a class="button outline" href="https://lh25-app-20261025.web.app/">Tạo tài khoản Free ↗</a>
        </div></section>''', html, flags=re.DOTALL,
    )
    html = html.replace('href="/#overview"', 'href="#start"')
    html = html.replace('href="/terms"', 'href="/terms.html"')
    html = html.replace('href="/privacy"', 'href="/privacy.html"')
    html = html.replace('Vào ứng dụng', 'Trạng thái ứng dụng')
    html = html.replace(
        'LH25 giúp bạn kiểm tra video hoặc webcam tại nhà. Khi thấy dấu hiệu té ngã, khói/lửa hoặc số người vượt mức đã đặt, hệ thống lưu bằng chứng và gửi cảnh báo qua Telegram.',
        'Bản Free công khai giúp bạn đếm người trong video hoặc webcam ngay trên thiết bị. Các cảnh báo té ngã, khói/lửa và Telegram đang được thử nghiệm riêng trên máy của nhóm, chưa mở cho tài khoản trên website này.',
    )
    html = html.replace('Telegram cảnh báo', 'Telegram · lộ trình tiếp theo')
    html = html.replace('Từ một video đến một cảnh báo có bằng chứng.', 'Từ video của bạn đến kết quả ngay trên máy.')
    html = html.replace('Bạn kiểm soát nguồn video, ngưỡng quan sát và người nhận tin.',
                        'Bạn chọn video hoặc webcam và ngưỡng số người; không có tin nhắn hay video được gửi đi.')
    html = html.replace('Kiểm tra cảnh báo', 'Kiểm tra kết quả')
    html = html.replace('Mỗi cảnh báo là một tín hiệu để kiểm tra, đi kèm thời điểm và hình ảnh tham chiếu.',
                        'Các thẻ dưới đây mô tả hướng phát triển đang thử nghiệm trên máy nhóm. Bản web Free hiện chỉ khoanh và đếm người.')
    html = html.replace('YOLO8/9/10 phát hiện người; YOLO8 Pose cho cảnh báo nghi té ngã',
                        'Chọn YOLO8/9/10 để khoanh và đếm người; Pose/ngã chưa mở trên web Free')
    html = html.replace('Không mở webcam, nhận diện khuôn mặt hoặc model nâng cao',
                        'Webcam có thể mở sau khi cấp quyền; không lưu video lên máy chủ')
    html = html.replace('Chỉ hiện nguồn video thuộc tài khoản đang đăng nhập và giới hạn Free.',
                        'Ảnh màn hình bản chạy tại máy nhóm; cổng Free công khai hiện không lưu thư viện video.')
    html = html.replace('Xem lượt video còn lại, trạng thái webcam và đường nâng cấp Pro.',
                        'Ảnh màn hình bản chạy tại máy nhóm; mua Pro chưa mở trên cổng công khai.')
    html = html.replace('Bắt đầu với Free', 'Tìm hiểu Free')
    html = html.replace('Tạo tài khoản Free', 'Free · sắp mở')
    html = html.replace('Yêu cầu Pro Local', 'Pro · chưa mở bán')
    html = html.replace('thanh toán hiện được nhóm xác nhận thủ công.', 'chưa mở bán và chưa nhận thanh toán trên trang này.')
    html = html.replace('Bạn gửi yêu cầu Pro trong ứng dụng. Nhóm LH25 liên hệ và hướng dẫn thanh toán; quyền Pro được kích hoạt sau khi giao dịch được xác minh. Website chưa nhận thanh toán tự động.', 'Chưa mở bán. Không chuyển khoản để mua từ trang giới thiệu này. Thanh toán chỉ mở khi backend và quy trình xác nhận giao dịch đã được kiểm thử.')
    html = html.replace('Pro chỉ được kích hoạt sau khi nhóm xác minh thanh toán; chưa có thanh toán tự động.', 'Tài khoản Free đang thử nghiệm; Pro chưa thu tiền trên trang công khai.')
    html = html.replace('href="#start" data-select-plan="free"', 'href="https://lh25-app-20261025.web.app/" data-select-plan="free"')
    html = html.replace('Free · sắp mở', 'Tạo tài khoản Free')
    html = html.replace('Có. Sau khi tạo tài khoản, bạn kết nối chat Telegram riêng với bot LH25. Bot gửi tin thử thành công thì bạn mới bắt đầu phân tích video.',
                        'Chưa cần Telegram để tạo tài khoản Free thử nghiệm. Kết nối Telegram và phân tích video chỉ mở khi nhóm phát hành chức năng tương ứng.')
    html = html.replace('3 video/tháng, tối đa 2 phút và 100 MB/video', 'Video tối đa 2 phút và 100 MB, xử lý trên thiết bị; chưa lưu kết quả lên cloud')
    html = html.replace('Thử phân tích video của bạn, xem kết quả và kiểm tra cách nhận cảnh báo.',
                        'Thử đếm người trong video hoặc webcam ngay trên thiết bị; chưa gửi cảnh báo.')
    html = html.replace('Free dùng video; Pro Local có thêm webcam. Bạn đặt mức người thường có trong khung hình.',
                        'Bản Free công khai hỗ trợ video ngắn và webcam trong trình duyệt để đếm người. Bạn đặt mức người dự kiến trong khung hình.')
    html = html.replace('Xem lại đoạn video và ảnh bằng chứng. Telegram chỉ nhận cảnh báo khi hệ thống ghi nhận sự kiện.',
                        'Xem số người và khung phát hiện trên màn hình. Bản Free công khai chưa gửi Telegram hoặc lưu bằng chứng.')
    html = html.replace('Phân tích video ngắn', 'Phân tích video ngắn tại máy')
    html = html.replace('Theo dõi webcam với Pro', 'Thử webcam trong trình duyệt')
    html = html.replace('Cảnh báo về Telegram riêng', 'Telegram thuộc lộ trình tiếp theo')
    html = html.replace('Nhận ảnh cảnh báo trong Telegram riêng', 'Telegram riêng khi tính năng cảnh báo được phát hành')
    html = html.replace('Giai đoạn hiện tại: Admin tạo link payOS riêng cho từng đơn và đối soát giao dịch thật trước khi mở Pro.',
                        'Giai đoạn hiện tại: chưa mở yêu cầu Pro hoặc thanh toán trên hai trang Firebase.')
    html = html.replace('Đăng nhập Google để bắt đầu Free, sau đó kết nối bot LH25 tới chat Telegram của riêng bạn.',
                        'Đăng nhập Google để tạo tài khoản Free. Kết nối Telegram sẽ mở trong giai đoạn tiếp theo.')
    (OUTPUT / "static").mkdir(parents=True, exist_ok=True)
    (OUTPUT / "index.html").write_text(html, encoding="utf-8")
    for name in STATIC_ASSETS:
        shutil.copyfile(source / name, OUTPUT / "static" / name)
    for name in ("terms.html", "privacy.html"):
        legal = (ROOT / "hosting" / "firebase-spark" / "app" / name).read_text(encoding="utf-8")
        legal = legal.replace('href="/style.css"', 'href="/static/store.css"')
        (OUTPUT / name).write_text(legal, encoding="utf-8")
    expected = {"index.html", "terms.html", "privacy.html"} | {
        f"static/{name}" for name in STATIC_ASSETS
    }
    actual = {p.relative_to(OUTPUT).as_posix() for p in OUTPUT.rglob("*") if p.is_file()}
    if actual != expected:
        raise RuntimeError("Unexpected files in public output; do not deploy")
    assert '<form' not in html and '/api' not in html and 'store.js' not in html
    print(f"Public Store built: {len(expected)} allowlisted files; no registration/payment/API calls.")


if __name__ == "__main__":
    build()
