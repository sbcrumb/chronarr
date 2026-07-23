# Chronarr Plugin Changelog

Full version history for the Emby and Jellyfin plugins. The config page inside each plugin shows the latest 5 entries only.

---

## v2.0.16 — Database-Direct Sync + License Self-Heal

- **Fix:** License validation now retries every hour when invalid (previously waited the full 23-hour interval), allowing the plugin to self-heal after a transient server outage without user intervention
- **Refactor:** Removed NFO file dependency — date lookups now go directly to the Chronarr database without requiring a sidecar NFO file to exist alongside the media. This fixes real-time sync silently skipping newly imported items that haven't had NFO files written yet
- Movies without an IMDb ID in the filename fall back to reading the ID from `movie.nfo` content if one is present

## v2.0.15 — Version correction (same code as v2.0.16, AssemblyInfo fix)

- Internal version number corrected so Emby displays the right version in the plugin catalog

## v2.0.14 — Removed TLS Certificate Pinning

- **Fix:** Removed TLS certificate pinning from the license client — the pinned leaf cert hash was expiring every 90 days (Let's Encrypt rotation), breaking license check-ins for all users and requiring a plugin rebuild each cycle
- License server responses are already protected by RSA signature verification, making cert pinning redundant
- Standard TLS CA validation is now used and will not break on routine certificate renewals

## v2.0.13 — Platform Reporting

- License check-ins now identify the media server platform (Emby vs Jellyfin), so the license admin panel can distinguish installs by server type

## v2.0.12 — Security: Grace Period Hardening

- Offline grace period no longer bypasses an expired license — blocking the license server after expiry is denied immediately
- Last server-validated expiry is stored in a signed state file; signature verified on every offline check

## v2.0.11 — Library Exclusions

- New: exclude specific libraries from processing — config page shows checkboxes for each library
- Exclusions apply to both scheduled task and real-time sync

## v2.0.10 — Bug Fixes

- Fixed license validation always failing — CheckIntegrity int32 overflow after ~25 days uptime
- Scheduled task no longer re-validates license on every run — uses cached startup state
- Fixed config page showing "NFOGuard Configuration" instead of "Chronarr Configuration"

## v2.0.9 — Security Hardening (MEDIUM)

- Removed ineffective AntiDebug checks — eliminates startup latency
- HttpClient socket leak fixed — WebhookLookup now uses shared static instance
- Email validation strengthened — uses MailAddress parser instead of string checks
- Client-side license call rate limiting — minimum 23h between server contacts
- Exception messages sanitized — no internal paths in log output

## v2.0.8 — Security Hardening (HIGH)

- IMDb ID validation — format and length checked before use in URLs
- ReDoS protection — NFO regex patterns capped with timeouts
- Certificate pinning — license server connection verified by cert hash
- Removed reflection from license status controller
- RSA-signed license responses — server signs, plugin verifies (forgery protection)

## v2.0.7 — Security Hardening (CRITICAL)

- Fixed critical offline grace period exploit — now persists across restarts (48h max)
- Removed `#if DEBUG` SSL bypass from license validation
- Removed hardcoded XOR encryption key
- Chronarr main app version now reported to license server on each check-in
- Fixed config page controller name mismatch (was showing error on open)
- Fixed license status URL (was calling wrong endpoint)

## v2.0.4 — Database-First Strategy

- **Movies:** Database-first approach using PostgreSQL lookup
- **TV Shows:** Hybrid approach — NFO first with database fallback
- Enhanced logging and improved filename parsing
- Better error handling for media items
