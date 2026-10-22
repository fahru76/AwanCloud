# Validation record — 21 October 2026

## Passed

| Check | Result |
|---|---|
| Python tests (`python -m pytest -q`) | **31 passed** |
| Python compilation (`python -m compileall -q server`) | Passed |
| Browser JavaScript syntax (`node --check server/static/app.js`) | Passed |
| Android resource/manifest XML parse | Passed |
| Android Gradle build (`wrapper --gradle-version 8.11.1 :app:assembleDebug`) | **BUILD SUCCESSFUL**, 33 tasks executed |
| Android toolchain | Gradle 8.11.1, Android Gradle Plugin 8.9.2, JDK 17, compile/target SDK 35 |
| APK | Debug APK built and verified locally; excluded from the source repository |

## Test coverage

- Encryption round trip and absence of plaintext content/filename in stored ciphertext.
- Rejection of tampered envelopes and incorrect recovery keys.
- Recovery fallback after corruption of the primary object.
- Offline recovery after deleting the complete primary data directory/database.
- Refusal to overwrite an existing restore output.
- Path/filename validation and attachment-only downloads.
- Content deduplication, separate-source preservation and new-version retention.
- Repair of missing recovery data on repeated upload.
- Repair from original device content when both filesystem objects are missing but the database survives.
- Blocking acknowledgement when the recovery target is missing.
- Unauthorized file-access rejection, password/TOTP authentication, TOTP replay rejection and persistent login throttling.
- Host/origin checks, browser session protection, logout and device/owner permission separation.
- Upload size limits and browser security headers.
- Telegram Saved Messages target, persistent flood waits, paused operation and preservation of recovery files after authorization loss, using a simulated Telegram transport.

## Not verified here

- No physical Android phone or emulator execution, UI screenshots, reboot test, battery/Doze behavior, large folder test or device-specific Samsung behavior.
- No real Telegram login, send, download, account restriction event or account approval.
- No deployed domain, HTTPS certificate issuance, Docker runtime launch, actual NAS mount, disk-failure simulation or real off-site backup.
- No interactive browser UI testing or accessibility audit; the HTTP endpoints and static JavaScript syntax were checked.
- No independent security review, penetration test, dependency vulnerability audit or Play Store review.

The Python suite reports one upstream Starlette/TestClient deprecation warning about httpx. It does not fail the tests. The Android compiler reports use of deprecated Activity/WindowInsets APIs retained for compatibility; this is not a compile failure.

The included APK is **debuggable and intended for testing**. A production installation needs an appropriately signed release, actual device/live-service testing, deployment review and a restore drill. Automated tests and a successful build do not establish production security.
