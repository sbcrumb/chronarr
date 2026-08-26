# Chronarr Emby Plugin — Changelog

## v2.0.20 — Server Name & Admin Pre-fill
- Server name field is now read-only and sourced automatically from Emby's configured server name
- Admin username is pre-filled from the first Emby administrator account at startup
- Registration and validation payloads now include structured server and user blocks for improved license server tracking

## v2.0.19 — Movie Date Sync Fix
- Movies now resolve their IMDb ID from Emby's own metadata instead of requiring it in the folder name — standard naming (Movie (Year)) is fully supported for real-time sync and scheduled task

## v2.0.18 — TV Episode Date Sync
- Real-time sync and scheduled task now resolve the series IMDb ID from Emby's own metadata instead of requiring it to be embedded in the folder name — standard Radarr/Sonarr naming (Series (Year)) is fully supported

## v2.0.17 — Registration Error Handling
- Invalid or disposable email addresses now show a clear message in the plugin configuration page instead of a misleading network error after the offline grace period expires

## v2.0.16 — Database-Direct Sync + License Self-Heal
- License validation retries every hour when invalid — self-heals after transient server outages without waiting 23 hours
- Removed NFO file dependency — date lookups go directly to the Chronarr database; real-time sync no longer silently skips items without a sidecar NFO file
- Movies without an IMDb ID in the filename fall back to reading the ID from movie.nfo content if present

## v2.0.14 — Removed TLS Certificate Pinning
- Removed cert pinning from the license client — the pinned hash expired every 90 days on Let's Encrypt renewal, breaking check-ins for all users
- License responses are already protected by RSA signature verification; standard TLS CA validation is now used instead

## v2.0.13 — Platform Reporting
- License check-ins now identify the media server platform (Emby) so the admin panel can distinguish Emby from Jellyfin installs

## v2.0.12 — Security: Grace Period Hardening
- Offline grace period no longer bypasses an expired license — blocking the server after expiry is denied immediately
- Last server-validated expiry is stored in a signed state file; signature verified on every offline check

## v2.0.11 — Library Exclusions
- New: exclude specific Emby libraries from processing — config page shows checkboxes for each library
- Exclusions apply to both scheduled task and real-time sync
