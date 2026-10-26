from fastapi.testclient import TestClient
import schoolguard.google_login as google_login
import pytest


def configured(app, monkeypatch, **overrides):
    app.state.settings.google_client_id = 'test.apps.googleusercontent.com'
    customer = TestClient(app)
    nonce = customer.get('/api/auth/google/config').json()['nonce']
    claims = {'sub': 'google-sub-123', 'email': 'customer@gmail.com',
              'email_verified': True, 'name': 'Customer', 'nonce': nonce}
    claims.update(overrides)
    monkeypatch.setattr(google_login, 'verify_identity', lambda token, audience: claims)
    return customer


def login(customer, consent=True):
    return customer.post('/api/auth/google', headers={'Origin': 'http://testserver'},
                         json={'credential': 'test-credential-long-enough', 'consent': consent})


def test_disabled_google(app):
    app.state.settings.google_client_id = ''
    assert TestClient(app).get('/api/auth/google/config').json() == {
        'enabled': False, 'google_only': False}


def test_local_oauth_client_is_not_offered_on_temporary_tunnel(app):
    app.state.settings.google_client_id = 'test.apps.googleusercontent.com'
    with TestClient(app, base_url='https://pilot.trycloudflare.com') as visitor:
        assert visitor.get('/api/auth/google/config').json() == {
            'enabled': False, 'google_only': False}
        assert visitor.post('/api/auth/google',
                            headers={'Origin': 'https://pilot.trycloudflare.com'},
                            json={'credential': 'test-credential-long-enough',
                                  'consent': True}).status_code == 403


def test_google_local_referrer_policy_keeps_public_policy_strict(app):
    app.state.settings.google_client_id = 'test.apps.googleusercontent.com'
    with TestClient(app, base_url='http://127.0.0.1:8770') as visitor:
        assert visitor.get('/store').headers['referrer-policy'] == 'no-referrer-when-downgrade'
    with TestClient(app, base_url='https://pilot.trycloudflare.com') as visitor:
        assert visitor.get('/store').headers['referrer-policy'] == 'same-origin'


def test_admin_has_separate_sign_in_page(app):
    visitor = TestClient(app, follow_redirects=False)
    response = visitor.get('/admin')
    assert response.status_code == 303
    assert response.headers['location'] == '/admin/login'
    login_page = visitor.get('/admin/login')
    assert login_page.status_code == 200
    assert 'data-require-admin="true"' in login_page.text


def test_google_only_rejects_password_flows_and_legacy_sessions(app, monkeypatch):
    with TestClient(app) as local_admin:
        password = (app.state.settings.runtime / 'admin-password.txt').read_text()
        assert local_admin.post('/api/login', json={
            'username': 'admin', 'password': password}).status_code == 200
        app.state.settings.google_client_id = 'test.apps.googleusercontent.com'
        app.state.settings.google_admin_subjects = ('trusted-admin-sub',)
        app.state.settings.google_only = True
        assert local_admin.post('/api/login', json={
            'username': 'admin', 'password': 'anything'}).status_code == 403
        assert local_admin.post('/api/register', json={
            'username': 'new-user', 'password': 'long-password-123',
            'display_name': 'New user', 'email': 'new@example.test', 'consent': True,
        }).status_code == 403
        assert local_admin.get('/api/me').status_code == 401
        customer = configured(app, monkeypatch)
        assert login(customer).status_code == 200
        assert customer.get('/api/me').status_code == 200


def test_google_creates_free_not_admin(app, monkeypatch):
    customer = configured(app, monkeypatch)
    response = login(customer)
    assert response.status_code == 200, response.text
    assert response.json()['role'] == 'operator'
    assert customer.get('/api/me/plan').json()['plan'] == 'free'
    assert customer.get('/api/me/google-identity').json() == {
        'linked': True, 'subject': 'google-sub-123'}
    assert customer.get('/api/admin/orders').status_code == 403
    assert 'httponly' in response.headers['set-cookie'].lower()
    # Nonce consumed; replay with browser's remaining cookies fails.
    assert login(customer).status_code == 403


def test_google_requires_consent(app, monkeypatch):
    assert login(configured(app, monkeypatch), consent=False).status_code == 409


