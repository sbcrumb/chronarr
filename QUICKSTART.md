# Chronarr Quick Start

## One-Command Setup

```bash
# Download docker-compose.yml.example, rename it, and start Chronarr
wget -O docker-compose.yml https://raw.githubusercontent.com/sbcrumb/chronarr/main/docker-compose.yml.example && \
echo "DB_PASSWORD=change_me_please" > .env && \
docker-compose up -d
```

That's it! Config files (`.env` and `.env.secrets`) will be auto-generated in `./config/`

## What Just Happened?

1. **Downloaded** docker-compose.yml.example as docker-compose.yml
2. **Created** root `.env` with temporary database password
3. **Created** `./config/.env` from embedded example
4. **Created** `./config/.env.secrets` from embedded example
5. **Started** all 3 containers (core, web, database)

## Next Steps

### 1. Configure Your Setup

```bash
# Edit main configuration
nano ./config/.env

# Edit sensitive data (API keys, passwords)
nano ./config/.env.secrets
```

**Required Settings:**
```bash
# IMPORTANT: Update root .env file (next to docker-compose.yml)
# This is used by Docker Compose for ${DB_PASSWORD} variable substitution
# Edit the root .env file:
nano .env

# Set a secure password:
DB_PASSWORD=your_secure_database_password

# Then also update ./config/.env.secrets with the SAME password:
nano ./config/.env.secrets

# In ./config/.env.secrets:
DB_PASSWORD=your_secure_database_password  # Must match root .env!

# Optional but recommended (in ./config/.env.secrets):
RADARR_API_KEY=your_radarr_api_key
SONARR_API_KEY=your_sonarr_api_key
TMDB_API_KEY=your_tmdb_api_key
```

**Optional Settings in ./config/.env:**
```bash
# Radarr connection
RADARR_URL=http://radarr:7878

# Sonarr connection
SONARR_URL=http://sonarr:8989

# Media paths (update volume mounts in docker-compose.yml)
MOVIE_PATHS=/media/Movies/movies
TV_PATHS=/media/TV/tv
```

### 2. Update Media Paths

Edit `docker-compose.yml` to point to your media:

```yaml
chronarr:
  volumes:
    - ./config:/config
    - /your/movies:/media/Movies:ro  # ← Change this
    - /your/tv:/media/TV:ro          # ← Change this
    - chronarr_data:/app/data
    - chronarr_logs:/app/data/logs
```

### 3. Restart Services

```bash
docker-compose restart
```

### 4. Populate Database

1. Open web interface: `http://your-server:8081`
2. Click **Tools** in the sidebar
3. Click **Populate Database**
4. Select **Movies** and/or **TV Shows**
5. Click **Start Population**

## Access Points

- **Web Interface**: `http://your-server:8081`
- **Core API**: `http://your-server:8080`
- **Database**: `localhost:5432` (optional external access)

## Configuration Files Location

**Two locations for config files:**

1. **Root directory** (same location as docker-compose.yml):
   - `.env` - Docker Compose variables (DB_PASSWORD for PostgreSQL initialization)

2. **Config directory** (`./config/`):
   - `./config/.env` - Main application configuration
   - `./config/.env.secrets` - API keys and passwords (including DB_PASSWORD)

**Important:** The `DB_PASSWORD` must be set in BOTH places:
- Root `.env` → Used by Docker Compose to create the PostgreSQL database
- `./config/.env.secrets` → Used by Chronarr to connect to the database

## Webhook Setup (Optional)

### Radarr
1. Go to **Settings → Connect**
2. Add **Webhook** connection:
   - Name: `Chronarr`
   - URL: `http://chronarr-core:8080/radarr/webhook`
   - Triggers: On Import, On Upgrade, On Rename

### Sonarr
1. Go to **Settings → Connect**
2. Add **Webhook** connection:
   - Name: `Chronarr`
   - URL: `http://chronarr-core:8080/sonarr/webhook`
   - Triggers: On Import, On Upgrade, On Rename, On Episode File Delete

## Useful Commands

```bash
# View logs
docker-compose logs -f chronarr
docker-compose logs -f chronarr-web

# Restart after config changes
docker-compose restart

# Stop all services
docker-compose down

# Update to latest version
docker-compose pull && docker-compose up -d

# Check status
docker-compose ps
```

## Troubleshooting

### Config files not created?
Check container logs:
```bash
docker logs chronarr-core
```

