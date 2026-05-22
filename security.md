# Security Review — Chronarr (Main App)

Local only — gitignored. Last updated: 2026-05-22

---

## Fixed Issues

| Severity | Issue | Fixed In |
|----------|-------|----------|
| CRITICAL | Arbitrary SQL execution endpoint `/api/admin/database/query` | v2.0.12 |
| CRITICAL | PostgreSQL port exposed to host in docker-compose | Merged ✅ |
| HIGH | Auth middleware allowed admin/debug/manual routes publicly | v2.0.10 |
| HIGH | Timing-safe password comparison missing | v2.0.10 |
| HIGH | Path traversal in `/manual/scan` | v2.0.12 |
| HIGH | `/tmp` status file deserialized and returned to clients | v2.0.12 |
| MEDIUM | Session expiry used `.seconds` instead of `.total_seconds()` | v2.0.10 |
| MEDIUM | Session cookie `secure=False` hardcoded | v2.0.10 |
| MEDIUM | Login rate limiting missing | v2.0.12 |
| MEDIUM | DEBUG print statements in production | v2.0.12 |
| MEDIUM | Duplicate `get_version()` in main.py | v2.0.12 |
| LOW | PID in populate-database API response | v2.0.12 |
| LOW | Webhook signature verification missing | v2.0.12 |
| HIGH | No `.dockerignore` — `.env` could bake into image layers | feature/security-dockerignore-version-pins |
| HIGH | Loose `>=` pins on FastAPI and Starlette | feature/security-dockerignore-version-pins |

---

## Still Open

### MEDIUM — Debug endpoints on core (port 8080) — no auth
**File:** `api/routes.py:3000-3150`
**Effort:** Small | **Breaking:** No

Routes `/debug/movie/{imdb_id}`, `/debug/movie/{imdb_id}/history`, `/debug/movie/{imdb_id}/priority` are registered on the core container (port 8080) which has zero auth middleware. They return full database records, internal paths, and processing history to any caller.

**Fix:**
```python
# In api/routes.py — wrap all /debug/ route registrations:
if os.environ.get("DEBUG_ENABLED", "false").lower() == "true":
    @app.get("/debug/movie/{imdb_id}")
    async def _debug_movie_import_date(imdb_id: str):
        return await debug_movie_import_date(imdb_id, dependencies)
    # ... rest of debug routes
```
Or simply delete the debug route registrations (lines 3000-3150).

---

### MEDIUM — `/api/debug/movie/{imdb_id}/raw` raw DB dump
**File:** `api/web_routes.py:1517`
**Effort:** Small | **Breaking:** No

Returns all raw database fields for a movie. Protected by auth when enabled but raw dump endpoints should not exist in production.

**Fix — delete the route (lines 1517-1537):**
```python
# DELETE these lines entirely:
@app.get("/api/debug/movie/{imdb_id}/raw")
async def api_debug_movie_raw(imdb_id: str):
    ...
```

---

### HIGH — GitHub Actions floating version tags
**Files:** `.github/workflows/ghcr-dev.yml` · `.github/workflows/ghcr-main.yml`
**Effort:** Medium | **Breaking:** No

All actions use floating tags (`@v3`, `@v5`, `@v7`). A compromised action maintainer can push malicious code that runs in your builds.

**Fix — pin every action to its commit SHA:**
```yaml
# ghcr-dev.yml and ghcr-main.yml — replace all @vN with SHA:
uses: actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683        # v4.2.2
uses: docker/setup-qemu-action@49ce6c3417387779bbf8ac56f46e7f6e04c64acf   # v3.6.0
uses: docker/setup-buildx-action@c47758c2199f1ec8c7f6a01e0aeef31929577033 # v3.9.0
uses: docker/login-action@9780b0c442fbb1117ed29e0efdff1e18412f7567      # v3.3.0
uses: docker/build-push-action@ca052bb54ab0790a636c9b5f226502c73d547a25  # v6.13.0
uses: actions/github-script@60a0d83039c74a4aee543508d2ffcb1c3799cdea    # v7.0.1
uses: release-drafter/release-drafter@3f0f87098bd6b5c5b9a36d49c0a6640cd5f2fcee # v6
```
Also add `.github/dependabot.yml` with `package-ecosystem: github-actions` to keep SHAs updated.

---


### HIGH — Build tools left in runtime image
**File:** `Dockerfile:17-23`
**Effort:** Large | **Breaking:** No

`gcc` and `libpq-dev` (development headers) remain in the runtime image, increasing attack surface by ~120MB.

**Fix — multi-stage build:**
```dockerfile
FROM python:3.12.12-slim AS builder
RUN apt-get update && apt-get install -y gcc libpq-dev && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

FROM python:3.12.12-slim
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
RUN apt-get update && apt-get install -y libpq5 curl tini && rm -rf /var/lib/apt/lists/*
```

---

### MEDIUM — `psycopg2-binary` in production
**File:** `requirements.txt:4`
**Effort:** Small (with multi-stage fix above) | **Breaking:** No

```
# CHANGE:
psycopg2-binary==2.9.11
# TO:
psycopg2==2.9.11
```
Requires `libpq-dev` at build time (provided by builder stage) and `libpq5` at runtime.

---

### MEDIUM — No resource limits in docker-compose
**File:** `docker-compose.yml.example`
**Effort:** Small | **Breaking:** No

Add to each service:
```yaml
    deploy:
      resources:
        limits:
          memory: 2G    # adjust per service
          cpus: '2'
```

---

### LOW — Weak password example in documentation
**File:** `docker-compose.yml.example:6`

```yaml
# CHANGE:
echo "DB_PASSWORD=change_me_please" > .env
# TO:
echo "DB_PASSWORD=$(openssl rand -base64 32)" > .env
```

---

### LOW — Fake `.git` directory in container
**File:** `Dockerfile:41-42`

```dockerfile
# CHANGE:
RUN mkdir -p .git && echo "ref: refs/heads/${GIT_BRANCH}" > .git/HEAD
# TO:
RUN echo "${GIT_BRANCH}" > /app/BUILD_BRANCH
```
Update `version_utils.py` to read `BUILD_BRANCH` file instead of `.git/HEAD`.

---

## Dependency Status

| Component | Version | Status |
|-----------|---------|--------|
| `python:3.12.12-slim` | 3.12.12 | ✅ Pinned |
| `fastapi` | ==0.120.0 | ✅ Pinned |
| `starlette` | ==0.49.1 | ✅ Pinned |
| `psycopg2-binary` | 2.9.11 | ⚠️ Switch to `psycopg2` |
| `uvicorn` | 0.38.0 | ✅ |
| `pydantic` | 2.12.4 | ✅ |
| `requests` | 2.32.5 | ✅ |
| `aiohttp` | 3.13.2 | ✅ |
| `APScheduler` | 3.11.0 | ✅ |
| GitHub Actions | @v3/@v5 | ⚠️ Pin to SHA |
