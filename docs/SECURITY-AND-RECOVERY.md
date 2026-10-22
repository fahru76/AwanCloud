# Security and recovery design

## Assumed deployment

This beta is for one owner on a server they control. The Android companion talks to that server over HTTPS. The server encrypts uploaded bytes and stores complete copies on primary and recovery filesystems. It optionally sends the same encrypted envelope to the owner's Telegram Saved Messages.

A second independent location is essential. If Telegram holds the only copy and the account becomes inaccessible, an index, recovery key, alternate account, or new app cannot guarantee recovery of the file bytes. This project does not evade bans, rotate accounts to avoid enforcement, scrape other accounts, or send unsolicited messages.

## Threat boundaries

| Event | Implemented behavior | Remaining requirement or limitation |
|---|---|---|
| Telegram access revoked/banned | Authorization/access errors stop uploads; local and recovery copies remain readable | At least one independent copy and the original key must survive |
| Telegram rate limiting | Persist server-requested wait and defer requests | Local pacing is not evidence of Telegram approval or a safe quota |
| Lost phone | Browser owner can revoke device token | Device lock and server revocation; already downloaded plaintext cannot be recalled |
| Stolen encrypted Telegram document | AES-256-GCM protects content and embedded filename metadata | Security depends on the master key remaining secret |
| Tampered encrypted object | GCM authentication and plaintext SHA-256 verification reject corruption | Recover another valid copy; no automatic silent acceptance |
| Missing recovery mount | Missing target marker or write/verify failure prevents upload acknowledgement | Host must manage/monitor mounts; marker is not proof of physical isolation |
| Primary object corruption | Download falls back to verified recovery object | Historical backup verification is a separate operator task |
| Both local copies lost, Telegram available | Owner can restore a referenced Telegram object from the dashboard | Requires working Telegram session, database message reference and key |
| Server/database destroyed, recovery survives | Offline CLI restores self-contained envelopes | Keep the recovery key offline; app index/settings must be rebuilt separately |
| Server compromise/ransomware | At-rest encryption does not protect against a running compromised server | Keep independent immutable/offline snapshots and revoke Telegram authorization |
| Lost master key | No decryption fallback is provided | Restore the exact original key; login reset cannot decrypt files |

## Authentication

- Local administrator initializes the sole owner account; no public registration or default credentials.
- Argon2id password hashing through argon2-cffi's PasswordHasher defaults.
- Six-digit TOTP with a narrow time tolerance; accepted time steps cannot be replayed.
- Persistent failed-login tracking: after ten failures within fifteen minutes, new login attempts are temporarily rejected. This single-owner global throttle intentionally trades availability for brute-force resistance; a distributed attacker can cause temporary lockout. Add network-level protection appropriate to the deployment.
- Browser session tokens are random, stored hashed server-side, and delivered only in HttpOnly, Secure, SameSite=Strict cookies under HTTPS. Lifetime: eight hours.
- Device session tokens are random, stored hashed server-side, sent in Authorization headers, encrypted on Android with an Android Keystore key, and expire after thirty days. They may upload/list/download, but cannot manage owner settings, sessions, or explicit Telegram restore actions.
- Android stores neither the login password nor authenticator secret. Its encryption key does not require per-use biometric prompts, allowing unattended backup. Rooted/unlocked compromised devices remain outside this protection.
- Host checks, same-origin checks for unsafe browser requests, and a required custom header reduce CSRF risk. No cross-origin API is enabled.
- Owner login reset requires local server access and revokes app sessions.

## Encryption and data format

The master key is 32 cryptographically random bytes, stored as URL-safe Base64 in a separate private file. Each AES-GCM encryption uses a fresh random 96-bit nonce. Purpose- and UUID-specific associated data separates file objects, database metadata, the Telegram session, and the authenticator secret.

An `.av` file consists of:

```text
4-byte format magic "AV01"
12-byte random nonce
AES-256-GCM ciphertext and authentication tag
```

The decrypted payload contains a four-byte big-endian metadata length, UTF-8 JSON metadata, and original file bytes. Metadata includes original filename, logical source, media type, byte length, and SHA-256 digest. File IDs are random UUIDs. Recovery validates IDs and filenames and never uses the original source path as a filesystem destination.

Deduplication uses a keyed HMAC over source, filename and content checksum. The database stores encrypted filename/source metadata; object counts, timestamps, states, sizes observable through storage, and Telegram message references are not hidden from a server/storage observer. Telegram sees account activity, encrypted object sizes and timing.

The master key can decrypt all files. This version does not implement key rotation, per-file wrapped keys, client-held end-to-end encryption, multi-owner key isolation, or cryptographic deletion. Server-side plaintext may be present in memory during upload/download; prevent swapping to unencrypted storage if that is in your threat model.

## Durable-write and recovery behavior

1. Read an explicitly selected original, respecting the 64 MiB cap.
2. Hash and encrypt it; metadata is authenticated inside the envelope.
3. Write the primary encrypted copy through a temporary file, flush/fsync, and atomic rename.
4. Write the recovery copy the same way, then read/decrypt/check it.
5. Commit the queue/index row only after both copies are valid.
6. Acknowledge the client; the Android app marks the source version uploaded.
7. If enabled, send the verified encrypted document to Saved Messages.
8. Save the returned message ID only after Telegram acknowledges the send.

A crash between Telegram accepting a message and recording its ID can leave a duplicate Telegram message after retry. No source file is deleted. A crash during pre-commit file writes can leave orphaned encrypted objects; they can still be recovered offline, but no automatic orphan cleanup is included. Network filesystems must support suitable durable-write/atomic-rename semantics; test your selected recovery target.

Five unsuccessful ordinary mirror attempts move an item to **Needs attention**. Explicit retries are available from the dashboard. Telegram flood waits persist independently and are still respected after a manual retry. Pausing prevents new uploads; a transfer already in flight may finish.

The database is necessary for normal browsing and Telegram message lookup, but not for offline restoration from surviving `.av` files. There is no automated database re-indexer in this beta. After a disaster, restore plaintext with the CLI, initialize a new vault if necessary, and re-upload from restored/device originals.

## Telegram terms and distribution

Telegram requires an application-specific API ID and transparent disclosure of API use. The published API terms contain additional client-functionality requirements. This storage-focused beta is **not approved by Telegram**, and personal use does not establish that it satisfies every applicable requirement. Review current terms and obtain clarification before distributing a dedicated storage service. The application title and logo do not use Telegram branding.

The server's Telegram session can authorize actions as the account owner; encryption at rest does not make a compromised running server harmless. Keep it private and revoke it through the official Telegram client if exposed.

## Before trusting important files

Complete a real restore drill on your chosen recovery filesystem, verify the exact Android build on your phone under network loss/reboot, test Telegram sign-in and upload with non-sensitive files, and review the service with a security professional before wider deployment. These tasks need the actual deployment/account and cannot be established by local unit tests.

## Official/reference sources checked 21 October 2026

- Telegram API terms: https://core.telegram.org/api/terms
- Telegram API credentials and unofficial-client monitoring: https://core.telegram.org/api/obtaining_api_id
- Telegram API errors, including flood waits: https://core.telegram.org/api/errors
- Telethon sign-in: https://docs.telethon.dev/en/stable/basic/signing-in.html
- Telethon sessions and authorization sensitivity: https://docs.telethon.dev/en/stable/concepts/sessions.html
- Android persistent work: https://developer.android.com/develop/background-work/background-tasks/persistent
- Android document/folder access: https://developer.android.com/training/data-storage/shared/documents-files
- Android Keystore: https://developer.android.com/privacy-and-security/keystore
