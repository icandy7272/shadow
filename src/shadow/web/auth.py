"""Single-owner authentication. Secrets live separately from practice data."""
from __future__ import annotations

import base64
import hashlib
import hmac
import ipaddress
import json
import secrets
import sqlite3
import time
from contextlib import contextmanager
from urllib.parse import quote, urlsplit

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse

from .. import config

COOKIE = 'shadow_session'
RECENT_SECONDS = 300


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def safe_next(value: str | None) -> str:
    if not value or not value.startswith('/') or value.startswith('//') or '\\' in value or any(ord(c) < 32 for c in value):
        return '/'
    return value


def canonical_origin(value: str) -> str:
    parsed = urlsplit(value)
    host = parsed.hostname
    try:
        loopback = host == 'localhost' or ipaddress.ip_address(host or '').is_loopback
    except ValueError:
        loopback = host == 'localhost'
    if (not host or parsed.username or parsed.password or parsed.path not in ('', '/')
            or parsed.query or parsed.fragment or parsed.scheme not in ('http', 'https')
            or (parsed.scheme != 'https' and not loopback)):
        raise ValueError('Origin must be HTTPS (HTTP is allowed only on loopback).')
    # Accessing port validates malformed/non-numeric ports.
    port = parsed.port
    authority = f'[{host}]' if ':' in host else host
    if port and port != (443 if parsed.scheme == 'https' else 80):
        authority += f':{port}'
    return f'{parsed.scheme}://{authority}'


@contextmanager
def connect():
    folder = config.data_dir()
    if not folder.exists():
        folder.mkdir(mode=0o700, parents=True)
    path = folder / 'auth.sqlite3'
    # Create with restrictive permissions before sqlite can write sensitive data.
    import os
    fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
    os.close(fd)
    path.chmod(0o600)
    db = sqlite3.connect(path, timeout=10)
    db.row_factory = sqlite3.Row
    try:
        db.executescript('''
        CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY,expires REAL,authenticated REAL);
        CREATE TABLE IF NOT EXISTS passkeys(id TEXT PRIMARY KEY,name TEXT,key BLOB,counter INTEGER);
        CREATE TABLE IF NOT EXISTS challenges(id TEXT PRIMARY KEY,challenge BLOB,mode TEXT,session TEXT,expires REAL);
        CREATE TABLE IF NOT EXISTS codes(code TEXT PRIMARY KEY,expires REAL);
        CREATE TABLE IF NOT EXISTS limits(key TEXT PRIMARY KEY,count INTEGER,until REAL);
        ''')
        yield db
        db.commit()
    finally:
        db.close()


def settings(db):
    return {r['key']: r['value'] for r in db.execute('SELECT * FROM settings')}


def initialize(origin: str, password: str, *, reset: bool = False):
    origin = canonical_origin(origin)
    if not 12 <= len(password) <= 1024:
        raise ValueError('Backup password must contain 12–1024 characters.')
    salt = secrets.token_bytes(16)
    hashed = hashlib.scrypt(password.encode(), salt=salt, n=16384, r=8, p=1)
    with connect() as db:
        if settings(db) and not reset:
            raise ValueError('Authentication is already initialized; use auth reset.')
        db.execute('BEGIN IMMEDIATE')
        for table in ('settings', 'sessions', 'passkeys', 'challenges', 'codes', 'limits'):
            db.execute(f'DELETE FROM {table}')
        db.executemany('INSERT INTO settings VALUES (?,?)', [
            ('origin', origin), ('password', salt.hex() + ':' + hashed.hex()),
            ('user', secrets.token_hex(32)), ('epoch', secrets.token_hex(32))])


def limited(db, key: str, maximum: int = 10, seconds: int = 600):
    now = time.time()
    db.execute('DELETE FROM limits WHERE until < ?', (now,))
    row = db.execute('SELECT * FROM limits WHERE key=?', (key,)).fetchone()
    if row and row['count'] >= maximum:
        raise HTTPException(429, 'Too many attempts. Try again later.')
    db.execute('INSERT INTO limits VALUES (?,1,?) ON CONFLICT(key) DO UPDATE SET count=count+1', (key, now + seconds))
    db.commit()  # Failed authentication must still count.


