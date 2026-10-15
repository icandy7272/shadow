import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from shadow.web import auth

ORIGIN = 'https://shadow.test'
PASSWORD = '012345'


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv('SHADOW_DATA_DIR', str(tmp_path))
    app = FastAPI()
    auth.register_auth(app, None)
    @app.get('/api/private')
    def private():
        return {'secret': True}
    @app.get('/media/audio.wav')
    def media():
        return {'audio': True}
    @app.get('/practice')
    def practice():
        return {'ok': True}
    return TestClient(app, base_url=ORIGIN)


def setup():
    auth.initialize(ORIGIN, PASSWORD)


def login(client):
    return client.post('/api/auth/password', json={'password': PASSWORD}, headers={'Origin': ORIGIN})


def post(client, path, data=None):
    return client.post('/api/auth/' + path, json=data or {}, headers={'Origin': ORIGIN})


def test_disabled_and_private_store(client):
    assert client.get('/api/private').status_code == 200
    assert client.get('/api/auth/status').json()['enabled'] is False
    setup()
    assert (auth.config.data_dir() / 'auth.sqlite3').stat().st_mode & 0o777 == 0o600
    assert client.get('/api/private').status_code == 401
    assert client.get('/media/audio.wav').status_code == 401
    assert client.get('/practice?a=1', follow_redirects=False).headers['location'] == '/login?next=%2Fpractice%3Fa%3D1'


def test_password_cookie_origin_and_expiry(client):
    setup()
    assert client.post('/api/auth/password', json={'password': PASSWORD}).status_code == 403
    assert client.post('/api/auth/password', json={'password': PASSWORD}, headers={'Origin': 'https://evil.test'}).status_code == 403
    response = login(client)
    assert response.status_code == 200
    cookie = response.headers['set-cookie']
    assert all(value in cookie for value in ('HttpOnly', 'Secure', 'SameSite=lax', 'Max-Age=7776000'))
    assert client.get('/api/private').status_code == 200
    with auth.connect() as db:
        db.execute('UPDATE sessions SET expires=?', (time.time()-1,))
    assert client.get('/api/private').status_code == 401


def test_pairing_single_use_and_recent(client):
    setup()
    assert post(client, 'device-code').status_code == 401
    login(client)
    result = post(client, 'device-code').json()
    assert result['url'].endswith('#device=' + result['code'])
    assert '<svg' in result['qr_svg']
    assert post(client, 'device-redeem', {'code': result['code']}).status_code == 200
    assert post(client, 'device-redeem', {'code': result['code']}).status_code == 401
    with auth.connect() as db:
        db.execute('UPDATE sessions SET authenticated=?', (time.time()-301,))
    assert post(client, 'device-code').status_code == 403
    assert post(client, 'passkey/options', {'mode': 'register'}).status_code == 403
    assert post(client, 'logout', {'all': True}).status_code == 403


def test_logout_all_and_reset(client):
    setup()
    login(client)
    old_cookie = client.cookies.get(auth.COOKIE)
    assert post(client, 'logout', {'all': True}).status_code == 200
    client.cookies.set(auth.COOKIE, old_cookie)
    assert client.get('/api/private').status_code == 401
    login(client)
    auth.initialize(ORIGIN, '654321', reset=True)
    assert client.get('/api/private').status_code == 401


def test_ceremony_single_attempt_and_no_anonymous_registration(client):
    setup()
    assert post(client, 'passkey/options', {'mode': 'register'}).status_code == 401
    result = post(client, 'passkey/options', {'mode': 'login'}).json()
    assert result['options']['userVerification'] == 'required'
    data = {'cid': result['cid'], 'credential': {}}
    assert post(client, 'passkey/verify', data).status_code == 400
    assert post(client, 'passkey/verify', data).json()['detail'].startswith('Ceremony expired')
    login(client)
    result = post(client, 'passkey/options', {'mode': 'register'}).json()
    assert result['options']['authenticatorSelection']['residentKey'] == 'required'


