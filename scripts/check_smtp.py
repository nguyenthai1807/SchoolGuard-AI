"""Validate email configuration; --connect tests login but sends no email."""

import argparse
import json

from schoolguard.config import Settings
from schoolguard.commerce import SmtpEmailSender


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--connect", action="store_true")
    args = parser.parse_args()
    Settings()
    sender = SmtpEmailSender()
    if not sender.available:
        print(json.dumps({"configured": False, "login_verified": False, "email_sent": False}))
        return
    if not args.connect:
        print(json.dumps({"configured": True, "login_verified": False, "email_sent": False}))
        return
    try:
        sender.check_connection()
    except Exception:
        print(json.dumps({"configured": True, "login_verified": False, "email_sent": False}))
        raise SystemExit(1)
    print(json.dumps({"configured": True, "login_verified": True, "email_sent": False}))


if __name__ == "__main__":
    main()