def session(db, request):
    token = request.cookies.get(COOKIE, '')
    return db.execute('SELECT * FROM sessions WHERE token=? AND expires>?', (digest(token), time.time())).fetchone() if token else None


def require_session(db, request, *, recent=False):
    row = session(db, request)
    if row is None:
        raise HTTPException(401, 'Please sign in.')
    if recent and row['authenticated'] < time.time() - RECENT_SECONDS:
        raise HTTPException(403, 'Please sign in again to confirm this action.')
    return row


def atomic_generation(db, cfg):
    """Serialize mutations against local recovery and reject stale config snapshots."""
    if not db.in_transaction:
        db.execute('BEGIN IMMEDIATE')
    current = settings(db)
    if (current.get('user') != cfg.get('user')
            or current.get('epoch') != cfg.get('epoch')):
        raise HTTPException(401, 'Authentication changed. Please sign in again.')


def signed_in(db, cfg, remember=True):
    atomic_generation(db, cfg)
    token = secrets.token_urlsafe(32)
    age = 90 * 86400 if remember else 12 * 3600
    db.execute('INSERT INTO sessions VALUES (?,?,?)', (digest(token), time.time() + age, time.time()))
    response = JSONResponse({'ok': True})
    response.set_cookie(COOKIE, token, max_age=age, httponly=True, secure=cfg['origin'].startswith('https:'), samesite='lax', path='/')
    response.headers['Cache-Control'] = 'no-store'
    return response


