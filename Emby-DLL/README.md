# Chronarr Emby Plugin

The Chronarr Emby plugin syncs accurate import dates from the Chronarr database back to your Emby library, so your media sorts by when you actually added it — not when Emby last scanned the file.

## Auto-Deploy (Recommended)

Chronarr ships the plugin DLL inside the Docker image and deploys it automatically on startup. Mount your Emby plugins directory in `docker-compose.yml`:

```yaml
volumes:
  - /path/to/emby/plugins:/emby-plugins
```

Or set `EMBY_PLUGINS_PATH` in your `.env` to the Emby plugins folder on the host. On startup you'll see:

```
✅ Plugin deployed successfully! (257536 bytes)
```

## Manual Install

If you prefer to install manually, download `Chronarr.Emby.Plugin.dll` from this directory and place it in your Emby plugins folder. Restart Emby.

## Code Signing

This project uses [SignPath Foundation](https://signpath.org) for code signing.

## Changelog

The plugin changelog is visible in the Emby configuration page under **Dashboard → Plugins → Chronarr → Version & Changelog**.
