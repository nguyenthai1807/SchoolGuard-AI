"""Show chat IDs seen by a local Telegram bot without printing its token."""

import os

import requests

from schoolguard.config import load_local_env


def main():
    load_local_env()
    token = os.getenv("LH25_TELEGRAM_BOT_TOKEN", "")
    if not token:
        print("Chưa đặt LH25_TELEGRAM_BOT_TOKEN trong .env.")
        return
    try:
        response = requests.get(
            f"https://api.telegram.org/bot{token}/getUpdates",
            params={"limit": 20, "timeout": 0}, timeout=(5, 10),
        )
        response.raise_for_status()
        payload = response.json()
        if not payload.get("ok"):
            print("Telegram từ chối yêu cầu; kiểm tra token và webhook.")
            return
        chats = {str(item[key]["chat"]["id"])
                 for item in payload.get("result", [])
                 for key in ("message", "edited_message", "channel_post")
                 if key in item and "chat" in item[key]}
        if chats:
            print("Chat ID đã thấy: " + ", ".join(sorted(chats)))
        else:
            print("Chưa thấy chat ID. Hãy gửi /start cho bot rồi chạy lại.")
    except (requests.RequestException, ValueError):
        print("Không đọc được getUpdates. Kiểm tra mạng, token và webhook; token không được in ra.")


if __name__ == "__main__":
    main()
