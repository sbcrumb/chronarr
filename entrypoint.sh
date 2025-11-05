#!/bin/bash
set -e

# Chronarr Entrypoint Script
# 1. Auto-generates config files if they don't exist
# 2. Deploys Emby plugin if directory is mounted
# 3. Starts the application

CONFIG_DIR="/config"
ENV_FILE="${CONFIG_DIR}/.env"
SECRETS_FILE="${CONFIG_DIR}/.env.secrets"

# ========================================
# Configuration File Auto-Generation
# ========================================
echo "🔧 Chronarr Configuration Check..."

# Ensure config directory exists
mkdir -p "${CONFIG_DIR}"

# Copy .env.example to .env if it doesn't exist
if [ ! -f "${ENV_FILE}" ]; then
    echo "📝 .env not found, creating from .env.example..."
    cp /app/.env.example "${ENV_FILE}"
    echo "✅ Created ${ENV_FILE}"
    echo "⚠️  Please edit ${ENV_FILE} to configure your setup"
else
    echo "✅ Found existing ${ENV_FILE}"
fi

# Copy .env.secrets.example to .env.secrets if it doesn't exist
if [ ! -f "${SECRETS_FILE}" ]; then
    echo "📝 .env.secrets not found, creating from .env.secrets.example..."
    cp /app/.env.secrets.example "${SECRETS_FILE}"
    echo "✅ Created ${SECRETS_FILE}"
    echo "⚠️  Please edit ${SECRETS_FILE} to add your API keys and passwords"
else
    echo "✅ Found existing ${SECRETS_FILE}"
fi

# Symlink config files to /app so application can find them
ln -sf "${ENV_FILE}" /app/.env
ln -sf "${SECRETS_FILE}" /app/.env.secrets

# ========================================
# Emby Plugin Deployment (Optional)
# ========================================
if [ -d "/emby-plugins" ]; then
    echo "🎬 Deploying Chronarr Emby Plugin to mounted directory: /emby-plugins"
    cp /app/emby-plugin/Chronarr.Emby.Plugin.dll /emby-plugins/
    echo "✅ Plugin deployed successfully!"
elif [ -n "$EMBY_PLUGINS_PATH" ] && [ -d "$EMBY_PLUGINS_PATH" ]; then
    echo "🎬 Deploying Chronarr Emby Plugin to: $EMBY_PLUGINS_PATH"
    cp /app/emby-plugin/Chronarr.Emby.Plugin.dll "$EMBY_PLUGINS_PATH/"
    echo "✅ Plugin deployed successfully!"
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