def test_google_rejects_nonce_and_unverified_email(app, monkeypatch):
    wrong_nonce = login(configured(app, monkeypatch, nonce='wrong'))
    assert wrong_nonce.status_code == 401
    assert 'Phiên đăng nhập Google' in wrong_nonce.json()['detail']
    unverified = login(configured(app, monkeypatch, email_verified=False))
    assert unverified.status_code == 401
    assert 'email đã xác minh' in unverified.json()['detail']


def test_google_config_reuses_nonce_across_tabs(app, monkeypatch):
    app.state.settings.google_client_id = 'test.apps.googleusercontent.com'
    browser = TestClient(app)
    first = browser.get('/api/auth/google/config').json()['nonce']
    second = browser.get('/api/auth/google/config').json()['nonce']
    assert second == first
    monkeypatch.setattr(google_login, 'verify_identity', lambda token, audience: {
        'sub': 'second-google-account', 'email': 'second@gmail.com',
        'email_verified': True, 'name': 'Second account', 'nonce': first,
    })
    assert login(browser).status_code == 200
    assert browser.get('/api/auth/google/config').json()['nonce'] != first


def test_google_transport_failure_is_service_unavailable(app, monkeypatch):
    customer = configured(app, monkeypatch)

    def unavailable(_credential, _audience):
        raise google_login.GoogleVerificationUnavailable

    monkeypatch.setattr(google_login, 'verify_identity', unavailable)
    response = login(customer)
    assert response.status_code == 503
    assert 'không kết nối được Google' in response.json()['detail']


def test_google_cert_verification_retries_direct_for_broken_local_proxy(monkeypatch):
    from google.auth.exceptions import TransportError
    from google.oauth2 import id_token
    from requests.exceptions import ProxyError

    monkeypatch.setenv('HTTPS_PROXY', 'http://127.0.0.1:9')
    monkeypatch.setenv('LH25_GOOGLE_DIRECT_CERT_RETRY', '1')
    monkeypatch.setenv('REQUESTS_CA_BUNDLE', 'C:/test/ca.pem')
    monkeypatch.delenv('NO_PROXY', raising=False)
    monkeypatch.delenv('no_proxy', raising=False)
    attempts = []

    def verify(token, transport, audience):
        attempts.append((token, transport.session.trust_env,
                         transport.session.verify, audience))
        if len(attempts) == 1:
            try:
                raise ProxyError('unreachable local proxy')
            except ProxyError as exc:
                raise TransportError(exc) from exc
        return {'sub': 'verified-google-subject'}

    monkeypatch.setattr(id_token, 'verify_oauth2_token', verify)
    assert google_login.verify_identity('signed-id-token', 'client-id') == {
        'sub': 'verified-google-subject'}
    assert attempts == [('signed-id-token', True, True, 'client-id'),
                        ('signed-id-token', False, 'C:/test/ca.pem', 'client-id')]


def test_google_cert_request_timeout_is_bounded(monkeypatch):
    from google.auth.transport.requests import Request as GoogleRequest
    from google.oauth2 import id_token

    timeouts = []

    def fake_http(_self, _url, **kwargs):
        timeouts.append(kwargs['timeout'])
        return {'verified': True}

    monkeypatch.setattr(GoogleRequest, '__call__', fake_http)
    monkeypatch.setattr(id_token, 'verify_oauth2_token',
                        lambda _token, transport, _audience: transport(
                            'https://www.googleapis.com/oauth2/v1/certs', timeout=120))
    assert google_login.verify_identity('signed-id-token', 'client-id') == {
        'verified': True}
    assert timeouts == [8]


def test_google_does_not_bypass_nonlocal_proxy(monkeypatch):
    from google.auth.exceptions import TransportError
    from google.oauth2 import id_token
    from requests.exceptions import ProxyError

    monkeypatch.setenv('HTTPS_PROXY', 'http://proxy.example:8080')
    monkeypatch.setenv('LH25_GOOGLE_DIRECT_CERT_RETRY', '1')
    monkeypatch.delenv('NO_PROXY', raising=False)
    monkeypatch.delenv('no_proxy', raising=False)
    attempts = []

    def proxy_failure(_token, transport, _audience):
        attempts.append(transport.session.trust_env)
        try:
            raise ProxyError('corporate proxy unavailable')
        except ProxyError as exc:
            raise TransportError(exc) from exc

    monkeypatch.setattr(id_token, 'verify_oauth2_token', proxy_failure)
    with pytest.raises(google_login.GoogleVerificationUnavailable):
        google_login.verify_identity('signed-id-token', 'client-id')
    assert attempts == [True]


