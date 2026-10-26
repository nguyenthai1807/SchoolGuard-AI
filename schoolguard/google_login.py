"""Opt-in Google identity login. Never link existing accounts by email alone."""
import os
import secrets
import re
import time
import threading
from collections import defaultdict, deque
from urllib.parse import urlparse, urlsplit

from fastapi import HTTPException, Request, Response
from pydantic import BaseModel, Field

from .auth import hash_password, make_session
from .commerce import valid_public_url
from .db import now
from .team_grants import redeem_verified_google_email


class GoogleLogin(BaseModel):
    credential: str = Field(min_length=20, max_length=10000)
    consent: bool = False


class GoogleVerificationUnavailable(Exception):
    """Google's public signing keys could not be reached."""


def verify_identity(credential, client_id):
    from google.auth.exceptions import TransportError
    from google.auth.transport.requests import Request as GoogleRequest
    from google.oauth2 import id_token
    import requests

    certs_url = 'https://www.googleapis.com/oauth2/v1/certs'

    class BoundedGoogleRequest(GoogleRequest):
        def __call__(self, *args, **kwargs):
            requested = kwargs.get('timeout')
            kwargs['timeout'] = 8 if requested is None else min(requested, 8)
            return super().__call__(*args, **kwargs)

    def blocked_local_proxy():
        proxy = requests.utils.select_proxy(
            certs_url, requests.utils.get_environ_proxies(certs_url))
        if not proxy:
            return False
        try:
            parsed = urlsplit(proxy)
            return parsed.hostname in {'127.0.0.1', 'localhost'} and parsed.port == 9
        except ValueError:
            return False

    try:
        return id_token.verify_oauth2_token(credential, BoundedGoogleRequest(), client_id)
    except TransportError as exc:
        # Explicitly opt in for local development only. Never silently bypass
        # a configured proxy in a hosted/commercial deployment.
        direct_retry = os.getenv('LH25_GOOGLE_DIRECT_CERT_RETRY') == '1'
        if (direct_retry and isinstance(exc.__cause__, requests.exceptions.ProxyError)
                and blocked_local_proxy()):
            with requests.Session() as direct:
                direct.trust_env = False
                direct.verify = (os.getenv('REQUESTS_CA_BUNDLE')
                                 or os.getenv('CURL_CA_BUNDLE') or True)
                try:
                    return id_token.verify_oauth2_token(
                        credential, BoundedGoogleRequest(session=direct), client_id)
                except TransportError as retry_exc:
                    raise GoogleVerificationUnavailable from retry_exc
        raise GoogleVerificationUnavailable from exc


def _allowed_host(request, settings):
    """Do not advertise a localhost OAuth client on temporary public tunnels."""
    hostname = request.url.hostname
    if hostname in {"127.0.0.1", "localhost", "testserver"}:
        return True
    public_url = settings.public_base_url
    return (valid_public_url(public_url)
            and hostname == urlparse(public_url).hostname
            and (request.url.scheme == "https"
                 or request.headers.get("x-forwarded-proto") == "https"))


