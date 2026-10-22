"""One consenting user's Saved Messages. No bots, scraping, or account rotation."""
import asyncio
import base64
import io
import os
import time
from telethon import TelegramClient, errors
from telethon.sessions import StringSession


class TelegramBridge:
    def __init__(self, vault):
        self.vault = vault
        self.client = None
        self.lock = asyncio.Lock()

    async def connect(self):
        if self.client and self.client.is_connected():
            return self.client
        stored = self.vault.get('telegram_session')
        if not stored or not os.getenv('TG_API_ID') or not os.getenv('TG_API_HASH'):
            return None
        session = self.vault.open(base64.b64decode(stored), 'telegram-session').decode()
        self.client = TelegramClient(StringSession(session), int(os.environ['TG_API_ID']), os.environ['TG_API_HASH'],
                                     flood_sleep_threshold=0, request_retries=0, connection_retries=1,
                                     receive_updates=False, device_model='AwanVault personal backup')
        await self.client.connect()
        if not await self.client.is_user_authorized():
            await self.client.disconnect()
            self.client = None
            self.vault.set('telegram_blocked', 'Authorization unavailable. Relink using the server CLI.')
            return None
        return self.client

    async def tick(self):
        v = self.vault
        if v.get('telegram_paused', '1') == '1' or v.get('telegram_blocked'):
            return
        if time.time() < float(v.get('telegram_wait_until', '0')):
            return
        async with self.lock:
            with v.db() as db:
                row = db.execute("SELECT * FROM files WHERE state='queued' AND next_try<=? ORDER BY created LIMIT 1", (time.time(),)).fetchone()
            if not row:
                return
            try:
                client = await self.connect()
                if not client:
                    return
                # Verify the independent copy still exists before sending.
                blob = v.read_blob(row['id'])
                v.write_copies(row['id'], blob)
                stream = io.BytesIO(blob)
                stream.name = row['id'] + '.av'
                message = await client.send_file('me', stream, force_document=True,
                    caption='AwanVault encrypted backup • ' + row['id'])
                with v.db() as db:
                    db.execute("UPDATE files SET state='mirrored',message_id=? WHERE id=?", (message.id, row['id']))
                v.set('telegram_status', 'Last upload completed')
            except errors.FloodWaitError as exc:
                v.set('telegram_wait_until', time.time() + exc.seconds + 5)
                v.set('telegram_status', 'Telegram requested a waiting period; uploads paused automatically')
            except (errors.UnauthorizedError, errors.ForbiddenError):
                v.set('telegram_blocked', 'Telegram authorization/access failed. Local recovery remains available.')
            except Exception:
                attempts = row['attempts'] + 1
                with v.db() as db:
                    db.execute('UPDATE files SET attempts=?, next_try=?, state=? WHERE id=?',
                        (attempts, time.time() + min(3600, 30 * 2 ** min(attempts, 6)),
                         'attention' if attempts >= 5 else 'queued', row['id']))
                v.set('telegram_status', 'Upload failed; retry scheduled or manual attention required')

    async def restore(self, file_id):
        if self.vault.get('telegram_blocked') or time.time() < float(self.vault.get('telegram_wait_until', '0')):
            raise OSError('Telegram is unavailable or requested a waiting period')
        with self.vault.db() as db:
            row = db.execute('SELECT message_id FROM files WHERE id=?', (file_id,)).fetchone()
        if not row or not row['message_id']:
            raise OSError('No Telegram reference')
        async with self.lock:
            client = await self.connect()
            if not client:
                raise OSError('Telegram not connected')
            try:
                message = await client.get_messages('me', ids=row['message_id'])
                if not message or not message.file or message.file.size > 65 * 1024 * 1024:
                    raise OSError('Telegram backup missing or invalid')
                blob = await client.download_media(message, bytes)
                self.vault.unpack(blob, file_id)
                self.vault.write_copies(file_id, blob)
                return blob
            except errors.FloodWaitError as exc:
                self.vault.set('telegram_wait_until', time.time() + exc.seconds + 5)
                raise OSError('Telegram requested a waiting period') from exc

    async def run(self):
        while True:
            try:
                await self.tick()
            except asyncio.CancelledError:
                raise
            except Exception:
                self.vault.set('telegram_status', 'Service error; original files remain untouched')
            await asyncio.sleep(15)  # Local pacing only; not a promise of a Telegram-safe rate.