def test_google_does_not_bypass_local_proxy_without_explicit_opt_in(monkeypatch):
    from google.auth.exceptions import TransportError
    from google.oauth2 import id_token
    from requests.exceptions import ProxyError

    monkeypatch.setenv('HTTPS_PROXY', 'http://127.0.0.1:9')
    monkeypatch.delenv('LH25_GOOGLE_DIRECT_CERT_RETRY', raising=False)
    monkeypatch.delenv('NO_PROXY', raising=False)
    monkeypatch.delenv('no_proxy', raising=False)
    attempts = []

    def proxy_failure(_token, transport, _audience):
        attempts.append(transport.session.trust_env)
        try:
            raise ProxyError('blocked local proxy')
        except ProxyError as exc:
            raise TransportError(exc) from exc

    monkeypatch.setattr(id_token, 'verify_oauth2_token', proxy_failure)
    with pytest.raises(google_login.GoogleVerificationUnavailable):
        google_login.verify_identity('signed-id-token', 'client-id')
    assert attempts == [True]


def test_google_direct_retry_keeps_signature_and_transport_failures(monkeypatch):
    from google.auth.exceptions import TransportError
    from google.oauth2 import id_token
    from requests.exceptions import ProxyError

    monkeypatch.setenv('HTTPS_PROXY', 'http://127.0.0.1:9')
    monkeypatch.setenv('LH25_GOOGLE_DIRECT_CERT_RETRY', '1')
    monkeypatch.delenv('NO_PROXY', raising=False)
    monkeypatch.delenv('no_proxy', raising=False)
    attempts = []

    def proxy_then_invalid(_token, transport, _audience):
        attempts.append(transport.session.trust_env)
        if len(attempts) == 1:
            try:
                raise ProxyError('blocked local proxy')
            except ProxyError as exc:
                raise TransportError(exc) from exc
        raise ValueError('invalid signature')

    monkeypatch.setattr(id_token, 'verify_oauth2_token', proxy_then_invalid)
    with pytest.raises(ValueError, match='invalid signature'):
        google_login.verify_identity('signed-id-token', 'client-id')
    assert attempts == [True, False]

    attempts.clear()

    def proxy_then_transport(_token, transport, _audience):
        attempts.append(transport.session.trust_env)
        if len(attempts) == 1:
            try:
                raise ProxyError('blocked local proxy')
            except ProxyError as exc:
                raise TransportError(exc) from exc
        raise TransportError('direct connection failed')

    monkeypatch.setattr(id_token, 'verify_oauth2_token', proxy_then_transport)
    with pytest.raises(google_login.GoogleVerificationUnavailable):
        google_login.verify_identity('signed-id-token', 'client-id')
    assert attempts == [True, False]

    monkeypatch.setenv('HTTPS_PROXY', 'http://127.0.0.1:9')
    attempts.clear()

    def invalid_signature(_token, transport, _audience):
        attempts.append(transport.session.trust_env)
        raise ValueError('invalid signature')

    monkeypatch.setattr(id_token, 'verify_oauth2_token', invalid_signature)
    with pytest.raises(ValueError, match='invalid signature'):
        google_login.verify_identity('signed-id-token', 'client-id')
    assert attempts == [True]


def test_google_does_not_link_existing_email(app, monkeypatch):
    customer = configured(app, monkeypatch)
    response = customer.post('/api/register', json={'username': 'existing',
        'password': 'unique-password-1234', 'display_name': 'Existing',
        'email': 'customer@gmail.com', 'consent': True})
    assert response.status_code == 201
    assert login(customer).status_code == 409


def test_google_admin_requires_allowlisted_subject_and_revokes_live_session(app, monkeypatch):
    app.state.settings.google_admin_subjects = ('google-sub-123',)
    customer = configured(app, monkeypatch)
    response = login(customer)
    assert response.status_code == 200
    assert response.json()['role'] == 'admin'
    assert customer.get('/api/admin/orders').status_code == 200
    app.state.settings.google_admin_subjects = ()
    assert customer.get('/api/admin/orders').status_code == 403


def test_google_email_never_grants_admin(app, monkeypatch):
    app.state.settings.google_admin_subjects = ('some-other-subject',)
    customer = configured(app, monkeypatch, email='admin@gmail.com')
    assert login(customer).json()['role'] == 'operator'