You should see:
```
✅ Created /config/.env
✅ Created /config/.env.secrets
```

### Database connection failed?
1. Check `DB_PASSWORD` is set in `./config/.env.secrets`
2. Restart: `docker-compose restart`

### Can't access web interface?
1. Check port 8081 is not in use: `netstat -tuln | grep 8081`
2. Check firewall allows port 8081
3. View logs: `docker logs chronarr-web`

## Advanced Configuration

### Database Access Configuration

**IMPORTANT:** Radarr requires direct database access. Sonarr can use API-only mode, but database access is recommended for better performance.

Configure database access in `./config/.env`:

```bash
# Radarr database (REQUIRED - PostgreSQL or SQLite)
RADARR_DB_TYPE=postgresql
RADARR_DB_HOST=radarr-db
RADARR_DB_NAME=radarr-main
RADARR_DB_USER=radarr
RADARR_DB_PASSWORD=radarr_password  # Add to .env.secrets

# Radarr database (SQLite alternative)
# RADARR_DB_TYPE=sqlite
# RADARR_DB_PATH=/path/to/radarr.db

# Sonarr database (OPTIONAL - PostgreSQL or SQLite)
# Recommended for better performance, but API-only mode works
SONARR_DB_TYPE=postgresql
SONARR_DB_HOST=sonarr-db
SONARR_DB_NAME=sonarr-main
SONARR_DB_USER=sonarr
SONARR_DB_PASSWORD=sonarr_password  # Add to .env.secrets

# Sonarr database (SQLite alternative)
# SONARR_DB_TYPE=sqlite
# SONARR_DB_PATH=/path/to/sonarr.db
```

**Why does Radarr require database access?**
The Radarr API doesn't expose all import history data needed for accurate date tracking. Direct database access allows Chronarr to query import timestamps, detect upgrades vs new imports, and handle complex scenarios.

### Multi-Instance Setup (Multiple Radarr/Sonarr)

Running a standard + 4K library split (or any other multi-instance setup)? Add a
`NAME` segment between the prefix and variable suffix — e.g. `RADARR_4K_URL`. Each
named instance is fully self-contained: it needs its own `_URL`, `_API_KEY`,
`_ROOT_FOLDERS`, its own paths variable (`RADARR_4K_MOVIE_PATHS`, not the global
`MOVIE_PATHS`), and — if using SQLite — its own `_DB_TYPE`/`_DB_PATH` **and its own
volume mount**, distinct from the main instance's:

```yaml
# docker-compose.yml — one mount per SQLite instance
chronarr:
  volumes:
    - /path/to/radarr/config:/radarr-data:ro          # RADARR_DB_PATH=/radarr-data/radarr.db
    - /path/to/radarr-4k/config:/radarr-4k-data:ro     # RADARR_4K_DB_PATH=/radarr-4k-data/radarr.db
```

```bash
# ./config/.env
RADARR_4K_URL=http://radarr-4k:7878
RADARR_4K_API_KEY=your_4k_api_key           # → set in .env.secrets
RADARR_4K_ROOT_FOLDERS=/mnt/unionfs/Media/Movies/movies4k
RADARR_4K_MOVIE_PATHS=/media/movies4k
RADARR_4K_DB_TYPE=sqlite
RADARR_4K_DB_PATH=/radarr-4k-data/radarr.db
```

Reusing the main instance's mount point or `_DB_PATH` for a second instance is the
most common cause of a "connected but returns no data" instance — each one needs
its own distinct container path. See the README's Multi-Instance Configuration
section and `docker-compose.yml.example` for the full annotated reference, and
visit `/setup` after restarting to confirm each instance's webhook URL and
connection status.

### Emby Plugin Deployment

To auto-deploy the Chronarr Emby plugin:

1. Edit `docker-compose.yml`
2. Uncomment the emby-plugins volume:
```yaml
chronarr:
  volumes:
    - /path/to/emby/plugins:/emby-plugins  # ← Add this
```
3. Restart: `docker-compose restart chronarr`

Plugin will be automatically copied to Emby on container start!

## Support

- **Discord**: https://discord.gg/ZykJRGt72b
- **GitHub Issues**: https://github.com/sbcrumb/chronarr/issues
- **Documentation**: https://github.com/sbcrumb/chronarr

---

**That's it!** Your Chronarr instance should now be running with auto-generated configuration files.
