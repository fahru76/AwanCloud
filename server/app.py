import asyncio
import base64
import contextlib
import hashlib
import hmac
import json
import os
import secrets
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import quote, urlsplit

import pyotp
from argon2 import PasswordHasher
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from .vault import Vault, MAX_FILE, load_key
from .telegram_bridge import TelegramBridge


class Login(BaseModel):
    username: str = Field(max_length=200)
    password: str = Field(max_length=512)
    code: str = Field(min_length=6, max_length=6)


class Switch(BaseModel):
    paused: bool


def create_app(vault=None, origin=None, start_worker=True):
    origin = (origin or os.environ.get('AV_ORIGIN', 'http://localhost:8000')).rstrip('/')
    parsed = urlsplit(origin)
    secure = parsed.scheme == 'https'
    if not secure and parsed.hostname not in ('localhost', '127.0.0.1'):
        raise RuntimeError('HTTPS is required except on loopback')
    v = vault or Vault(Path(os.environ.get('AV_DATA', './data')),
                       Path(os.environ.get('AV_RECOVERY', './recovery')),
                       load_key(os.environ.get('AV_KEY_FILE', './secrets/master.key')))
    bridge = TelegramBridge(v)
    upload_lock = asyncio.Lock()
    login_lock = asyncio.Lock()
    ph = PasswordHasher()
    cookie_name = '__Host-awanvault' if secure else 'awanvault_dev'

    @asynccontextmanager
    async def lifespan(app):
        task = asyncio.create_task(bridge.run()) if start_worker else None
        yield
        if task:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        if bridge.client:
            await bridge.client.disconnect()

    app = FastAPI(title='AwanVault', docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.state.vault = v
    app.state.bridge = bridge

    @app.middleware('http')
    async def security(request, call_next):
        if request.headers.get('host') != parsed.netloc:
            return Response('Invalid host', status_code=400)
        if request.method == 'POST' and request.url.path != '/api/files' and 'content-length' not in request.headers:
            return Response('Content-Length required', status_code=411)
        length = request.headers.get('content-length', '0')
        try:
            limit = MAX_FILE if request.url.path == '/api/files' and request.method == 'PUT' else 16384
            if int(length) < 0 or int(length) > limit:
                return Response('Request too large', status_code=413)
        except ValueError:
            return Response('Invalid length', status_code=400)
        if request.method not in ('GET', 'HEAD', 'OPTIONS'):
            req_origin = request.headers.get('origin')
            bearer = request.headers.get('authorization', '').startswith('Bearer ')
            native_login = request.url.path == '/api/auth/device-login'
            if req_origin is not None and req_origin != origin:
                return Response('Origin rejected', status_code=403)
            if not bearer and not native_login and (req_origin != origin or request.headers.get('x-awanvault') != '1'):
                return Response('Origin/header required', status_code=403)
        response = await call_next(request)
        response.headers.update({
            'Content-Security-Policy': "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
            'X-Content-Type-Options': 'nosniff', 'Referrer-Policy': 'no-referrer',
            'X-Frame-Options': 'DENY', 'Cache-Control': 'no-store',
            'Permissions-Policy': 'camera=(), microphone=(), geolocation=()'})
        if secure:
            response.headers['Strict-Transport-Security'] = 'max-age=31536000'
        return response

    def identity(request: Request):
        header = request.headers.get('authorization', '')
        is_device = header.startswith('Bearer ')
        token = header[7:] if is_device else request.cookies.get(cookie_name, '')
        if not token or len(token) > 200:
            raise HTTPException(401, 'Sign in required')
        with v.db() as db:
            row = db.execute('SELECT * FROM sessions WHERE token_hash=? AND expires>?',
                             (hashlib.sha256(token.encode()).hexdigest(), time.time())).fetchone()
        if not row or row['kind'] != ('device' if is_device else 'browser'):
            raise HTTPException(401, 'Session expired or revoked')
        return dict(row)

    def owner(session=Depends(identity)):
        if session['kind'] != 'browser':
            raise HTTPException(403, 'Use the browser owner session')
        return session

    async def sign_in(login, kind):
        async with login_lock:
            with v.db() as db:
                db.execute('DELETE FROM failures WHERE created<?', (time.time() - 900,))
                count = db.execute('SELECT COUNT(*) FROM failures').fetchone()[0]
            if count >= 10:
                raise HTTPException(429, 'Too many attempts. Wait 15 minutes.')
            valid = False
            try:
                valid = await asyncio.to_thread(ph.verify, v.get('password_hash', ''), login.password)
                valid = valid and hmac.compare_digest(login.username.encode(), v.get('username', '').encode())
                seed = v.open(base64.b64decode(v.get('totp_secret', '')), 'totp').decode()
                now_step = int(time.time()) // 30
                totp = pyotp.TOTP(seed)
                matched = next((step for step in (now_step - 1, now_step, now_step + 1)
                                if hmac.compare_digest(totp.at(step * 30), login.code)), None)
                valid = valid and matched is not None and matched > int(v.get('totp_last_step', '-1'))
            except Exception:
                valid = False
            if not valid:
                with v.db() as db:
                    db.execute('INSERT INTO failures VALUES (?)', (time.time(),))
                raise HTTPException(401, 'Invalid credentials or already-used authenticator code')
            v.set('totp_last_step', matched)
            token = secrets.token_urlsafe(48)
            expires = time.time() + (30 * 86400 if kind == 'device' else 8 * 3600)
            with v.db() as db:
                db.execute('DELETE FROM sessions WHERE expires<?', (time.time(),))
                db.execute('INSERT INTO sessions VALUES (?,?,?,?,?)',
                    (str(uuid.uuid4()), hashlib.sha256(token.encode()).hexdigest(), kind, time.time(), expires))
            return token, expires

    @app.post('/api/auth/login')
    async def login(body: Login, response: Response):
        token, expires = await sign_in(body, 'browser')
        response.set_cookie(cookie_name, token, max_age=8 * 3600, secure=secure, httponly=True, samesite='strict', path='/')
        return {'expires': expires}

    @app.post('/api/auth/device-login')
    async def device_login(body: Login):
        token, expires = await sign_in(body, 'device')
        return {'token': token, 'expires': expires}

    @app.post('/api/auth/logout')
    def logout(response: Response, session=Depends(identity)):
        with v.db() as db:
            db.execute('DELETE FROM sessions WHERE id=?', (session['id'],))
        response.delete_cookie(cookie_name, path='/', secure=secure, httponly=True, samesite='strict')
        return {'ok': True}

    @app.get('/api/sessions')
    def sessions(session=Depends(owner)):
        with v.db() as db:
            return [dict(row) | {'current': row['id'] == session['id']} for row in db.execute(
                'SELECT id,kind,created,expires FROM sessions WHERE expires>? ORDER BY created DESC', (time.time(),))]

    @app.delete('/api/sessions/{session_id}')
    def revoke(session_id: str, session=Depends(owner)):
        with v.db() as db:
            db.execute('DELETE FROM sessions WHERE id=?', (session_id,))
        return {'ok': True}

    @app.get('/api/status')
    def status(session=Depends(identity)):
        with v.db() as db:
            counts = {row[0]: row[1] for row in db.execute('SELECT state,COUNT(*) FROM files GROUP BY state')}
        return {'counts': counts, 'telegram_linked': bool(v.get('telegram_session')),
                'telegram_paused': v.get('telegram_paused', '1') == '1',
                'telegram_blocked': v.get('telegram_blocked'),
                'telegram_wait_until': float(v.get('telegram_wait_until', '0')),
                'telegram_status': v.get('telegram_status', 'Not connected'),
                'recovery_online': (v.recovery / '.awanvault-target').is_file(),
                'max_file_bytes': MAX_FILE}

    @app.post('/api/telegram/pause')
    def pause(body: Switch, session=Depends(owner)):
        v.set('telegram_paused', '1' if body.paused else '0')
        return {'ok': True}

    @app.post('/api/telegram/retry')
    def retry(session=Depends(owner)):
        with v.db() as db:
            db.execute("UPDATE files SET state='queued',attempts=0,next_try=0 WHERE state='attention'")
        return {'ok': True}

    @app.get('/api/files')
    def files(session=Depends(identity)):
        return v.list_files()

    @app.put('/api/files')
    async def upload(request: Request, session=Depends(identity)):
        try:
            header = request.headers.get('x-file-metadata', '')
            if len(header) > 8192:
                raise ValueError()
            meta = json.loads(base64.b64decode(header, validate=True))
            v.clean_name(meta['name'])
            source = meta.get('source', 'Browser')
            if not isinstance(source, str) or len(source.encode()) > 2048:
                raise ValueError()
        except Exception:
            raise HTTPException(400, 'Invalid file metadata')
        async with upload_lock:
            content = bytearray()
            async for chunk in request.stream():
                if len(content) + len(chunk) > MAX_FILE:
                    raise HTTPException(413, 'First version supports files up to 64 MiB')
                content.extend(chunk)
            try:
                file_id, duplicate = await asyncio.to_thread(v.store, bytes(content), meta['name'], source, meta.get('media_type', 'application/octet-stream'))
            except (ValueError, TypeError):
                raise HTTPException(400, 'Invalid file metadata')
            except OSError:
                raise HTTPException(503, 'Recovery copy could not be verified. Keep the original and retry.')
            return {'id': file_id, 'duplicate': duplicate, 'recovery_verified_at_upload': True}

    @app.get('/api/files/{file_id}/download')
    async def download(file_id: str, session=Depends(identity)):
        try:
            file_id = str(uuid.UUID(file_id))
        except ValueError:
            raise HTTPException(404, 'File not found')
        with v.db() as db:
            if not db.execute('SELECT 1 FROM files WHERE id=?', (file_id,)).fetchone():
                raise HTTPException(404, 'File not found')
        try:
            blob = await asyncio.to_thread(v.read_blob, file_id)
            meta, content = v.unpack(blob, file_id)
        except Exception:
            raise HTTPException(503, 'No valid local copy. Use Restore from Telegram in the dashboard.')
        return Response(content, media_type='application/octet-stream', headers={
            'Content-Disposition': "attachment; filename*=UTF-8''" + quote(meta['name'], safe='')})

    @app.post('/api/files/{file_id}/restore')
    async def restore(file_id: str, session=Depends(owner)):
        try:
            file_id = str(uuid.UUID(file_id))
            await bridge.restore(file_id)
        except Exception:
            raise HTTPException(503, 'Telegram restore unavailable. Check connection, waiting period and backup target.')
        return {'ok': True}

    @app.get('/')
    def index():
        return FileResponse(Path(__file__).parent / 'static' / 'index.html')

    app.mount('/static', StaticFiles(directory=Path(__file__).parent / 'static'), name='static')
    return app
