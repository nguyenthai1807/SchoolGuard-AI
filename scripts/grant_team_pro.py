"""Queue complimentary Pro for verified Google team accounts on this LH25 server.

Usage: python -m scripts.grant_team_pro email@example.com [more emails...]
"""

import argparse

from schoolguard.config import Settings
from schoolguard.db import Database
from schoolguard.team_grants import provision


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("emails", nargs="+", help="Verified Google emails to grant Pro")
    args = parser.parse_args()
    db = Database(Settings().runtime / "schoolguard.sqlite3")
    for email in dict.fromkeys(value.strip().lower() for value in args.emails):
        status = provision(db, email)
        print(f"{email}: {status}")


if __name__ == "__main__":
    main()
