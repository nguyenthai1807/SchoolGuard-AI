import hashlib
import hmac
import os
import secrets
import time


def hash_password(password):
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=16384, r=8, p=1)
    return salt.hex() + ":" + digest.hex()


def verify_password(password, stored):
    salt, expected = stored.split(":")
    got = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1)
    return hmac.compare_digest(got.hex(), expected)


def token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def bootstrap(db, runtime):
    if not db.one("SELECT id FROM users LIMIT 1"):
        password = os.getenv("LH25_ADMIN_PASSWORD") or os.getenv("SCHOOLGUARD_ADMIN_PASSWORD")
        if not password or password.startswith("replace-with-"):
            password = secrets.token_urlsafe(18)
            (runtime / "admin-password.txt").write_text(password, encoding="utf-8")
        db.execute(
            "INSERT INTO users(username,password,role) VALUES(?,?,?)",
            ("admin", hash_password(password), "admin"),
        )


def make_session(db, user_id):
    token = secrets.token_urlsafe(32)
    db.execute("DELETE FROM sessions WHERE expires < ?", (time.time(),))
    db.execute(
        "INSERT INTO sessions VALUES(?,?,?)", (token_hash(token), user_id, time.time() + 8 * 3600)
    )
    return token
