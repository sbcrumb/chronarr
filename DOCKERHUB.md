# Chronarr

**Comprehensive date and chronology management for Radarr and Sonarr**

Chronarr tracks and manages "dateadded" timestamps for all your movies and TV episodes, integrating directly with Radarr and Sonarr databases. Keep accurate library chronology for sorting, organizing, and understanding when content was added to your collection.

**[Join our Discord community](https://discord.gg/XcMQY9k2jK)** for support, updates, and discussion.
Full documentation: [github.com/sbcrumb/chronarr](https://github.com/sbcrumb/chronarr)

## Why Chronarr?

**The Problem**: Radarr and Sonarr don't consistently track when media was added to your library. Import dates get lost during migrations, upgrades replace dates, and manual additions have no timestamp at all.

**The Solution**: Chronarr maintains a dedicated PostgreSQL database tracking every movie and episode's true "dateadded" timestamp, pulling from multiple authoritative sources and presenting them in a clean web interface.

## Features

- **Intelligent Date Tracking** — multiple sources (import history, digital/physical release, air date) with smart fallback, manual override, and skipped-item tracking
- **Multi-Instance Support** — run multiple Radarr and/or Sonarr instances (e.g. standard + 4K), each tracked independently with per-instance badges and filtering
- **Powerful Web Interface** — browse/filter/search your collection, bulk database population, real-time statistics dashboard
- **Database-First Architecture** — PostgreSQL backend, full audit trail, connection pooling
- **Emby & Jellyfin Plugins** — syncs accurate import dates directly into your media server
- **Webhook Support** — real-time updates on import, upgrade, and rename events
- **Production Ready** — 3-container Docker Compose architecture, health checks, structured logging

## Quick Start

```bash
wget -O docker-compose.yml https://raw.githubusercontent.com/sbcrumb/chronarr/main/docker-compose.yml.example && \
echo "DB_PASSWORD=change_me_please" > .env && \
docker-compose up -d
```

This downloads the example compose file, sets a database password, auto-generates `./config/.env` and `./config/.env.secrets` from embedded examples, and starts all three containers (core, web, database).

## Image Tags

- `latest` / `<version>` — e.g. `sbcrumb/chronarr:2.1.0`

## Full Documentation

Configuration, multi-instance setup, webhook setup, the Emby/Jellyfin plugins, troubleshooting, and the full changelog all live in the main repository:

👉 **[github.com/sbcrumb/chronarr](https://github.com/sbcrumb/chronarr)**

## Support

- **GitHub Issues**: [github.com/sbcrumb/chronarr/issues](https://github.com/sbcrumb/chronarr/issues)
- **Discord**: [discord.gg/XcMQY9k2jK](https://discord.gg/XcMQY9k2jK)

## License

MIT License — see the [LICENSE](https://github.com/sbcrumb/chronarr/blob/main/LICENSE) file in the repository.
