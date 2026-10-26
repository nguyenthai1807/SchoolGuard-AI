"""Plan or register this installation's fixed HTTPS callback without creating payments."""

import argparse
import json
import sys

from schoolguard.commerce import PayOSGateway, valid_public_url
from schoolguard.config import Settings


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("--register", action="store_true", help="Register the configured URL with payOS")
    args = parser.parse_args()
    settings, gateway = Settings(), PayOSGateway()
    ready = gateway.available and valid_public_url(settings.public_base_url)
    if not args.register:
        print(json.dumps({"ready_to_register": ready, "keys_present": gateway.available,
                          "https_url_configured": valid_public_url(settings.public_base_url),
                          "webhook_url": settings.public_base_url.rstrip("/") + "/api/payments/payos/webhook"
                          if valid_public_url(settings.public_base_url) else None,
                          "action": "plan_only"}, ensure_ascii=False, indent=2))
        return
    if not ready:
        parser.error("Cần LH25_PUBLIC_BASE_URL là URL HTTPS cố định và đủ khóa payOS.")
    try:
        url = gateway.register_webhook(settings.public_base_url)
    except Exception:
        print("Đăng ký chưa thành công. Kiểm tra HTTPS và máy chủ webhook. Không tạo giao dịch.")
        raise SystemExit(1)
    print(json.dumps({"registered": True, "webhook_url": url}, ensure_ascii=False))


if __name__ == "__main__":
    main()
