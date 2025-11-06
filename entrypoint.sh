#!/bin/bash
set -e

# Chronarr Entrypoint Script
# 1. Auto-generates config files if they don't exist
# 2. Deploys Emby plugin if directory is mounted
# 3. Starts the application

CONFIG_DIR="/config"

# ========================================
# Configuration File Auto-Generation
# ========================================
echo "🔧 Chronarr Configuration Check..."

# Try to use /config if it's writable, otherwise fall back to /app
if [ -d "${CONFIG_DIR}" ] && [ -w "${CONFIG_DIR}" ]; then
    echo "✅ Using /config directory for configuration files"
    ENV_FILE="${CONFIG_DIR}/.env"
    SECRETS_FILE="${CONFIG_DIR}/.env.secrets"
elif mkdir -p "${CONFIG_DIR}" 2>/dev/null; then
    echo "✅ Created /config directory for configuration files"
    ENV_FILE="${CONFIG_DIR}/.env"
    SECRETS_FILE="${CONFIG_DIR}/.env.secrets"
else
    echo "⚠️  /config directory not accessible, using /app for configuration files"
    echo "   To persist config across container restarts, mount a volume at /config"
    ENV_FILE="/app/.env"
    SECRETS_FILE="/app/.env.secrets"
fi

# Copy .env.example to .env if it doesn't exist
if [ ! -f "${ENV_FILE}" ]; then
    echo "📝 .env not found, creating from .env.example..."
    if [ -f /app/.env.example ]; then
        cp /app/.env.example "${ENV_FILE}"
        echo "✅ Created ${ENV_FILE}"
        echo "⚠️  Please edit ${ENV_FILE} to configure your setup"
    else
        echo "❌ ERROR: /app/.env.example not found, cannot create ${ENV_FILE}"
        echo "   You must manually create ${ENV_FILE}"
    fi
else
    echo "✅ Found existing ${ENV_FILE}"
fi

# Copy .env.secrets.example to .env.secrets if it doesn't exist
if [ ! -f "${SECRETS_FILE}" ]; then
    echo "📝 .env.secrets not found, creating from .env.secrets.example..."
    if [ -f /app/.env.secrets.example ]; then
        cp /app/.env.secrets.example "${SECRETS_FILE}"
        echo "✅ Created ${SECRETS_FILE}"
        echo "⚠️  Please edit ${SECRETS_FILE} to add your API keys and passwords"
    else
        echo "❌ ERROR: /app/.env.secrets.example not found, cannot create ${SECRETS_FILE}"
        echo "   You must manually create ${SECRETS_FILE}"
    fi
else
    echo "✅ Found existing ${SECRETS_FILE}"
fi

# Symlink config files to /app if using /config directory
if [ "${ENV_FILE}" != "/app/.env" ]; then
    ln -sf "${ENV_FILE}" /app/.env
    ln -sf "${SECRETS_FILE}" /app/.env.secrets
fi

# ========================================
# Emby Plugin Deployment (Optional)
# ========================================
if [ -d "/emby-plugins" ]; then
    echo "🎬 Deploying Chronarr Emby Plugin to mounted directory: /emby-plugins"
    if [ -f /app/emby-plugin/Chronarr.Emby.Plugin.dll ]; then
        cp /app/emby-plugin/Chronarr.Emby.Plugin.dll /emby-plugins/
        echo "✅ Plugin deployed successfully!"
    else
        echo "⚠️  Emby plugin DLL not found at /app/emby-plugin/Chronarr.Emby.Plugin.dll"
        echo "   Skipping plugin deployment"
    fi
elif [ -n "$EMBY_PLUGINS_PATH" ] && [ -d "$EMBY_PLUGINS_PATH" ]; then
    echo "🎬 Deploying Chronarr Emby Plugin to: $EMBY_PLUGINS_PATH"
    if [ -f /app/emby-plugin/Chronarr.Emby.Plugin.dll ]; then
        cp /app/emby-plugin/Chronarr.Emby.Plugin.dll "$EMBY_PLUGINS_PATH/"
        echo "✅ Plugin deployed successfully!"
    else
        echo "⚠️  Emby plugin DLL not found at /app/emby-plugin/Chronarr.Emby.Plugin.dll"
        echo "   Skipping plugin deployment"
    fi
else
    echo "ℹ️  No Emby plugins directory found - skipping plugin deployment"
    echo "   To enable plugin deployment, bind mount your Emby plugins directory to /emby-plugins"
fi

# ========================================
# Start Application
# ========================================
echo "🚀 Starting Chronarr..."

# Execute the command passed to the entrypoint (defaults to main.py or start_web.py)
exec "$@"
