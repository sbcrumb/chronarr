# Chronarr

[![Docker Pulls](https://img.shields.io/docker/pulls/sbcrumb/chronarr.svg)](https://hub.docker.com/r/sbcrumb/chronarr)
[![Docker Image Version](https://img.shields.io/docker/v/sbcrumb/chronarr?sort=semver)](https://hub.docker.com/r/sbcrumb/chronarr)
[![Docker Image Size](https://img.shields.io/docker/image-size/sbcrumb/chronarr/latest)](https://hub.docker.com/r/sbcrumb/chronarr)

**[Join our Discord community](https://discord.gg/XcMQY9k2jK)** for support, updates, and discussion.

**Comprehensive date and chronology management for Radarr and Sonarr**

Chronarr tracks and manages "dateadded" timestamps for all your movies and TV episodes, integrating directly with Radarr and Sonarr databases. Keep accurate library chronology for sorting, organizing, and understanding when content was added to your collection.

## Why Chronarr?

**The Problem**: Radarr and Sonarr don't consistently track when media was added to your library. Import dates get lost during migrations, upgrades replace dates, and manual additions have no timestamp at all.

**The Solution**: Chronarr maintains a dedicated PostgreSQL database tracking every movie and episode's true "dateadded" timestamp, pulling from multiple authoritative sources and presenting them in a clean web interface.

## Features

### **Intelligent Date Tracking**
- **Multiple Date Sources** - Prioritizes Radarr/Sonarr import history, digital release dates, physical releases, and air dates
- **Import History Integration** - Direct database queries to Radarr/Sonarr for accurate import timestamps
- **Fallback Logic** - Smart fallback hierarchy ensures every item gets the most accurate date possible
- **Manual Override** - Web interface allows manual date entry and source management
- **Skipped Item Tracking** - Identifies and tracks items without valid dates for later resolution

### **Powerful Web Interface**
- **Movie & TV Management** - Browse, filter, and search your entire collection
- **Date Editing** - Update dates and sources with smart date picker and pre-populated options
- **Bulk Operations** - Database population from Radarr/Sonarr with progress tracking
- **Smart Filtering** - Filter by date status, source type, and video file presence
- **IMDb ID Migration** - Update placeholder IMDb IDs for manually-added items
- **Real-time Statistics** - Dashboard with source distribution, missing dates, and recent activity

### **Database-First Architecture**
- **PostgreSQL Backend** - Production-ready relational database with ACID compliance
- **Efficient Queries** - Optimized indexes and batch operations
- **Data Integrity** - Foreign keys, constraints, and validation
- **Processing History** - Full audit trail of all database operations
- **Connection Pooling** - High-performance database connection management

### **Radarr & Sonarr Integration**
- **Direct Database Access** - Required for Radarr, optional for Sonarr (PostgreSQL & SQLite support)
- **API Integration** - Sonarr API support for metadata and series lookups
- **Webhook Support** - Real-time updates on import, upgrade, and rename events
- **Multi-Instance Support** - Run multiple Radarr instances (e.g., standard + 4K) and/or multiple Sonarr instances, each tracked independently with per-instance badges and filtering
- **Bulk Import** - One-click population of entire Radarr/Sonarr libraries across all instances
- **Path Mapping** - Intelligent path translation for Docker/remote setups

### **Jellyfin Plugin**
- **Third-Party Plugin** - Install via custom repository URL
- **Automatic Date Sync** - Syncs accurate import dates from Chronarr to Jellyfin
- **Real-time Updates** - Monitors library scans and updates dates on the fly
- **Easy Installation** - Add repository URL and install from Jellyfin dashboard

### **Production Ready**
- **Docker Compose** - 3-container architecture (core, web, database)
- **Auto-Configuration** - Config files auto-generated from embedded examples on first run
- **Health Monitoring** - Kubernetes-ready health checks and status endpoints
- **Graceful Shutdown** - Proper signal handling for container orchestration
- **Async Operations** - Non-blocking I/O for responsive web interface
- **Comprehensive Logging** - Structured logging with multiple log levels

## Use Cases

- **Library Organization** - Sort and filter media by actual acquisition date, not modified time
- **Collection Management** - Track when items were added vs when they were released
- **Jellyfin Integration** - Sync accurate import dates to Jellyfin via the official plugin
- **Migration Safety** - Preserve dateadded timestamps across Radarr/Sonarr database migrations
- **Manual Additions** - Assign proper dates to manually-added content
- **Upgrade Tracking** - Maintain original import dates even after quality upgrades
- **Statistical Analysis** - Understand library growth patterns and collection habits

## Quick Start

**One-command setup with auto-configuration!**

### 1. Download and Start

```bash
wget -O docker-compose.yml https://raw.githubusercontent.com/sbcrumb/chronarr/main/docker-compose.yml.example && \
echo "DB_PASSWORD=change_me_please" > .env && \
docker-compose up -d
```

**What just happened?**
- Downloaded docker-compose.yml.example as docker-compose.yml
- Created root `.env` with temporary database password
- Auto-created `./config/.env` from embedded example
- Auto-created `./config/.env.secrets` from embedded example
- Started all containers (core, web, database)

### 2. Configure Your Setup

Edit the auto-generated config files:

```bash
nano ./config/.env
nano ./config/.env.secrets
```

**Required Settings:**
```bash
# 1. FIRST: Update root .env file (next to docker-compose.yml)
#    This is used by Docker Compose for PostgreSQL initialization
nano .env

# Set a secure password:
DB_PASSWORD=your_secure_database_password

# 2. THEN: Update ./config/.env.secrets with the SAME password
nano ./config/.env.secrets

# In ./config/.env.secrets:
DB_PASSWORD=your_secure_database_password  # Must match root .env!

# API Keys (optional but recommended):
RADARR_API_KEY=your_radarr_api_key
SONARR_API_KEY=your_sonarr_api_key
TMDB_API_KEY=your_tmdb_api_key
```

**Note:** `DB_PASSWORD` must be in BOTH locations:
- Root `.env` → Docker Compose uses this to create PostgreSQL database
- `./config/.env.secrets` → Chronarr uses this to connect to the database

**Optional Settings (in `./config/.env`):**
```bash
# Radarr connection
RADARR_URL=http://radarr:7878

# Sonarr connection
SONARR_URL=http://sonarr:8989

# Direct Database Access (faster - recommended)
RADARR_DB_TYPE=postgresql
RADARR_DB_HOST=radarr-db
RADARR_DB_NAME=radarr-main
RADARR_DB_PASSWORD=radarr_password  # Add to .env.secrets

# SQLite alternative for Radarr
# RADARR_DB_TYPE=sqlite
# RADARR_DB_PATH=/path/to/radarr.db

SONARR_DB_TYPE=postgresql
SONARR_DB_HOST=sonarr-db
SONARR_DB_NAME=sonarr-main
SONARR_DB_PASSWORD=sonarr_password  # Add to .env.secrets

# SQLite alternative for Sonarr
# SONARR_DB_TYPE=sqlite
# SONARR_DB_PATH=/path/to/sonarr.db
```

### 3. Update Media Paths and Database Access

Edit your `docker-compose.yml` to configure paths:

**Media Paths:**
```yaml
chronarr:
  volumes:
    - ./config:/config
    - /your/movies:/media/Movies:ro  # ← Change this
    - /your/tv:/media/TV:ro          # ← Change this
```

**SQLite Database Access (Required for SQLite-based Radarr/Sonarr):**

If your Radarr or Sonarr uses SQLite (not PostgreSQL), you MUST mount the database directory:

```yaml
chronarr:
  volumes:
    # ... other volumes ...
    # Radarr SQLite database (read-only)
    - /path/to/radarr/config:/radarr-config:ro
    # Sonarr SQLite database (read-only)
    - /path/to/sonarr/config:/sonarr-config:ro
```

Then update `./config/.env`:
```bash
# For Radarr SQLite
RADARR_DB_TYPE=sqlite
RADARR_DB_PATH=/radarr-config/radarr.db

# For Sonarr SQLite
SONARR_DB_TYPE=sqlite
SONARR_DB_PATH=/sonarr-config/sonarr.db
```

**Common SQLite Database Locations:**
- **Docker containers**: Mount the config volume (e.g., `/path/to/radarr/config`)
- **Windows**: `C:\ProgramData\Radarr` or `C:\ProgramData\Sonarr`
- **Linux**: `/home/user/.config/Radarr` or `/var/lib/radarr`

### 4. Restart and Populate

```bash
# Apply configuration changes
docker-compose restart
```

Browse to `http://your-server:8081`

Then in the web interface:
1. Open the sidebar and click **Tools**
2. Click **Populate Database**
3. Select **Movies** and/or **TV Shows**
4. Click **Start Population**

Watch as Chronarr imports all your media with proper dates!

> **📖 For detailed setup instructions, see [QUICKSTART.md](QUICKSTART.md)**

## Folder Naming

Chronarr works with standard Radarr/Sonarr folder naming out of the box — no changes required.

**Standard naming (always works):**
```
/movies/Selena (1997)/
/tv/Breaking Bad (2008)/
```

**Optional — embed IMDb ID in folder name:**
```
/movies/Selena (1997) [imdb-tt0120094]/
/tv/Breaking Bad (2008) [imdb-tt0903747]/
```

When an IMDb ID is present in the folder or file name, Chronarr cross-checks it against the webhook payload as an extra validation step. If a conflicting ID is found, the webhook is rejected to prevent processing the wrong media. If no ID is present, the webhook payload is trusted as the authoritative source — which is correct for all standard naming setups.

**Radarr** — if your movie file naming includes `[{ImdbId}]`, Chronarr detects it from the filename inside the folder even when the folder name itself is standard.

**Sonarr** — the series folder name is checked. If your series folder format includes `[imdb-{ImdbId}]`, Chronarr will cross-check on every TV webhook.

Supported IMDb formats in folder/file names: `[imdb-tt1234567]`, `[tt1234567]`, `{imdb-tt1234567}`, `(imdb-tt1234567)`.

## Architecture

Chronarr uses a 3-container Docker Compose architecture:

```
┌─────────────────┐     ┌──────────────────┐     ┌──────────────────┐
│  chronarr-web   │────▶│  chronarr-core   │────▶│  chronarr-db     │
│  (Port 8081)    │     │  (Port 8080)     │     │  (PostgreSQL)    │
│                 │     │                  │     │                  │
│  - Web UI       │     │  - Webhooks      │     │  - Movie dates   │
│  - API routes   │     │  - Processing    │     │  - Episode dates │
│  - Dashboard    │     │  - Database ops  │     │  - History       │
└─────────────────┘     └──────────────────┘     └──────────────────┘
         │                       │                         │
         │                       │                         │
         ▼                       ▼                         ▼
    ┌─────────────────────────────────────┐     ┌──────────────────┐
    │   Radarr/Sonarr Databases & APIs    │     │  Jellyfin Server │
    └─────────────────────────────────────┘     │  + Plugin        │
                                                 └──────────────────┘
```

**Benefits:**
- Web interface remains responsive during large scans
- Core processing isolated from user interactions
- Database optimized for concurrent access
- Independent scaling and updates

## Date Source Priority

Chronarr uses an intelligent priority system to determine the best date for each item:

### Movies
1. **Radarr Import Date** - Direct from Radarr's import history (most accurate)
2. **Digital Release Date** - From TMDB via Radarr
3. **Physical Release Date** - From TMDB via Radarr
4. **Theatrical Release Date** - From TMDB via Radarr
5. **Manual Entry** - User-specified date via web interface

### TV Episodes
1. **Sonarr Import Date** - Direct from Sonarr's import history (most accurate)
2. **Air Date** - Original broadcast date
3. **Manual Entry** - User-specified date via web interface

## Configuration

### Environment Variables

**Database Configuration:**
```bash
DB_TYPE=postgresql          # Database type (postgresql only)
DB_HOST=chronarr-db         # Database hostname
DB_PORT=5432                # Database port
DB_NAME=chronarr            # Database name
DB_USER=chronarr            # Database user
DB_PASSWORD=secure_pass     # Database password (.env.secrets)
```

**Radarr Integration:**
```bash
RADARR_URL=http://radarr:7878        # Radarr URL (optional, for metadata only)
RADARR_API_KEY=your_key              # Radarr API key (.env.secrets)

# REQUIRED: Direct database access for import history
RADARR_DB_TYPE=postgresql            # postgresql or sqlite
RADARR_DB_HOST=radarr-db             # Radarr PostgreSQL host
RADARR_DB_NAME=radarr-main           # Radarr database name
RADARR_DB_USER=radarr                # Radarr database user
RADARR_DB_PASSWORD=radarr_pass       # Radarr database password (.env.secrets)

# SQLite alternative
# RADARR_DB_TYPE=sqlite
# RADARR_DB_PATH=/path/to/radarr.db
# IMPORTANT: Docker users must mount the SQLite database directory!
# See docker-compose.yml.example for volume mount configuration
```

**Sonarr Integration:**
```bash
SONARR_URL=http://sonarr:8989        # Sonarr URL (required)
SONARR_API_KEY=your_key              # Sonarr API key (.env.secrets)

# Optional: Direct database access (recommended for better performance)
SONARR_DB_TYPE=postgresql            # postgresql or sqlite
SONARR_DB_HOST=sonarr-db             # Sonarr PostgreSQL host
SONARR_DB_NAME=sonarr-main           # Sonarr database name
SONARR_DB_USER=sonarr                # Sonarr database user
SONARR_DB_PASSWORD=sonarr_pass       # Sonarr database password (.env.secrets)

# SQLite alternative
# SONARR_DB_TYPE=sqlite
# SONARR_DB_PATH=/path/to/sonarr.db
# IMPORTANT: Docker users must mount the SQLite database directory!
# See docker-compose.yml.example for volume mount configuration
```

**Multi-Instance Configuration (v3.0+):**

Add additional Radarr or Sonarr instances using a `NAME` segment between the prefix and the variable suffix. The name becomes the instance identifier in Chronarr's UI and database.

Each instance block is fully self-contained — define all settings including paths directly within it. **Do not use the global `MOVIE_PATHS` or `TV_PATHS` keys in additional instance blocks.** If those keys appear more than once in your env file, Docker only keeps the last value and silently drops the rest, corrupting path matching for every instance.

```bash
# Main Radarr instance — use RADARR_MOVIE_PATHS, not MOVIE_PATHS
RADARR_URL=http://radarr:7878
RADARR_API_KEY=your_api_key         # (.env.secrets)
RADARR_ROOT_FOLDERS=/mnt/nas/Movies
RADARR_MOVIE_PATHS=/media/movies
RADARR_DB_TYPE=sqlite
RADARR_DB_PATH=/radarr-data/radarr.db

# Second Radarr instance (e.g., 4K library)
RADARR_4K_URL=http://radarr-4k:7878
RADARR_4K_API_KEY=your_4k_api_key   # (.env.secrets)
RADARR_4K_ROOT_FOLDERS=/mnt/nas/Movies-4K
RADARR_4K_MOVIE_PATHS=/media/movies-4k   # ← per-instance, NOT MOVIE_PATHS
RADARR_4K_DB_TYPE=sqlite
RADARR_4K_DB_PATH=/radarr-4k-data/radarr.db

# Main Sonarr instance — use SONARR_TV_PATHS, not TV_PATHS
SONARR_URL=http://sonarr:8989
SONARR_API_KEY=your_sonarr_key      # (.env.secrets)
SONARR_ROOT_FOLDERS=/mnt/nas/TV
SONARR_TV_PATHS=/media/tv
SONARR_DB_TYPE=sqlite
SONARR_DB_PATH=/sonarr-data/sonarr.db

# Second Sonarr instance (e.g., anime library)
SONARR_ANIME_URL=http://sonarr-anime:8989
SONARR_ANIME_API_KEY=your_anime_key  # (.env.secrets)
SONARR_ANIME_ROOT_FOLDERS=/mnt/nas/Anime
SONARR_ANIME_TV_PATHS=/media/anime   # ← per-instance, NOT TV_PATHS
SONARR_ANIME_DB_TYPE=sqlite
SONARR_ANIME_DB_PATH=/sonarr-anime-data/sonarr.db
```

Each named instance gets its own webhook endpoint (`/radarr_4k/webhook`, `/sonarr_anime/webhook`) and appears as a separate entry in the sidebar. An "All" view aggregates across all instances with colored instance badges on each row.

**SQLite Docker Configuration (multi-instance):**

Each SQLite database needs its own volume mount in `docker-compose.yml`. The container path you choose must match the `_DB_PATH` value in your `.env`:

```yaml
# In docker-compose.yml, under chronarr-core volumes:
- /host/path/to/radarr/config:/radarr-data:ro          # → RADARR_DB_PATH=/radarr-data/radarr.db
- /host/path/to/radarr-4k/config:/radarr-4k-data:ro    # → RADARR_4K_DB_PATH=/radarr-4k-data/radarr.db
- /host/path/to/sonarr/config:/sonarr-data:ro           # → SONARR_DB_PATH=/sonarr-data/sonarr.db
```

The `radarr.db` file is usually at the top level of Radarr's config directory. If the database fails to open, browse that directory on your host to find the actual filename and depth, then adjust `DB_PATH` accordingly. See `docker-compose.yml.example` for a complete annotated example.

## Web Interface

The web interface uses a dark sidebar for navigation. Sections expand to show per-instance sub-items; clicking an instance filters the view to that instance only. An "All" sub-item shows the full library with colored instance badges on each row.

### Dashboard
- **Statistics** - Total movies, episodes, dates populated, missing dates
- **Source Distribution** - Pie charts showing date source breakdown
- **Recent Activity** - Last 7 days of processing history
- **Skipped Items** - Items without valid dates

### Movies
- **Search & Filter** - By title, path, IMDb ID, date status, source
- **Instance Filter** - Click an instance in the sidebar or view all with badges
- **Bulk Actions** - Delete, edit dates, update IMDb IDs
- **Smart Sorting** - By date added, release date, title
- **Debug Tools** - Raw database inspection for troubleshooting

### TV Shows
- **Series Management** - View all series with episode counts and progress
- **Episode Browsing** - Detailed episode lists with dates and sources
- **Season Filtering** - Filter episodes by season
- **Delete Series** - Remove an entire series and all its episode records
- **Instance Filter** - Click an instance in the sidebar or view all with badges
- **Batch Updates** - Update multiple episodes at once

### Tools
- **Database Population** - One-click import from Radarr/Sonarr across all instances
- **Progress Tracking** - Real-time progress bars and statistics
- **Validation** - Pre-population checks for connectivity and permissions

## API Endpoints

### Movies
- `GET /api/movies` - List all movies with pagination
- `GET /api/movies/{imdb_id}` - Get specific movie details
- `PUT /api/movies/{imdb_id}` - Update movie date and source
- `DELETE /api/movies/{imdb_id}` - Delete movie from database
- `GET /api/movies/{imdb_id}/date-options` - Get available date options for movie
- `POST /api/movies/{imdb_id}/migrate-imdb` - Migrate placeholder IMDb ID to real ID

### TV Shows
- `GET /api/series` - List all series with episode counts (`?instance=sonarr` to filter)
- `DELETE /api/series/{imdb_id}` - Delete an entire series and all its episodes (`?instance=sonarr`)
- `GET /api/series/{imdb_id}/episodes` - Get episodes for series
- `GET /api/episodes/{imdb_id}/{season}/{episode}` - Get specific episode
- `PUT /api/episodes/{imdb_id}/{season}/{episode}` - Update episode date
- `DELETE /api/episodes/{imdb_id}/{season}/{episode}` - Delete episode
- `POST /api/series/{imdb_id}/migrate-imdb` - Migrate series IMDb ID

### Administration
- `POST /admin/populate-database` - Trigger database population across all configured instances
- `GET /api/dashboard` - Get dashboard statistics
- `GET /health` - Health check endpoint

## Webhook Configuration

Each Radarr/Sonarr instance gets its own webhook endpoint. The URL path matches the instance name derived from the environment variable: `RADARR_URL` → `/radarr/webhook`, `RADARR_4K_URL` → `/radarr_4k/webhook`.

### Radarr
1. Go to **Settings → Connect**
2. Add **Webhook** connection
3. Configure:
   - **Name**: Chronarr
   - **URL**: `http://chronarr-core:8080/radarr/webhook` (default instance)
   - **Triggers**: On Import, On Upgrade, On Rename
   - **Tags**: (optional, leave blank for all movies)

For a second instance (e.g., `RADARR_4K_URL`), use `http://chronarr-core:8080/radarr_4k/webhook`.

### Sonarr
1. Go to **Settings → Connect**
2. Add **Webhook** connection
3. Configure:
   - **Name**: Chronarr
   - **URL**: `http://chronarr-core:8080/sonarr/webhook` (default instance)
   - **Triggers**: On Import, On Upgrade, On Rename, On Episode File Delete
   - **Tags**: (optional, leave blank for all series)

For a second instance (e.g., `SONARR_ANIME_URL`), use `http://chronarr-core:8080/sonarr_anime/webhook`.

## Jellyfin Integration

Chronarr includes a Jellyfin plugin that automatically syncs episode and movie dates to Jellyfin, ensuring your media library displays the correct import dates from Chronarr instead of scan dates.

### Features
- **Automatic Date Sync** - Syncs PremiereDate to DateCreated for TV episodes and movies
- **Real-time Updates** - Monitors Jellyfin library scans and updates dates on the fly
- **Scheduled Tasks** - Optional scheduled task for periodic synchronization
- **Chronarr Integration** - Pulls accurate import dates from Chronarr's database

### Installation

1. **Add the Chronarr Plugin Repository** to Jellyfin:
   - Navigate to **Dashboard → Plugins → Repositories**
   - Click the **+** button to add a new repository
   - Enter the repository URL:
     ```
     https://raw.githubusercontent.com/sbcrumb/chronarr-jellyfin-plugin/main/manifest.json
     ```

2. **Install the Plugin**:
   - Go to **Plugins → Catalog**
   - Find and install **Chronarr**
   - Restart Jellyfin

3. **Configure the Plugin**:
   - Go to **Dashboard → Plugins → Chronarr**
   - Enter your Chronarr API URL (e.g., `http://chronarr-core:8080`)
   - Save settings

### Requirements
- Jellyfin 10.8.0 or higher
- Chronarr webhook service running

For more information, visit the [Chronarr Jellyfin Plugin Repository](https://github.com/sbcrumb/chronarr-jellyfin-plugin).

## Troubleshooting

### Database Connection Issues
```bash
# Check database is running
docker ps | grep chronarr-db

# Check database logs
docker logs chronarr-db

# Test connection from core container
docker exec -it chronarr-core psql -h chronarr-db -U chronarr -d chronarr
```

### Radarr/Sonarr Integration Issues
```bash
# Check core container logs
docker logs chronarr-core

# Verify API connectivity
docker exec -it chronarr-core curl http://radarr:7878/api/v3/system/status?apikey=YOUR_KEY

# Check database access (if enabled)
docker exec -it chronarr-core psql -h radarr-db -U radarr -d radarr-main
```

### Missing Dates
- Check **Dashboard** → **Skipped Items** section
- Review **Source** column in the Movies or TV Shows sections
- Use **Debug** button to inspect raw database data
- Verify Radarr/Sonarr have import history data

### Performance Issues
- Enable direct database access for Radarr/Sonarr (much faster than API)
- Increase database connection pool size
- Use pagination in web interface for large libraries

## Development

### Project Structure
```
chronarr/
├── api/                    # Core API route handlers
├── clients/                # Radarr/Sonarr API clients
├── config/                 # Configuration management
├── core/                   # Core database and logic
├── chronarr-web/           # Web interface container
│   ├── static/             # HTML, CSS, JavaScript (served by web container)
│   └── api/                # Web-specific API routes (web_routes.py)
├── static/                 # Shared static assets
├── processors/             # Webhook processors
├── utils/                  # Utility functions
└── docker-compose.yml.example  # Docker Compose configuration template
```

### Building from Source
```bash
# Clone repository
git clone https://github.com/sbcrumb/chronarr.git
cd chronarr

# Build Docker image
docker build -t chronarr:dev .

# Run with the example compose file
cp docker-compose.yml.example docker-compose.yml
docker-compose up -d
```

## FAQ

**Q: Does Chronarr modify my Radarr/Sonarr databases?**
A: No. Chronarr only reads from Radarr/Sonarr databases (if direct access is enabled). All data is stored in its own dedicated PostgreSQL database.

**Q: What happens if I delete a movie from Radarr?**
A: The movie will remain in Chronarr's database. You can manually delete it from Chronarr's web interface if desired.

**Q: Can I use this without direct database access?**
A: **Radarr requires direct database access** (PostgreSQL or SQLite) - the Radarr API doesn't expose all the import history data needed for accurate date tracking. **Sonarr can work with API-only access**, though direct database access provides better performance.

**Q: Does this work with SQLite Radarr/Sonarr databases?**
A: Yes, Chronarr can read from both SQLite and PostgreSQL databases for both Radarr and Sonarr. **Important for Docker users**: You must mount the directory containing the SQLite database file(s) as a read-only volume in your `docker-compose.yml`. See the Quick Start guide for configuration details.

## Privacy Policy

Chronarr's core application does not collect personal data. It reads only from your local Radarr and Sonarr databases and stores date information in your own PostgreSQL instance.

The **Emby and Jellyfin plugins** collect the following information during license registration:

- **Name** — used to identify your license
- **Email address** — used to deliver your license key and send license status notifications
- **Server name** — used to associate a license with a specific media server installation

This data is transmitted to the Chronarr license server and is used solely for license management. It is never sold, shared with third parties, or used for any purpose other than validating and managing your license.

To request removal of your data, open an issue at [github.com/sbcrumb/chronarr/issues](https://github.com/sbcrumb/chronarr/issues).

## Contributing

Contributions welcome! Please:
1. Fork the repository
2. Create a feature branch
3. Submit a pull request with clear description

## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Support

- **GitHub Issues**: [https://github.com/sbcrumb/chronarr/issues](https://github.com/sbcrumb/chronarr/issues)

## Upgrading from v2 to v3

v3 is a drop-in upgrade for single-instance setups. Pull the new image and restart — no config changes are required.

**What you'll notice immediately:**
- The horizontal tab bar is replaced by a collapsible sidebar. Dashboard, Movies, TV Shows, Reports, and Tools are all still there.
- The "Admin" tab is now **Tools** in the sidebar.

**Webhooks:** The old `/webhook/radarr` and `/webhook/sonarr` URLs still work — they're kept as aliases. The new canonical format is `/radarr/webhook` and `/sonarr/webhook`, and you can update your Radarr/Sonarr connections at any time, but there's no urgency.

**Database:** Schema migrations run automatically on startup. Existing movie and episode records are preserved and tagged with the default instance name (`radarr` / `sonarr`).

**Multi-instance (optional):** If you run a second Radarr (e.g., 4K) or second Sonarr, see the [Multi-Instance Configuration](#multi-instance-configuration-v30) block in the Configuration section. Each extra instance just needs a `RADARR_{NAME}_URL` block in your `.env` and its own webhook connection in Radarr/Sonarr.

---

## Changelog

### v3.0.0
- 🏠 **Sidebar navigation** - Replaced horizontal tab bar with a collapsible dark sidebar; instance sub-items expand under Movies and TV Shows
- 🔀 **Multi-instance support** - Configure multiple Radarr and/or Sonarr instances; each is tracked separately and shown with colored badges in the UI
- 🏷️ **Instance badges** - Every row in the Movies and TV tables shows a colored badge identifying its instance; badge colors are consistent between the sidebar and the table
- 🚀 **Cold-start populate fix** - Database population on startup now iterates all configured instances, not just the first
- 🗑️ **Delete series** - Remove an entire TV series and all its episode records from the database in one click
- 🔧 **Instance-aware edit** - Date edits, smart fixes, and skipped-item updates are now scoped to the correct instance
- 🧹 **Series title cleanup** - Series titles derived from folder paths no longer include media-manager ID suffixes (e.g., `[imdb-tt1234567]`)

### v2.0.0 (2025-11-05)
- 🎉 **Initial release** - Comprehensive date and chronology management for Radarr and Sonarr
- 🎯 **Smart date tracking** - Multiple sources with intelligent fallback hierarchy
- 🗄️ **Database-first** - PostgreSQL backend with full ACID compliance
- 🌐 **Web interface** - Complete movie and TV show management
- 🔗 **Radarr/Sonarr integration** - API and direct database access support (PostgreSQL and SQLite)
- 📊 **Dashboard** - Real-time statistics and monitoring
- 🔧 **IMDb ID migration** - Update placeholder IDs for manual entries
- 📈 **Processing history** - Full audit trail of all operations
- ⚡ **Performance** - Async operations and connection pooling
- 🐳 **Docker** - 3-container architecture with health checks
- ✨ **Auto-configuration** - Config files auto-generated from embedded examples on first run
