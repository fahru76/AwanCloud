"""Local administrator setup and Telegram-independent offline recovery."""
import argparse
import asyncio
import base64
import getpass
import json
import os
import secrets
import sys
from pathlib import Path

import pyotp
from argon2 import PasswordHasher
from .vault import Vault, atomic_write, load_key


def configured():
    return Vault(Path(os.getenv('AV_DATA', './data')), Path(os.getenv('AV_RECOVERY', './recovery')),
                 load_key(os.getenv('AV_KEY_FILE', './secrets/master.key')))


def setup():
    os.umask(0o077)
    keypath = Path(os.getenv('AV_KEY_FILE', './secrets/master.key'))
    recovery = Path(os.getenv('AV_RECOVERY', './recovery'))
    recovery.mkdir(parents=True, exist_ok=True)
    if not (recovery / '.awanvault-target').exists():
        atomic_write(recovery / '.awanvault-target', b'AwanVault recovery target v1\n')
    if not keypath.exists() and (Path(os.getenv('AV_DATA', './data')) / 'vault.sqlite3').exists():
        raise SystemExit('Existing vault found without its key. Restore the original key; never generate a replacement.')
    if not keypath.exists():
        atomic_write(keypath, base64.urlsafe_b64encode(secrets.token_bytes(32)))
    v = configured()
    if v.get('username'):
        raise SystemExit('Already initialized. Use reset-login for account recovery.')
    reset_login(v)
    print('Setup complete. Keep a separate offline copy of the master key. Losing it loses access to encrypted files.')
    print('Recovery directory must be on a separate mounted disk/NAS for failure isolation.')


def reset_login(v=None):
    v = v or configured()
    username = input('Owner username: ').strip()
    if not username or len(username) > 200:
        raise SystemExit('Invalid username')
    password = getpass.getpass('New password (at least 14 characters): ')
    if len(password) < 14 or len(password) > 512 or password != getpass.getpass('Repeat password: '):
        raise SystemExit('Password too short, too long, or mismatched')
    seed = pyotp.random_base32()
    print('Add this secret to your authenticator, then keep it private:', seed)
    code = input('Authenticator code: ').strip()
    if not pyotp.TOTP(seed).verify(code, valid_window=1):
        raise SystemExit('Authenticator verification failed')
    v.set('username', username)
    v.set('password_hash', PasswordHasher().hash(password))
    v.set('totp_secret', base64.b64encode(v.seal(seed.encode(), 'totp')).decode())
    v.set('totp_last_step', '-1')
    with v.db() as db:
        db.execute('DELETE FROM sessions')
        db.execute('DELETE FROM failures')
    print('Owner login configured; previous sessions revoked.')


async def link():
    from telethon import TelegramClient
    from telethon.sessions import StringSession
    v = configured()
    client = TelegramClient(StringSession(), int(os.environ['TG_API_ID']), os.environ['TG_API_HASH'])
    print('Stop the web server before relinking. This signs into your real Telegram account.')
    print('Only opt-in encrypted backups will be sent to Saved Messages. Account restriction remains possible.')
    if input('Type LINK to continue: ') != 'LINK':
        return
    try:
        await client.start(phone=lambda: input('Telegram phone (+country code): '),
                           code_callback=lambda: getpass.getpass('Telegram login code: '),
                           password=lambda: getpass.getpass('Telegram two-step verification password: '))
        v.set('telegram_session', base64.b64encode(v.seal(client.session.save().encode(), 'telegram-session')).decode())
        v.set('telegram_blocked', '')
        v.set('telegram_wait_until', '0')
        v.set('telegram_paused', '1')
        v.set('telegram_status', 'Connected; resume uploads in the browser when ready')
        print('Session saved encrypted. Uploads remain paused until you enable them in the dashboard.')
    finally:
        await client.disconnect()


def recover(source, output, keyfile):
    # No Telegram access, server credentials, database, or mounted recovery target is needed.
    v = object.__new__(Vault)
    v.key = load_key(keyfile)
    destination = Path(output)
    destination.mkdir(parents=True, exist_ok=True)
    ok, failed = 0, 0
    for path in sorted(Path(source).glob('*.av')):
        try:
            import uuid
            file_id = str(uuid.UUID(path.stem))
            meta, content = v.unpack(path.read_bytes(), file_id)
            target = destination / file_id
            if target.exists():
                raise ValueError('Destination already exists; refusing overwrite')
            target.mkdir(mode=0o700)
            atomic_write(target / meta['name'], content)
            # Metadata stored outside the user file directory to avoid filename collisions.
            atomic_write(destination / (file_id + '.metadata.json'), json.dumps(meta, indent=2).encode())
            ok += 1
        except Exception:
            failed += 1
            print('Could not restore:', path.name, file=sys.stderr)
    print(f'Restored {ok}; failed {failed}. Output files are plaintext: protect this location.')
    if failed:
        raise SystemExit(1)


def main():
    parser = argparse.ArgumentParser(description='AwanVault administrator tools')
    commands = parser.add_subparsers(dest='command', required=True)
    for name in ('init', 'reset-login', 'link-telegram'):
        commands.add_parser(name)
    restore = commands.add_parser('recover')
    restore.add_argument('--source', required=True)
    restore.add_argument('--output', required=True)
    restore.add_argument('--key-file', required=True)
    args = parser.parse_args()
    if args.command == 'init': setup()
    elif args.command == 'reset-login': reset_login()
    elif args.command == 'link-telegram': asyncio.run(link())
    else: recover(args.source, args.output, args.key_file)


if __name__ == '__main__':
    main()