def test_rate_limit_and_safe_next(client):
    setup()
    for _ in range(10):
        assert post(client, 'password', {'password': 'wrong'}).status_code == 401
    assert login(client).status_code == 429
    for value in ('//evil.test', '/\\evil.test', '/\nfoo', 'https://evil.test'):
        assert auth.safe_next(value) == '/'
    assert auth.safe_next('/practice?a=1') == '/practice?a=1'


@pytest.mark.parametrize('origin', ['http://shadow.test', 'https://user@shadow.test', 'https://shadow.test/path', 'https://shadow.test?x=1'])
def test_origin_validation(origin):
    with pytest.raises(ValueError):
        auth.canonical_origin(origin)


def test_cli_setup_and_reset(client, monkeypatch):
    from shadow import cli
    monkeypatch.setattr('getpass.getpass', lambda prompt: PASSWORD)
    assert cli.main(['auth', 'setup', '--origin', ORIGIN]) == 0
    assert cli.main(['auth', 'setup', '--origin', ORIGIN]) == 1
    assert login(client).status_code == 200
    assert cli.main(['auth', 'reset', '--origin', ORIGIN]) == 0
    assert client.get('/api/private').status_code == 401


def test_real_signed_passkey_registration_and_login(client):
    """A real ES256 signature exercises library RP/origin/challenge/UV checks."""
    import base64
    import hashlib
    import json
    import cbor2
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives import hashes

    def encode(value):
        return base64.urlsafe_b64encode(value).rstrip(b'=').decode()

    setup()
    login(client)
    private = ec.generate_private_key(ec.SECP256R1())
    numbers = private.public_key().public_numbers()
    cose = cbor2.dumps({1: 2, 3: -7, -1: 1, -2: numbers.x.to_bytes(32, 'big'), -3: numbers.y.to_bytes(32, 'big')})
    credential_id = b'shadow-test-credential'
    rp_hash = hashlib.sha256(b'shadow.test').digest()
    options = post(client, 'passkey/options', {'mode': 'register'}).json()
    client_data = json.dumps({'type': 'webauthn.create', 'challenge': options['options']['challenge'], 'origin': ORIGIN}).encode()
    auth_data = rp_hash + bytes([0x45]) + (0).to_bytes(4, 'big') + bytes(16) + len(credential_id).to_bytes(2, 'big') + credential_id + cose
    attestation = cbor2.dumps({'fmt': 'none', 'attStmt': {}, 'authData': auth_data})
    registration = {'id': encode(credential_id), 'rawId': encode(credential_id), 'type': 'public-key', 'response': {'clientDataJSON': encode(client_data), 'attestationObject': encode(attestation)}}
    assert post(client, 'passkey/verify', {'cid': options['cid'], 'credential': registration, 'name': 'Test key'}).status_code == 200
    assert client.get('/api/auth/status').json()['passkeys'] == [{'id': encode(credential_id), 'name': 'Test key'}]
    repeated = post(client, 'passkey/options', {'mode': 'register'}).json()
    assert repeated['options']['excludeCredentials'][0]['id'] == encode(credential_id)
    post(client, 'logout')

    def assertion(options, *, origin=ORIGIN, flags=5, counter=1):
        data = json.dumps({'type': 'webauthn.get', 'challenge': options['options']['challenge'], 'origin': origin}).encode()
        authenticator = rp_hash + bytes([flags]) + counter.to_bytes(4, 'big')
        signature = private.sign(authenticator + hashlib.sha256(data).digest(), ec.ECDSA(hashes.SHA256()))
        with auth.connect() as db:
            handle = bytes.fromhex(auth.settings(db)['user'])
        return {'id': encode(credential_id), 'rawId': encode(credential_id), 'type': 'public-key', 'response': {'clientDataJSON': encode(data), 'authenticatorData': encode(authenticator), 'signature': encode(signature), 'userHandle': encode(handle)}}

    for changes in ({'origin': 'https://evil.test'}, {'flags': 1}):
        options = post(client, 'passkey/options').json()
        assert post(client, 'passkey/verify', {'cid': options['cid'], 'credential': assertion(options, **changes)}).status_code == 400
    options = post(client, 'passkey/options').json()
    assert post(client, 'passkey/verify', {'cid': options['cid'], 'credential': assertion(options)}).status_code == 200
    assert client.get('/api/private').status_code == 200
    options = post(client, 'passkey/options').json()
    assert post(client, 'passkey/verify', {'cid': options['cid'], 'credential': assertion(options)}).status_code == 400


