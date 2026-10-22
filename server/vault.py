"""Authenticated encrypted envelopes and durable local/recovery storage."""
import base64
from contextlib import contextmanager
import hashlib
import hmac
import json
import os
import sqlite3
import struct
import tempfile
import time
import uuid
from pathlib import Path
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

MAX_FILE = 64 * 1024 * 1024  # Deliberate MVP resource limit, not a Telegram limit.


def atomic_write(path: Path, data: bytes):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix='.pending-')
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        Path(temporary).unlink(missing_ok=True)


def load_key(path):
    key = base64.urlsafe_b64decode(Path(path).read_text().strip())
    if len(key) != 32:
        raise ValueError('Master key must contain 32 random bytes')
    return key


class Vault:
    def __init__(self, data: Path, recovery: Path, key: bytes):
        self.data, self.recovery, self.key = data, recovery, key
        if data.resolve() == recovery.resolve() or data.resolve() in recovery.resolve().parents or recovery.resolve() in data.resolve().parents:
            raise ValueError('Recovery must be a separate directory, outside the primary data tree')
        # Recovery root must already exist: a missing mount must not be silently created.
        if not recovery.is_dir() or not (recovery / '.awanvault-target').is_file():
            raise ValueError('Initialize and mount the recovery target first')
        data.mkdir(parents=True, exist_ok=True, mode=0o700)
        (data / 'objects').mkdir(exist_ok=True, mode=0o700)
        self.db_path = data / 'vault.sqlite3'
        with self.db() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS files (
              id TEXT PRIMARY KEY, fingerprint TEXT UNIQUE NOT NULL, metadata BLOB NOT NULL,
              created REAL NOT NULL, state TEXT NOT NULL DEFAULT 'queued',
              message_id INTEGER, attempts INTEGER NOT NULL DEFAULT 0, next_try REAL NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS config (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS sessions (
              id TEXT PRIMARY KEY, token_hash TEXT UNIQUE NOT NULL, kind TEXT NOT NULL,
              created REAL NOT NULL, expires REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS failures (created REAL NOT NULL);
            ''')
        os.chmod(self.db_path, 0o600)

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.db_path, timeout=20)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA journal_mode=WAL')
        db.execute('PRAGMA synchronous=FULL')
        try:
            with db:
                yield db
        finally:
            db.close()

    def get(self, key, default=None):
        with self.db() as db:
            row = db.execute('SELECT value FROM config WHERE key=?', (key,)).fetchone()
            return row[0] if row else default

    def set(self, key, value):
        with self.db() as db:
            db.execute('INSERT OR REPLACE INTO config VALUES (?,?)', (key, str(value)))

    def seal(self, data, purpose):
        nonce = os.urandom(12)
        return b'AV01' + nonce + AESGCM(self.key).encrypt(nonce, data, purpose.encode())

    def open(self, blob, purpose):
        if blob[:4] != b'AV01':
            raise ValueError('Unknown envelope format')
        return AESGCM(self.key).decrypt(blob[4:16], blob[16:], purpose.encode())

    @staticmethod
    def clean_name(name):
        if not isinstance(name, str) or not name or len(name.encode()) > 240 or name in ('.', '..') or any(ord(c) < 32 or c in '/\\' for c in name):
            raise ValueError('Invalid filename')
        return name

    def unpack(self, blob, file_id):
        plain = self.open(blob, 'file:' + file_id)
        length = struct.unpack('>I', plain[:4])[0]
        if length > 16384:
            raise ValueError('Invalid metadata')
        meta = json.loads(plain[4:4 + length])
        content = plain[4 + length:]
        self.clean_name(meta['name'])
        if hashlib.sha256(content).hexdigest() != meta['sha256'] or len(content) != meta['size']:
            raise ValueError('Integrity check failed')
        return meta, content

    def store(self, content, name, source, media_type):
        self.clean_name(name)
        if len(content) > MAX_FILE:
            raise ValueError('64 MiB per-file limit exceeded')
        if not isinstance(source, str) or len(source.encode()) > 2048:
            raise ValueError('Invalid source')
        checksum = hashlib.sha256(content).hexdigest()
        identity = json.dumps([source, name, checksum], separators=(',', ':')).encode()
        fingerprint = hmac.new(self.key, b'dedup:' + identity, hashlib.sha256).hexdigest()
        with self.db() as db:
            existing = db.execute('SELECT id,metadata FROM files WHERE fingerprint=?', (fingerprint,)).fetchone()
        if existing:
            # A retried upload repairs missing/corrupt copies before acknowledging it.
            file_id = existing['id']
            try:
                blob = self.read_blob(file_id)
            except OSError:
                header = self.open(existing['metadata'], 'meta:' + file_id)
                blob = self.seal(struct.pack('>I', len(header)) + header + content, 'file:' + file_id)
            self.write_copies(file_id, blob)
            return file_id, True
        file_id = str(uuid.uuid4())
        meta = dict(name=name, source=source, media_type=str(media_type)[:200], size=len(content), sha256=checksum)
        header = json.dumps(meta, ensure_ascii=False).encode()
        blob = self.seal(struct.pack('>I', len(header)) + header + content, 'file:' + file_id)
        self.write_copies(file_id, blob)
        with self.db() as db:
            db.execute('INSERT INTO files(id,fingerprint,metadata,created) VALUES(?,?,?,?)',
                       (file_id, fingerprint, self.seal(header, 'meta:' + file_id), time.time()))
        return file_id, False

    def write_copies(self, file_id, blob):
        if not (self.recovery / '.awanvault-target').is_file():
            raise OSError('Recovery target is unavailable; original must be retained')
        atomic_write(self.data / 'objects' / (file_id + '.av'), blob)
        atomic_write(self.recovery / (file_id + '.av'), blob)
        self.unpack((self.recovery / (file_id + '.av')).read_bytes(), file_id)

    def read_blob(self, file_id):
        if str(uuid.UUID(file_id)) != file_id:
            raise ValueError('Invalid file ID')
        for path in (self.data / 'objects' / (file_id + '.av'), self.recovery / (file_id + '.av')):
            try:
                blob = path.read_bytes()
                self.unpack(blob, file_id)
                return blob
            except Exception:
                continue
        raise OSError('No valid local copy. Use Telegram restore if available.')

    def list_files(self):
        with self.db() as db:
            rows = db.execute('SELECT * FROM files ORDER BY created DESC').fetchall()
        result = []
        for row in rows:
            meta = json.loads(self.open(row['metadata'], 'meta:' + row['id']))
            result.append(dict(id=row['id'], created=row['created'], state=row['state'], **meta))
        return result
