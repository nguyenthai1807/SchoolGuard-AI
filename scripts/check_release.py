"""Show setup gaps without printing any credentials or contacting payment APIs."""

import json
import sys

from schoolguard.commerce import PayOSGateway, SmtpEmailSender
from schoolguard.config import Settings
from schoolguard.release import release_report


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    report = release_report(Settings(), PayOSGateway().available, SmtpEmailSender().available)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