def test_expired_device_code_and_challenge(client):
    setup()
    login(client)
    code = post(client, 'device-code').json()['code']
    challenge = post(client, 'passkey/options').json()['cid']
    with auth.connect() as db:
        db.execute('UPDATE codes SET expires=?', (time.time()-1,))
        db.execute('UPDATE challenges SET expires=?', (time.time()-1,))
    assert post(client, 'device-redeem', {'code': code}).status_code == 401
    assert post(client, 'passkey/verify', {'cid': challenge, 'credential': {}}).status_code == 400


def test_registration_challenge_is_bound_to_issuing_session(client):
    setup()
    login(client)
    challenge = post(client, 'passkey/options', {'mode': 'register'}).json()['cid']
    login(client)  # A distinct, recently authenticated browser/session still cannot borrow it.
    result = post(client, 'passkey/verify', {'cid': challenge, 'credential': {}})
    assert result.status_code == 403
    assert 'another session' in result.json()['detail']


@pytest.mark.parametrize('path', ['/audio/1', '/take/1', '/talk/audio/1'])
def test_audio_prefix_returns_machine_readable_expiry(client, path):
    setup()
    response = client.get(path, follow_redirects=False)
    assert response.status_code == 401
    assert response.json()['detail'] == 'Please sign in.'


def test_auth_body_limit(client):
    setup()
    response = client.post('/api/auth/password', content=b'"' + b'x' * (128 * 1024) + b'"', headers={'Origin': ORIGIN, 'Content-Type': 'application/json'})
    assert response.status_code == 413
    assert login(client).status_code == 200


def test_password_verification_cannot_issue_session_across_cli_reset(client, monkeypatch):
    setup()
    original = auth.hashlib.scrypt
    reset_once = False

    def interrupted(*args, **kwargs):
        nonlocal reset_once
        result = original(*args, **kwargs)
        if not reset_once:
            reset_once = True
            auth.initialize(ORIGIN, '654321', reset=True)
        return result

    monkeypatch.setattr(auth.hashlib, 'scrypt', interrupted)
    assert login(client).status_code == 401
    with auth.connect() as db:
        assert db.execute('SELECT count(*) FROM sessions').fetchone()[0] == 0
    assert post(client, 'password', {'password': '654321'}).status_code == 200


def test_logout_all_fences_inflight_password_without_changing_passkey_user(client, monkeypatch):
    setup()
    login(client)
    with auth.connect() as db:
        user = auth.settings(db)['user']
    original = auth.hashlib.scrypt
    logout_once = False

    def interrupted(*args, **kwargs):
        nonlocal logout_once
        result = original(*args, **kwargs)
        if not logout_once:
            logout_once = True
            assert post(client, 'logout', {'all': True}).status_code == 200
        return result

    monkeypatch.setattr(auth.hashlib, 'scrypt', interrupted)
    assert login(client).status_code == 401
    with auth.connect() as db:
        assert auth.settings(db)['user'] == user
        assert db.execute('SELECT count(*) FROM sessions').fetchone()[0] == 0
    assert login(client).status_code == 200


@pytest.mark.parametrize('value', ['', '12345', '1234567', 'abcdef', '１２３４５６', '12345 ', '123.45'])
def test_backup_pin_requires_exactly_six_ascii_digits(client, value):
    with pytest.raises(ValueError, match='6'):
        auth.initialize(ORIGIN, value)


def test_backup_pin_preserves_leading_zero(client):
    setup()
    assert login(client).status_code == 200
    assert post(client, 'password', {'password': '12345'}).status_code == 401
