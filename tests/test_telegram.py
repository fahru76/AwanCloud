import asyncio
import time
from types import SimpleNamespace
from telethon import errors
from server.telegram_bridge import TelegramBridge
from test_vault import vault


def test_successful_mirror_is_sent_to_saved_messages(vault):
    file_id, _ = vault.store(b'contents','a.txt','f','text/plain')
    vault.set('telegram_paused','0')
    bridge = TelegramBridge(vault)
    class Fake:
        async def send_file(self, target, stream, **kwargs):
            assert target == 'me' and kwargs['force_document']
            assert stream.read().startswith(b'AV01')
            return SimpleNamespace(id=123)
    async def connect(): return Fake()
    bridge.connect = connect
    asyncio.run(bridge.tick())
    assert vault.list_files()[0]['state'] == 'mirrored'


def test_flood_wait_is_persisted_and_respected(vault):
    vault.store(b'contents','a.txt','f','text/plain')
    vault.set('telegram_paused','0')
    bridge = TelegramBridge(vault)
    count = 0
    class Fake:
        async def send_file(self,*args,**kwargs):
            nonlocal count
            count += 1
            raise errors.FloodWaitError(request=None,capture=100)
    async def connect(): return Fake()
    bridge.connect = connect
    asyncio.run(bridge.tick())
    assert float(vault.get('telegram_wait_until')) > time.time() + 95
    asyncio.run(bridge.tick())
    assert count == 1 and vault.list_files()[0]['state'] == 'queued'


def test_banned_or_revoked_access_keeps_recovery(vault):
    file_id, _ = vault.store(b'contents','a.txt','f','text/plain')
    vault.set('telegram_paused','0')
    bridge = TelegramBridge(vault)
    class Fake:
        async def send_file(self,*args,**kwargs):
            raise errors.UnauthorizedError(request=None,message='AUTH_KEY_UNREGISTERED')
    async def connect(): return Fake()
    bridge.connect = connect
    asyncio.run(bridge.tick())
    assert vault.get('telegram_blocked')
    assert vault.unpack(vault.read_blob(file_id),file_id)[1] == b'contents'


def test_paused_worker_does_not_connect(vault):
    vault.store(b'contents','a.txt','f','text/plain')
    bridge = TelegramBridge(vault)
    async def forbidden(): raise AssertionError('Must not connect')
    bridge.connect = forbidden
    asyncio.run(bridge.tick())
    assert vault.list_files()[0]['state'] == 'queued'
