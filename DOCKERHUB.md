# Chronarr

**Comprehensive date and chronology management for Radarr and Sonarr**

Chronarr tracks "dateadded" timestamps for your movies and TV episodes, integrating directly with Radarr and Sonarr databases. Radarr and Sonarr don't reliably keep this date straight on their own — migrations lose it, upgrades overwrite it, manual additions never get one at all. Chronarr keeps its own PostgreSQL record of the real date, pulling from import history, release dates, and air dates as a fallback chain, and exposes it through a web UI you can edit by hand when something still needs fixing.

**[Join our Discord](https://discord.gg/XcMQY9k2jK)** for support and updates. Full docs live on [GitHub](https://github.com/sbcrumb/chronarr).

## What it does

- Multiple Radarr and/or Sonarr instances at once (standard + 4K, for example), each tracked and badged separately in the UI
- Real-time webhook updates on import, upgrade, and rename, plus bulk population for backfilling an existing library
- A web interface for browsing, filtering, and manually correcting dates and sources
- Emby and Jellyfin plugins that push the corrected date straight into your media server

## Quick Start

```bash
wget -O docker-compose.yml https://raw.githubusercontent.com/sbcrumb/chronarr/main/docker-compose.yml.example && \
echo "DB_PASSWORD=change_me_please" > .env && \
docker-compose up -d
```

That pulls down the example compose file, sets a database password, auto-generates `./config/.env` and `./config/.env.secrets` from embedded examples, and brings up all three containers (core, web, database).

## Tags

`latest` and version tags (e.g. `2.1.0`).

## Everything else

Configuration, multi-instance setup, webhooks, the Emby/Jellyfin plugins, troubleshooting, and the changelog are all in the main repo: **[github.com/sbcrumb/chronarr](https://github.com/sbcrumb/chronarr)**

Issues: [github.com/sbcrumb/chronarr/issues](https://github.com/sbcrumb/chronarr/issues) · License: MIT