def register_auth(app, templates):
    public = {'/login', '/api/auth/status', '/api/auth/password', '/api/auth/passkey/options', '/api/auth/passkey/verify', '/api/auth/device-redeem'}

    @app.middleware('http')
    async def guard(request, call_next):
        # Reading an absent store must preserve unconfigured local operation.
        if not (config.data_dir() / 'auth.sqlite3').exists():
            return await call_next(request)
        with connect() as db:
            cfg = settings(db)
            if not cfg:
                return await call_next(request)
            if request.method not in ('GET', 'HEAD', 'OPTIONS') and request.headers.get('origin') != cfg['origin']:
                return JSONResponse({'detail': 'Origin not allowed.'}, status_code=403)
            if request.url.path not in public and not request.url.path.startswith('/static/') and session(db, request) is None:
                if request.method == 'GET' and not request.url.path.startswith(('/api/', '/media/', '/audio/', '/take/', '/talk/audio/')):
                    target = safe_next(request.url.path + ('?' + request.url.query if request.url.query else ''))
                    return RedirectResponse('/login?next=' + quote(target, safe=''), status_code=303)
                return JSONResponse({'detail': 'Please sign in.'}, status_code=401)
        response = await call_next(request)
        if not request.url.path.startswith('/static/'):
            response.headers['Cache-Control'] = 'no-store'
        return response

    @app.get('/login')
    async def login_page(request: Request):
        return templates.TemplateResponse(request=request, name='login.html', context={'next': safe_next(request.query_params.get('next'))})

    @app.get('/account')
    async def account_page(request: Request):
        return templates.TemplateResponse(request=request, name='account.html', context={})

    @app.get('/api/auth/status')
    async def status(request: Request):
        if not (config.data_dir() / 'auth.sqlite3').exists():
            return {'enabled': False, 'authenticated': False, 'passkeys': []}
        with connect() as db:
            cfg = settings(db)
            row = session(db, request)
            keys = [dict(r) for r in db.execute('SELECT id,name FROM passkeys')] if row else []
            return {'enabled': bool(cfg), 'authenticated': row is not None, 'passkeys': keys}

    async def body(request):
        try:
            chunks = bytearray()
            async for chunk in request.stream():
                if len(chunks) + len(chunk) > 128 * 1024:
                    raise HTTPException(413, 'Authentication request is too large.')
                chunks.extend(chunk)
            data = json.loads(chunks)
            if not isinstance(data, dict):
                raise ValueError()
            return data
        except (ValueError, TypeError):
            raise HTTPException(400, 'Invalid request.')

    def enabled(db):
        cfg = settings(db)
        if not cfg:
            raise HTTPException(404, 'Authentication is not configured.')
        return cfg

    @app.post('/api/auth/password')
    async def password(request: Request):
        data = await body(request)
        with connect() as db:
            cfg = enabled(db)
            limited(db, 'password')
            value = data.get('password', '')
            if not isinstance(value, str) or len(value) > 1024:
                raise HTTPException(400, 'Invalid password.')
            salt, expected = cfg['password'].split(':')
            actual = hashlib.scrypt(value.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1)
            if not hmac.compare_digest(actual.hex(), expected):
                raise HTTPException(401, 'Password not accepted.')
            return signed_in(db, cfg, data.get('remember', True) is True)

    @app.post('/api/auth/logout')
    async def logout(request: Request):
        data = await body(request)
        with connect() as db:
            cfg = enabled(db)
            atomic_generation(db, cfg)
            row = require_session(db, request, recent=data.get('all') is True)
            if data.get('all') is True:
                db.execute("INSERT INTO settings VALUES ('epoch',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (secrets.token_hex(32),))
                db.execute('DELETE FROM sessions')
                db.execute('DELETE FROM codes')
                db.execute('DELETE FROM challenges')
            else:
                db.execute('DELETE FROM sessions WHERE token=?', (row['token'],))
            response = JSONResponse({'ok': True})
            response.delete_cookie(COOKIE, path='/')
            return response

    @app.post('/api/auth/device-code')
    async def device_code(request: Request):
        with connect() as db:
            cfg = enabled(db)
            require_session(db, request, recent=True)
            limited(db, 'code-create', 10)
            atomic_generation(db, cfg)
            require_session(db, request, recent=True)
            code = base64.b32encode(secrets.token_bytes(8)).decode()[:12]
            db.execute('DELETE FROM codes WHERE expires<?', (time.time(),))
            db.execute('INSERT INTO codes VALUES (?,?)', (digest(code), time.time() + 600))
            import qrcode
            from qrcode.image.svg import SvgPathImage
            url = cfg['origin'] + '/login#device=' + code
            qr_svg = qrcode.make(url, image_factory=SvgPathImage).to_string().decode()
            return {'code': code, 'expires_in': 600, 'url': url, 'qr_svg': qr_svg}

    @app.post('/api/auth/device-redeem')
    async def redeem(request: Request):
        data = await body(request)
        with connect() as db:
            cfg = enabled(db)
            limited(db, 'code-redeem', 20)
            value = data.get('code', '')
            if not isinstance(value, str) or len(value) > 64:
                raise HTTPException(400, 'Invalid device code.')
            atomic_generation(db, cfg)
            row = db.execute('DELETE FROM codes WHERE code=? AND expires>? RETURNING code', (digest(value.replace('-', '').replace(' ', '').upper()), time.time())).fetchone()
            if row is None:
                raise HTTPException(401, 'Code expired or not accepted.')
            return signed_in(db, cfg, data.get('remember', True) is True)

    @app.post('/api/auth/passkey/options')
    async def options(request: Request):
        import webauthn
        from webauthn.helpers.structs import AuthenticatorSelectionCriteria, ResidentKeyRequirement, UserVerificationRequirement, PublicKeyCredentialDescriptor
        from webauthn.helpers import base64url_to_bytes
        data = await body(request)
        mode = data.get('mode', 'login')
        if mode not in ('login', 'register'):
            raise HTTPException(400, 'Invalid ceremony.')
        with connect() as db:
            cfg = enabled(db)
            owner = require_session(db, request, recent=True) if mode == 'register' else None
            limited(db, 'challenges', 30)
            atomic_generation(db, cfg)
            owner = require_session(db, request, recent=True) if mode == 'register' else None
            challenge = secrets.token_bytes(32)
            rp = urlsplit(cfg['origin']).hostname
            if mode == 'register':
                generated = webauthn.generate_registration_options(rp_id=rp, rp_name='Shadow', user_name='owner', user_id=bytes.fromhex(cfg['user']), challenge=challenge, exclude_credentials=[PublicKeyCredentialDescriptor(id=base64url_to_bytes(row['id'])) for row in db.execute('SELECT id FROM passkeys')], authenticator_selection=AuthenticatorSelectionCriteria(resident_key=ResidentKeyRequirement.REQUIRED, user_verification=UserVerificationRequirement.REQUIRED))
            else:
                generated = webauthn.generate_authentication_options(rp_id=rp, challenge=challenge, user_verification=UserVerificationRequirement.REQUIRED)
            cid = secrets.token_urlsafe(32)
            db.execute('DELETE FROM challenges WHERE expires<?', (time.time(),))
            db.execute('INSERT INTO challenges VALUES (?,?,?,?,?)', (digest(cid), challenge, mode, owner['token'] if owner else None, time.time()+300))
            return {'cid': cid, 'options': json.loads(webauthn.options_to_json(generated))}

    @app.post('/api/auth/passkey/verify')
    async def verify(request: Request):
        import webauthn
        from webauthn.helpers import base64url_to_bytes, bytes_to_base64url
        data = await body(request)
        with connect() as db:
            cfg = enabled(db)
            limited(db, 'verify', 30)
            cid = data.get('cid', '')
            if not isinstance(cid, str) or len(cid) > 128:
                raise HTTPException(400, 'Invalid ceremony.')
            atomic_generation(db, cfg)
            challenge = db.execute('DELETE FROM challenges WHERE id=? AND expires>? RETURNING *', (digest(cid), time.time())).fetchone()
            # Consume even rejected ceremonies; each challenge permits one attempt.
            db.commit()
            if challenge is None:
                raise HTTPException(400, 'Ceremony expired. Try again.')
            credential = data.get('credential')
            if not isinstance(credential, dict):
                raise HTTPException(400, 'Invalid credential.')
            try:
                atomic_generation(db, cfg)
                if challenge['mode'] == 'register':
                    owner = require_session(db, request, recent=True)
                    if owner['token'] != challenge['session']:
                        raise HTTPException(403, 'Ceremony belongs to another session.')
                    verified = webauthn.verify_registration_response(credential=credential, expected_challenge=challenge['challenge'], expected_rp_id=urlsplit(cfg['origin']).hostname, expected_origin=cfg['origin'], require_user_verification=True)
                    name = data.get('name', 'Passkey')
                    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 80:
                        raise HTTPException(400, 'Choose a name of 1–80 characters.')
                    db.execute('INSERT INTO passkeys VALUES (?,?,?,?)', (bytes_to_base64url(verified.credential_id), name.strip(), verified.credential_public_key, verified.sign_count))
                    return {'ok': True}
                stored = db.execute('SELECT * FROM passkeys WHERE id=?', (credential.get('id'),)).fetchone()
                if stored is None:
                    raise ValueError('Unknown credential')
                handle = credential.get('response', {}).get('userHandle')
                if handle is None or not hmac.compare_digest(base64url_to_bytes(handle), bytes.fromhex(cfg['user'])):
                    raise ValueError('Wrong user')
                verified = webauthn.verify_authentication_response(credential=credential, expected_challenge=challenge['challenge'], expected_rp_id=urlsplit(cfg['origin']).hostname, expected_origin=cfg['origin'], credential_public_key=stored['key'], credential_current_sign_count=stored['counter'], require_user_verification=True)
                db.execute('UPDATE passkeys SET counter=? WHERE id=?', (verified.new_sign_count, stored['id']))
                return signed_in(db, cfg, data.get('remember', True) is True)
            except HTTPException:
                raise
            except Exception:
                raise HTTPException(400, 'Passkey verification failed. Try again.') from None

    @app.delete('/api/auth/passkey/{credential_id}')
    async def remove(credential_id: str, request: Request):
        with connect() as db:
            cfg = enabled(db)  # CLI always retains a backup password as recovery.
            atomic_generation(db, cfg)
            require_session(db, request, recent=True)
            db.execute('DELETE FROM passkeys WHERE id=?', (credential_id,))
            return {'ok': True}
