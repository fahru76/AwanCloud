# AwanVault · personal backup beta

An Android companion, a browser dashboard, and a self-hosted service for backing up selected photos and documents. Uses your own Telegram account's Saved Messages as an **additional encrypted copy**.

**Status: working server implementation, a separate Android testing APK, and native Android source. See `docs/VALIDATION.md` for the exact build and test status. This is an early single-owner beta, not a production-audited Google Drive replacement.**

## What it does

- Android folder selection with read-only Storage Access Framework permissions.
- Optional photos and/or common documents; unmetered-network and charging preferences.
- Scheduled background backup with WorkManager, retries, and change detection.
- Browser file upload, search, type filters, version listing, and downloads.
- Password plus authenticator sign-in, expiring sessions, and remote session revocation.
- AES-256-GCM encryption of file contents, filename metadata, and Telegram session at rest.
- Two verified encrypted filesystem copies before acknowledging an upload.
- Opt-in Telegram mirror to Saved Messages, sequential uploads, persistent flood-wait handling, and bounded retries.
- Offline recovery from encrypted backup files **without Telegram or the application database**.

## Important boundaries

1. **Telegram bans cannot be prevented or bypassed.** Recovery requires a surviving copy outside Telegram and the original master key. A manifest alone cannot recover missing file bytes.
2. **A server is required.** Use a machine you control and an independent recovery disk/NAS/volume. This is not a free unlimited-storage workaround: the server and recovery location retain complete encrypted copies.
3. **Encryption is server-side.** Files travel to your server over HTTPS, then are encrypted before Telegram upload. The server administrator can decrypt them. This is not end-to-end encryption against the server.
4. **Backup is one-way.** Changes create versions; deletions do not propagate. There is no automatic cloud-to-phone sync, editing merge, or device file removal.
5. **64 MiB per file in this beta.** This is our conservative implementation limit, not Telegram's advertised limit. Videos and large-file chunking are not included.
6. **One owner, one server worker.** No public registration, shared folders, multi-user isolation, or multiple gateway processes.
7. **Android controls background timing.** Scans are scheduled hourly, subject to battery/network restrictions. No promise of instant or continuous sync.
8. **Special-purpose Telegram use is not approved by Telegram.** API terms target Telegram clients and impose requirements that need review before distribution. Personal use is not a guarantee against restrictions.

## Start here

Read [`docs/SETUP.md`](docs/SETUP.md), then [`docs/SECURITY-AND-RECOVERY.md`](docs/SECURITY-AND-RECOVERY.md).

Build the Android APK from source with `./gradlew :app:assembleDebug` in the `android` folder. The separately supplied debug APK is intentionally not stored in this source repository.

The browser dashboard is served by your own service at its HTTPS address. It is not hosted or connected to your Telegram account by this package. No real account credentials, recovery keys, or personal files are included.

## Project structure

```text
android/                Native Java Android app, Gradle project
server/app.py           FastAPI service and security controls
server/vault.py         Encrypted envelope and durable storage
server/telegram_bridge.py   Telegram transport and queue
server/cli.py           Local setup, linking, offline recovery
server/static/          Responsive browser dashboard; no external CDN
tests/                 Authentication, recovery and failure tests
docs/                  Setup, trust model, validation and roadmap
```

## Development check

From this directory, with Python 3.12:

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

The tests use temporary files and a fake Telegram transport; they never log in to or send files through Telegram. Dependency versions were used in the development environment; the production image and Android dependency set must still be reviewed for security updates before exposure.

## License

Original code in this package is MIT licensed. Third-party libraries retain their own licenses. This project does not reuse Telegram branding or official-client source code. It is not affiliated with Telegram.
