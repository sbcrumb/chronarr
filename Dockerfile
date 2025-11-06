FROM python:3.12.12-slim
# Updates for local builds

# Build argument for git branch and build source
ARG GIT_BRANCH=main
ARG BUILD_SOURCE=

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=utf-8 \
    GIT_BRANCH=${GIT_BRANCH} \
    BUILD_SOURCE=${BUILD_SOURCE}

# Install system dependencies including PostgreSQL client libraries and tini
# Try to upgrade tar to fix CVE-2025-45582 (may not be available in stable)
RUN apt-get update && apt-get install -y \
    curl \
    libpq-dev \
    gcc \
    tini \
    && apt-get upgrade -y tar || true \
    && rm -rf /var/lib/apt/lists/*

# Create app user and directory
RUN useradd --create-home --shell /bin/bash app
WORKDIR /app

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Copy web starter file to root directory
COPY start_web.py .

# Create git metadata for version detection based on build arg
RUN mkdir -p .git && \
    echo "ref: refs/heads/${GIT_BRANCH}" > .git/HEAD

# Copy DLL to a dedicated directory (if it exists)
RUN mkdir -p /app/emby-plugin && \
    if [ -f /app/Emby-DLL/Chronarr.Emby.Plugin.dll ]; then \
        cp /app/Emby-DLL/Chronarr.Emby.Plugin.dll /app/emby-plugin/; \
        echo "✅ Emby plugin DLL copied successfully"; \
    else \
        echo "⚠️  Emby plugin DLL not found, skipping..."; \
    fi

# Copy and setup entrypoint script
COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

# Create data directory for logs and ensure proper permissions
RUN mkdir -p /app/data/logs && \
    chown -R app:app /app

# Switch to app user
USER app

# Declare volume mount point
VOLUME ["/app/data"]

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8080/health || exit 1

# Expose port
EXPOSE 8080

# Use tini as init process to handle signals and zombie processes properly
ENTRYPOINT ["tini", "--", "/app/entrypoint.sh"]

# Default command (can be overridden in docker-compose for chronarr-web)
CMD ["python", "-u", "main.py"]