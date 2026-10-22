import base64
import json
import time
import pyotp
import pytest
from argon2 import PasswordHasher
from fastapi.testclient import TestClient
from server.app import create_app
from test_vault import vault

ORIGIN = 'https://vault.example.test'
HEADERS = {'Origin': ORIGIN, 'X-AwanVault':'1'}

@pytest.fixture
def client(vault):
    vault.set('username', 'owner')
    vault.set('password_hash', PasswordHasher().hash('correct-horse-long-password'))
    seed = pyotp.random_base32()
    vault.set('totp_secret', base64.b64encode(vault.seal(seed.encode(),'totp')).decode())
    app = create_app(vault, ORIGIN, start_worker=False)
    with TestClient(app, base_url=ORIGIN) as c:
        c.seed = seed
        c.vault = vault
        yield c


def login(client, path='/api/auth/login'):
    return client.post(path, headers=HEADERS, json={'username':'owner','password':'correct-horse-long-password','code':pyotp.TOTP(client.seed).now()})


def upload(client, content=b'private file', name='report.pdf'):
    meta = base64.b64encode(json.dumps({'name':name,'source':'test','media_type':'application/pdf'}).encode()).decode()
    return client.put('/api/files', headers=HEADERS | {'X-File-Metadata':meta}, content=content)


def test_all_file_access_requires_login(client):
    assert client.get('/api/files').status_code == 401
    assert upload(client).status_code == 401
    assert client.get('/api/status').status_code == 401


def test_full_upload_list_download(client):
    response = login(client)
    assert response.status_code == 200
    assert 'HttpOnly' in response.headers['set-cookie'] and 'Secure' in response.headers['set-cookie']
    result = upload(client)
    assert result.status_code == 200 and result.json()['recovery_verified_at_upload']
    file_id = result.json()['id']
    assert client.get('/api/files').json()[0]['name'] == 'report.pdf'
    download = client.get('/api/files/' + file_id + '/download')
    assert download.content == b'private file'
    assert 'attachment' in download.headers['content-disposition']


def test_totp_replay_and_bad_credentials(client):
    assert login(client).status_code == 200
    assert login(client).status_code == 401
    assert client.post('/api/auth/device-login', json={'username':'owner','password':'wrong','code':'000000'}).status_code == 401


def test_csrf_and_host_validation(client):
    assert login(client).status_code == 200
    assert client.post('/api/telegram/pause',json={'paused':False}).status_code == 403
    assert client.post('/api/telegram/pause',headers={'Origin':'https://evil.test','X-AwanVault':'1'},json={'paused':False}).status_code == 403
    assert client.get('/api/status',headers={'Host':'evil.test'}).status_code == 400


def test_rate_limit(client):
    for _ in range(10):
        assert client.post('/api/auth/device-login',json={'username':'owner','password':'wrong','code':'000000'}).status_code == 401
    assert login(client).status_code == 429


def test_device_access_cannot_change_owner_settings(client):
    result = login(client,'/api/auth/device-login')
    assert result.status_code == 200
    auth = {'Authorization':'Bearer '+result.json()['token']}
    assert client.get('/api/files',headers=auth).status_code == 200
    assert client.get('/api/sessions',headers=auth).status_code == 403
    assert client.post('/api/telegram/pause',headers=auth,json={'paused':False}).status_code == 403
    assert client.post('/api/auth/logout',headers=auth,json={}).status_code == 200
    assert client.get('/api/files',headers=auth).status_code == 401


def test_cookie_logout_invalidates_session(client):
    login(client)
    assert client.post('/api/auth/logout',headers=HEADERS,json={}).status_code == 200
    assert client.get('/api/files').status_code == 401


def test_missing_backup_target_returns_retryable_failure(client):
    login(client)
    (client.vault.recovery/'.awanvault-target').unlink()
    assert upload(client).status_code == 503


def test_client_filename_is_not_executable_html(client):
    login(client)
    # Less-than signs are legal names. UI uses textContent and downloads are attachments.
    assert upload(client,name='<script>.txt').status_code == 200
    assert client.get('/api/files').json()[0]['name'] == '<script>.txt'


def test_size_cap_before_reading_body(client):
    login(client)
    assert client.put('/api/files',headers=HEADERS | {'Content-Length':str(64*1024*1024+1)},content=b'').status_code == 413


def test_security_headers(client):
    response = client.get('/')
    assert response.status_code == 200
    assert "frame-ancestors 'none'" in response.headers['content-security-policy']
    assert response.headers['cache-control'] == 'no-store'
    assert response.headers['x-content-type-options'] == 'nosniff'
