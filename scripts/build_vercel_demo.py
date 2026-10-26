"""Build an allowlisted, non-commercial LH25 preview for static hosting.

The output is deliberately separate from the application and never contains
its API, database, model weights, credentials, videos, or checkout flow.
"""

from pathlib import Path
import json
import re
import shutil


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "schoolguard" / "static"
OUTPUT = ROOT / "hosting" / "vercel-demo"

ASSETS = {
    "brand-lh25-original.jpg",
    "brand.css",
    "child-home-observation.png",
    "elderly-home-fall-feature.png",
    "store-group-consented.webp",
    "store-ribbon.css",
    "store.css",
    "yolo-person-illustration.webp",
    "yolo-pose-illustration.webp",
}


def render_html():
    html = (SOURCE / "store.html").read_text(encoding="utf-8")
    marker = '<section id="pricing"'
    if html.count(marker) != 1:
        raise RuntimeError("Store structure changed; review the demo builder")
    html = html.split(marker, 1)[0]
    html, shots_count = re.subn(
        r'<section id="product-shots".*?</section>', "", html, flags=re.DOTALL)
    if shots_count != 1:
        raise RuntimeError("Product screenshots changed; review the demo builder")
    html = re.sub(r"\s*<script\b[^>]*>.*?</script>", "", html, flags=re.DOTALL)
    html, picker_count = re.subn(
        r'<label class="language-picker">.*?</label>', "", html, flags=re.DOTALL)
    if picker_count != 1:
        raise RuntimeError("Language picker changed; review the demo builder")
    html = re.sub(r'<img class="store-logo-word"[^>]*>', "", html)
    html = re.sub(
        r'<meta name="description" content="[^"]*">',
        '<meta name="description" content="Bản demo học thuật phi thương mại của LH25. Không nhận đăng ký, thanh toán hoặc video.">',
        html,
    )
    html = html.replace("LH25 STORE", "LH25 DEMO")
    html = html.replace("An tâm bắt đầu từ những điều thấy được", "Trình diễn nghiên cứu")
    html = html.replace("Điều hướng trang bán hàng", "Điều hướng bản demo")
    html = html.replace(
        'LH25 đang trong giai đoạn thử nghiệm tại nhà <span class="announcement-extra"><span class="announcement-divider">/</span> Dữ liệu phân tích trên máy chạy ứng dụng</span>',
        'DEMO HỌC THUẬT · KHÔNG NHẬN ĐĂNG KÝ HAY THANH TOÁN',
    )
    html = html.replace("DÙNG THỬ", "BẢN DEMO")
    html = html.replace("href=\"/store\"", "href=\"/\"")
    html = html.replace("href=\"/#overview\"", "href=\"#status\"")
    html = html.replace("href=\"#start\"", "href=\"#status\"")
    html = html.replace("href=\"#pricing\"", "href=\"#status\"")
    html = html.replace("href=\"#faq\"", "href=\"#status\"")
    html = html.replace("Vào ứng dụng", "Trạng thái demo")
    html = html.replace("Gói dịch vụ", "Trạng thái demo")
    html = html.replace('<a href="#status">Hỏi đáp</a>',
                        '<a href="#yolo-examples">Đầu ra YOLO</a>')
    html = html.replace("Bắt đầu với Free", "Xem trạng thái demo")
    html = html.replace("Theo dõi webcam với Pro", "Minh họa theo dõi webcam")
    html = html.replace("Đăng nhập Google để bắt đầu Free, sau đó kết nối bot LH25 tới chat Telegram của riêng bạn.",
                        "Trong bản chạy thử nội bộ, người dùng đăng nhập Google và kết nối Telegram riêng.")
    html = html.replace("Free dùng video; Pro Local có thêm webcam. Bạn đặt mức người thường có trong khung hình.",
                        "Bản chạy thử nội bộ hỗ trợ video và webcam; người dùng đặt mức người thường có trong khung hình.")
    html = html.replace("YOLO8n / PERSON · FREE", "YOLO8n / PERSON · DEMO")
    html = html.replace("YOLO8n POSE · FREE", "YOLO8n POSE · DEMO")
    html += '''
    <section id="status" class="section wrap pricing" aria-labelledby="status-title">
      <div class="section-heading"><span class="overline">BẢN XEM TRƯỚC HỌC THUẬT</span>
        <h2 id="status-title">LH25 hiện chạy thử trên máy của nhóm.</h2>
        <p>Đây là trang tĩnh để trình bày giao diện và hướng nghiên cứu, không phải dịch vụ đang mở cho khách hàng. Trang không nhận đăng ký, video, thanh toán hay dữ liệu cá nhân; không có kết nối đến máy chủ LH25.</p>
        <p>Hình ảnh người trong demo do nhóm cung cấp. Khung người và ảnh minh họa chỉ mô tả đầu ra trên mẫu; không chứng minh độ chính xác ngoài thực tế. AI có thể báo sai hoặc bỏ sót.</p>
      </div>
    </section>
  </main>
  <footer class="footer"><div class="wrap footer-bottom"><span>© LH25 · Demo nghiên cứu phi thương mại</span><span>Không phải thiết bị an toàn được chứng nhận.</span></div></footer>
</body>
</html>
'''
    forbidden = ("<form", "<script", "/api", "payos", "49.000", "29.000", "chuyển khoản",
                 "checkout", "đăng ký ngay", "href=\"/#overview\"")
    if any(token in html.lower() for token in forbidden):
        raise RuntimeError("Demo still contains an interactive or commercial element")
    referenced = set(re.findall(r'(?:src|href)="/static/([^"?]+)', html))
    if not referenced <= ASSETS:
        raise RuntimeError(f"Unreviewed assets in demo: {sorted(referenced - ASSETS)}")
    return html, referenced


def build(output=OUTPUT):
    html, referenced = render_html()
    output = Path(output)
    expected = {"index.html", "vercel.json"} | {f"static/{name}" for name in referenced}
    if output.exists():
        existing = {p.relative_to(output).as_posix() for p in output.rglob("*") if p.is_file()}
        if existing - expected:
            raise RuntimeError(f"Unexpected existing output files: {sorted(existing - expected)}")
    (output / "static").mkdir(parents=True, exist_ok=True)
    (output / "index.html").write_text(html, encoding="utf-8")
    for name in sorted(referenced):
        shutil.copyfile(SOURCE / name, output / "static" / name)
    config = {
        "version": 2,
        "cleanUrls": True,
        "headers": [{"source": "/(.*)", "headers": [
            {"key": "Content-Security-Policy", "value":
             "default-src 'none'; style-src 'self'; img-src 'self' data:; "
             "font-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"},
            {"key": "X-Content-Type-Options", "value": "nosniff"},
            {"key": "Referrer-Policy", "value": "no-referrer"},
            {"key": "X-Robots-Tag", "value": "noindex, nofollow"},
        ]}],
    }
    (output / "vercel.json").write_text(
        json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    actual = {p.relative_to(output).as_posix() for p in output.rglob("*") if p.is_file()}
    if actual != expected:
        raise RuntimeError(f"Unexpected demo files: {sorted(actual ^ expected)}")
    print(f"Static LH25 demo ready: {len(actual)} allowlisted files in {output}")


if __name__ == "__main__":
    build()
