# Chronarr Setup Guide

## 🔐 Secure Configuration Setup

Chronarr now uses a **two-file configuration system** for better security and easier troubleshooting:

- **`.env`** - Main configuration (safe to share for debugging)
- **`.env.secrets`** - Sensitive API keys and passwords (never commit to git)

### Step 1: Copy Configuration Templates

```bash
# Copy main configuration
cp .env.template .env

# Copy secrets configuration  
cp .env.secrets.template .env.secrets
```

### Step 2: Configure Main Settings

Edit your `.env` file with your specific paths and preferences:

```bash
# Media paths (adjust to your directory structure)
TV_PATHS=/media/TV/tv,/media/TV/tv6
MOVIE_PATHS=/media/Movies/movies,/media/Movies/movies6

# Database connection details
RADARR_DB_HOST=radarr-postgres
RADARR_DB_PORT=5432
RADARR_DB_NAME=radarr
RADARR_DB_USER=radarr

# Processing preferences
PREFER_RELEASE_DATES_OVER_FILE_DATES=true
ALLOW_FILE_DATE_FALLBACK=false
RELEASE_DATE_PRIORITY=digital,physical,theatrical

# TV webhook processing mode (v0.6.0+)
TV_WEBHOOK_PROCESSING_MODE=targeted
```

### Step 3: Configure Secrets

Edit your `.env.secrets` file with your actual API keys and passwords:

```bash
# Database password
RADARR_DB_PASSWORD=your_actual_radarr_password

# TMDB API key (required for release date detection)
TMDB_API_KEY=your_actual_tmdb_api_key

# Sonarr API key (REQUIRED for v0.6.0+ Enhanced TV NFO Generation)
SONARR_API_KEY=your_actual_sonarr_api_key

# Optional API keys
RADARR_API_KEY=your_radarr_api_key
OMDB_API_KEY=your_omdb_api_key
```

### Step 4: Verify Configuration

Test your setup:

```bash
# Test database connections
curl -X POST "http://localhost:8080/test/bulk-update"

# Test movie scanning
curl -X POST "http://localhost:8080/test/movie-scan"

# Check system health
curl "http://localhost:8080/health"
```

## 🔒 Security Features

### API Key Masking
All API keys and passwords are automatically masked in logs:
```
[2025-09-09T12:34:56] INFO: TMDB API call with key=***masked***
[2025-09-09T12:34:56] INFO: Database connection password=***masked***
```

### Sensitive Data Separation
- **Main `.env`**: Paths, preferences, URLs (safe to share)
- **`.env.secrets`**: API keys, passwords (never commit to version control)
- **Automatic loading**: Both files loaded automatically at startup

### Git Protection
The `.gitignore` file prevents accidental commits:
```
.env
.env.secrets
.env.local
```

## 🛠 Troubleshooting

### "Environment files not loaded" Warning
Install python-dotenv:
```bash
pip install python-dotenv==1.0.0
# or
docker-compose build  # rebuilds with updated requirements.txt
```

### Sharing Configuration for Help
You can safely share your `.env` file for debugging since it contains no sensitive data. The `.env.secrets` file should never be shared.

### Migration from Old Setup
If you have an existing `.env` with API keys:
1. Move all `*_API_KEY` and `*_PASSWORD` variables to `.env.secrets`
2. Remove sensitive data from `.env` 
3. Restart Chronarr

## 🎯 Docker Compose Example

```yaml
version: '3.8'
services:
  chronarr:
    image: sbcrumb/chronarr:latest
    container_name: chronarr
    ports:
      - "8080:8080"
    volumes:
      - /path/to/your/media:/media:rw
      - ./data:/app/data
      - ./.env:/app/.env:ro          # Main configuration
      - ./.env.secrets:/app/.env.secrets:ro  # Secrets
    environment:
      - CORE_API_PORT=8080
    depends_on:
      - radarr-postgres
```

## 📋 Configuration Reference

### Main Configuration (.env)
- **Paths**: `TV_PATHS`, `MOVIE_PATHS`, `DB_PATH`
- **Processing**: `MOVIE_PRIORITY`, `RELEASE_DATE_PRIORITY`
- **Features**: `MANAGE_NFO`, `FIX_DIR_MTIMES`, `LOCK_METADATA`
- **URLs**: `RADARR_URL`, `SONARR_URL`, `JELLYSEERR_URL`

### Secrets Configuration (.env.secrets)  
- **Database**: `RADARR_DB_PASSWORD`
- **APIs**: `TMDB_API_KEY`, `OMDB_API_KEY`, `RADARR_API_KEY`, `SONARR_API_KEY`
- **Optional**: `JELLYSEERR_API_KEY`

This setup makes Chronarr more secure while keeping configuration manageable for troubleshooting and deployment.