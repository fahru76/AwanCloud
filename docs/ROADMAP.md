# Boundaries and next implementation stages

The included source implements a single-owner backup workflow. It deliberately preserves originals and avoids cloud deletion propagation. The following are **not implemented** and must not be presented as current capabilities:

- Full two-way filesystem sync, conflict resolution, selective cloud-to-device sync and offline editing.
- Large-file chunking/resumable upload, videos, thumbnails or photo-gallery previews.
- End-to-end encryption with keys held exclusively by Android/browser clients.
- Automated encryption-key rotation, passkeys, hardware-bound Telegram authorization or independent penetration-test certification.
- Multi-user hosting, sharing links, shared albums, role management or billing.
- An S3 API provider or automatic cloud-provider migration. Current recovery storage is a mounted filesystem; a provider-specific uploader would need its own verification and restore tests.
- Automated snapshot retention, storage quotas, delete/undelete UI, immutability or air-gapped rotation.
- Full database rebuild from `.av` envelopes, automatic orphan cleanup, or Telegram message reconciliation.
- Play Store submission, store privacy disclosures, account approval or guarantees against Telegram bans.

## Practical order for completing a personal deployment

1. Choose the trusted server and physically independent recovery location.
2. Review Telegram's current terms for this specialized use; resolve any applicability questions before wider distribution.
3. Configure HTTPS, owner login, offline key custody and recovery mount.
4. Install the Android beta on a test device; validate file selection, reboots, permission loss, token expiry and intermittent connectivity.
5. Link the real Telegram account locally and test small non-sensitive uploads/downloads, including restoring from Telegram.
6. Run a recovery drill with Telegram disconnected and without the original server database.
7. Only then consider large-file support, client-side encryption and a more complete Drive-style sync engine.

No hosting subscription, domain purchase, account connection, external repository push or production publication has been performed by this package.
