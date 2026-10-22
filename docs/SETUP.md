# Setup guide

## 1. What you need

- A Linux machine or VPS you control, with sufficient storage for all files. The container route uses Docker Engine and Docker Compose.
- A **separate, pre-mounted recovery disk or NAS**. A second directory on the same physical disk is suitable only for testing. Keep an additional disconnected/off-site snapshot for ransomware or site loss.
- A domain/hostname pointing to the server, with TCP 80 and 443 accessible for the supplied HTTPS proxy. An experienced administrator can instead use an existing trusted HTTPS reverse proxy or private VPN.
- An authenticator app supporting standard six-digit TOTP codes.
- Your own Telegram account, with Telegram two-step verification enabled, and your own API ID/hash from https://my.telegram.org → API development tools.
- For Android builds: Android Studio, SDK 35, JDK 17, and Gradle 8.11.1. The app targets Android 8.0/API 26 and above, with target SDK 35. Store publication compliance is not established by this beta.

Never send Telegram login codes, passwords, API hashes, master keys, or session strings in a chat. Enter them only in your trusted local setup.

## 2. Configure the server

Extract the package and open a terminal in `AwanVault`.

```bash
cp .env.example .env
mkdir -p data secrets recovery
chmod 700 data secrets recovery
chmod 600 .env
```

Edit `.env`:

- Set `AV_HOST` to your actual hostname (without `https://`).
- Set `AV_UID` and `AV_GID` to the Linux user/group owning these folders (`id -u` and `id -g`).
- Set `RECOVERY_PATH` to the **already mounted**, independent recovery directory. Make it writable by that user. Verify the mount before initialization; `mkdir` alone does not mount a disk.
- Set your own `TG_API_ID` and `TG_API_HASH`. These are application credentials, not bot credentials.

Keep the recovery mount mounted for the lifetime of the containers. Stop the app before unmounting it. A sentinel file detects many missing-target cases, but does not prove physical independence or protect against all mount/bind-mount failures. Configure host-side mount checks and alerts.

Build and initialize:

```bash
docker compose build
docker compose run --rm setup init
```

The setup asks for an owner username, a password of at least 14 characters, and authenticator enrollment. It creates:

- `secrets/master.key`: encryption/recovery key.
- `data/vault.sqlite3`: account settings, queue, encrypted metadata and hashed sessions.
- A `.awanvault-target` marker in the configured recovery directory.

**Copy `master.key` to a separate secure offline location before relying on this vault.** It is not your login password. It cannot be reset to decrypt old backups. Do not store the only copy on the same server, in Telegram, or beside the only backup.

## 3. Link your own Telegram account

Keep the app stopped during linking or relinking:

```bash
docker compose stop app
docker compose run --rm setup link-telegram
```

Read the consent prompt, type `LINK`, and enter the phone number, Telegram login code and Telegram two-step verification password locally. Linking creates an encrypted authorization session. It is not a bot and does not automate the installed Telegram interface.

The first Telegram upload remains paused until you explicitly enable it in the browser. This lets you verify local and recovery storage first.

## 4. Start and test the browser dashboard

```bash
docker compose up -d app proxy
```

Open `https://YOUR_HOSTNAME`. Sign in with the new AwanVault username/password/authenticator code. Your browser login is separate from Telegram.

1. Upload a small, non-sensitive test document.
2. Download it and compare it with the original.
3. Verify a corresponding `.av` file exists on the independent recovery target.
4. Run the offline recovery drill below.
5. Open **Sync & connections** and resume Telegram uploads.
6. Check that the item becomes **Uploaded**. You should see an opaque `.av` document in your own Saved Messages. It must be decrypted through AwanVault; normal Telegram clients cannot preview the encrypted photo/document contents.

“Uploaded” means the send was acknowledged; it does not continuously verify that someone has not subsequently deleted the Telegram message. “Recovery target available” checks the target marker, not all historical file integrity. Use recovery drills and filesystem snapshots.

## 5. Android installation and use

The exact compile/APK status is in `VALIDATION.md`. The debug APK is not committed; build it from source using the included Gradle wrapper. It is not a Play Store release. Only install it after configuring your own HTTPS server.

To build from source:

1. Open the `android` directory in Android Studio.
2. Use JDK 17 and SDK platform/build tools 35.
3. Use Gradle 8.11.1. The Gradle wrapper is included; it downloads Gradle 8.11.1 on the first run.
4. Run `./gradlew :app:assembleDebug` (Windows: `gradlew.bat :app:assembleDebug`).
5. Install `app/build/outputs/apk/debug/app-debug.apk` on a test phone.
6. For a durable personal installation, create and retain your own release signing key, then build a signed release. Losing that key can prevent installing updates over the existing app.

In the app:

1. Enter your HTTPS server address, owner username/password, and a fresh authenticator code. A code already used by a browser login is rejected; wait for the next code.
2. Choose a specific photo folder such as `DCIM/Camera` and/or a documents folder. Android may prevent choosing storage roots, Download root, or protected app directories. Choose allowed subfolders.
3. Select photos, documents, or both. Videos are not included.
4. Choose unmetered-network/charging preferences.
5. Enable background backup, then use **Run backup now** for the first scan.
6. Open **My files in browser** to browse and download. The browser asks for its own login; the device token is not passed in a URL.

Folder selection persists through restarts. Android may delay work under battery-saving rules or after the app is force-stopped; open the app again to resume scheduling. Work is divided into bounded batches, with a full scan scheduled roughly hourly. The app never requests all-files permission and does not write or delete device originals.

Change detection uses file size and modification time where available, and a content hash when modification time is unavailable. Files changed without changing size or timestamp can be missed until **Recheck all selected files** is used. This button also helps after rebuilding the server from recovery. Retransfers are deduplicated on the server by source/name/content.

Android sessions expire after 30 days. Sign in again when requested. An expired session pauses scheduling until you re-enable it. Device keys do not require biometric authentication for each use because background backup must work unattended; keep the phone protected with a screen lock.

## 6. Recovery drill: no Telegram or database required

Use a separate test/output directory on a trusted computer. This produces plaintext files.

With Python 3.12 and the package dependencies installed:

```bash
python -m server.cli recover \
  --source /path/to/copied-recovery-files \
  --output /path/to/new-restored-directory \
  --key-file /path/to/offline/master.key
```

Every encrypted `.av` file contains authenticated metadata, original filename and content. Restored versions go into UUID-named subfolders; separate metadata files record the original logical source. This avoids overwriting files with duplicate names and prevents metadata paths from writing outside the restore directory.

Check file counts and open a sample of restored files. Compare checksums for important documents. An error exits non-zero and leaves other successfully recovered files in place. Existing output folders are never overwritten.

## 7. Maintenance

- Keep host time synchronized for authenticator codes.
- Monitor free space in both primary and recovery locations. Uploads fail rather than acknowledge an unverifiable recovery copy.
- Keep an encrypted, offline copy of `master.key`. Keep backups of the database and secrets separately with access controls. The standalone `.av` files support emergency content restoration even without the database; preserving the database preserves Telegram message references and settings.
- Use independent snapshots or offline backups. A writable mirror can be damaged by a compromised server.
- Pause uploads before maintenance. Stop `app` before copying its database for a consistent backup; include the whole `data` directory or use a proper SQLite backup tool.
- If a phone is lost, use **Security** in the browser to revoke its device session. Revoking cannot claw back file bytes already downloaded.
- If the server is compromised, revoke its Telegram authorization in the official Telegram app's device/session settings, revoke app sessions, and rebuild from a trusted machine. Server compromise may expose decrypted data and the master key.
- Review dependency and operating system security updates before production use; container tags are not fully reproducible lockfiles.
- There is no retention/pruning UI in this beta. Versions accumulate and consume storage. Do not remove objects manually without a backup and a planned retention mechanism.

To reset the owner login after losing a password/authenticator, with administrative access:

```bash
docker compose stop app
docker compose run --rm setup reset-login
docker compose up -d app
```

This preserves file encryption but revokes existing app sessions. It cannot replace a lost master key.

## Local developer route

For a loopback-only test, without Docker or Telegram:

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements-dev.txt
python -m server.cli init
python -m uvicorn server.app:create_app --factory --host 127.0.0.1 --port 8000 --workers 1
```

Open exactly `http://localhost:8000`. The default expected origin is `http://localhost:8000`; using `127.0.0.1` in the browser requires changing `AV_ORIGIN` to match. HTTP is allowed only for loopback development, and the Android app requires HTTPS. Local `./recovery` is only a development copy, not independent disaster protection.