def install_google_login(app, db, settings):
    attempts = defaultdict(deque)
    lock = threading.Lock()
    with db.connect() as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS google_identities ("
                     "subject TEXT PRIMARY KEY, user_id INTEGER UNIQUE NOT NULL REFERENCES users(id))")

    @app.get('/api/auth/google/config')
    def config(request: Request, response: Response):
        client_id = settings.google_client_id
        if not client_id or not _allowed_host(request, settings):
            return {'enabled': False, 'google_only': settings.google_only}
        # A browser may have several LH25 tabs. Reuse the short-lived challenge
        # so loading another tab does not invalidate an in-progress Google popup.
        previous = request.cookies.get('lh25_google_nonce', '')
        nonce = previous if re.fullmatch(r'[A-Za-z0-9_-]{43}', previous) else secrets.token_urlsafe(32)
        response.set_cookie('lh25_google_nonce', nonce, httponly=True,
                            secure=request.url.scheme == 'https' or request.headers.get('x-forwarded-proto') == 'https',
                            samesite='strict', max_age=300)
        response.headers['Cache-Control'] = 'no-store'
        return {'enabled': True, 'google_only': settings.google_only,
                'client_id': client_id, 'nonce': nonce}

    @app.post('/api/auth/google')
    def login(payload: GoogleLogin, request: Request, response: Response):
        if not settings.google_client_id:
            raise HTTPException(503, 'Đăng nhập Google chưa được cấu hình.')
        if not _allowed_host(request, settings):
            raise HTTPException(403, 'Google chỉ mở tại địa chỉ đã được cấu hình.')
        key = request.client.host if request.client else 'local'
        with lock:
            queue = attempts[key]
            while queue and queue[0] < time.monotonic() - 60:
                queue.popleft()
            if len(queue) >= 8:
                raise HTTPException(429, 'Thử lại sau một phút.')
            queue.append(time.monotonic())
        # Explicit same-origin fetch plus HttpOnly challenge prevents login CSRF.
        if request.headers.get('origin') != str(request.base_url).rstrip('/'):
            raise HTTPException(403, 'Nguồn đăng nhập không hợp lệ.')
        nonce = request.cookies.get('lh25_google_nonce', '')
        if not nonce:
            raise HTTPException(403, 'Hãy tải lại trang đăng nhập.')
        try:
            claims = verify_identity(payload.credential, settings.google_client_id)
        except ImportError as exc:
            raise HTTPException(503, 'Máy chủ chưa cài thư viện xác minh Google.') from exc
        except GoogleVerificationUnavailable as exc:
            raise HTTPException(503, 'Máy chủ không kết nối được Google để xác minh. Vui lòng thử lại sau.') from exc
        except Exception as exc:
            raise HTTPException(401, 'Không xác minh được tài khoản Google.') from exc
        if not claims.get('sub') or not claims.get('email_verified') or not claims.get('email'):
            raise HTTPException(401, 'Tài khoản Google chưa cung cấp email đã xác minh.')
        if not secrets.compare_digest(str(claims.get('nonce', '')), nonce):
            raise HTTPException(401, 'Phiên đăng nhập Google đã thay đổi. Tải lại trang và thử lại.')
        subject = str(claims['sub'])
        email = str(claims['email']).lower()
        # Stable, verified Google subject IDs only; never frontend role or email.
        allowed_role = 'admin' if subject in settings.google_admin_subjects else 'operator'
        with db.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            row = conn.execute('SELECT u.* FROM google_identities g JOIN users u ON u.id=g.user_id WHERE g.subject=?', (subject,)).fetchone()
            if not row:
                if not payload.consent:
                    raise HTTPException(409, 'Đồng ý điều khoản dữ liệu trước khi tạo tài khoản.')
                if conn.execute('SELECT 1 FROM customer_profiles WHERE lower(email)=?', (email,)).fetchone():
                    raise HTTPException(409, 'Email đã có tài khoản. Đăng nhập tài khoản cũ để liên hệ hỗ trợ liên kết Google.')
                username = 'google_' + secrets.token_hex(12)
                uid = conn.execute("INSERT INTO users(username,password,role) VALUES(?,?,'operator')", (username, hash_password(secrets.token_urlsafe(48)))).lastrowid
                conn.execute('INSERT INTO google_identities(subject,user_id) VALUES(?,?)', (subject, uid))
                conn.execute("INSERT INTO customer_profiles(user_id,display_name,email,phone,updated_at) VALUES(?,?,?,'',?)", (uid, str(claims.get('name', 'Khách LH25'))[:100], email, now()))
                conn.execute("INSERT INTO subscriptions(user_id,plan,expires_at,source,updated_at) VALUES(?,'free',NULL,'google_registration',?)", (uid, now()))
                conn.execute('INSERT INTO email_verifications(user_id,email,verified_at) VALUES(?,?,?)', (uid, email, now()))
                row = {'id': uid, 'username': username, 'role': 'operator'}
            conn.execute('UPDATE users SET role=? WHERE id=?', (allowed_role, row['id']))
            if allowed_role != 'admin':
                redeem_verified_google_email(conn, email, row['id'])
            row = dict(row)
            row['role'] = allowed_role
        token = make_session(db, row['id'])
        response.set_cookie('sg_session', token, httponly=True, samesite='strict',
                            secure=request.url.scheme == 'https' or request.headers.get('x-forwarded-proto') == 'https', max_age=8 * 3600)
        response.delete_cookie('lh25_google_nonce')
        db.audit(row['id'], 'google_login', str(row['id']))
        return {'id': row['id'], 'username': row['username'], 'role': row['role']}
