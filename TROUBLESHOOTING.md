# Chronarr Troubleshooting

## Symlinked / Debrid Libraries (decypharr, rclone, strm-backed mounts, etc.)

If your library uses symlinks into a FUSE/debrid-backed mount (decypharr's DFS, rclone, similar tools), and episodes/movies intermittently fail to get a date with errors like `Transport endpoint is not connected` (`ENOTCONN`) in the core container's logs even though the file plays fine in Emby/Jellyfin/Plex — this is almost always a **Docker mount propagation** issue, not a Chronarr bug.

**Why it happens:** the FUSE mount (e.g. `/mnt/decypharr`) gets bind-mounted into the `chronarr-core` container at container start. If the underlying mount is ever remounted on the host afterward (the debrid tool's own container restarting, its cache cycling, etc.), Docker doesn't automatically propagate that into containers unless the mount is explicitly configured with **shared propagation**. Without it, Chronarr's container keeps holding a stale, dead handle to the *old* mount — even though the host itself, and anything that mounted fresh, sees the real file just fine. Restarting `chronarr-core` "fixes" it temporarily because that gives the container a fresh bind-mount — but it comes back the next time the underlying mount cycles.

**Fix — set up shared mount propagation so a remount propagates automatically, no restart needed:**

1. In `docker-compose.yml`, add `rslave` propagation to the relevant volume under `chronarr-core`:
   ```yaml
   volumes:
     - /mnt/decypharr:/mnt/decypharr:rslave
   ```
2. On the host, mark that mountpoint as shared (this is what `rslave` listens for):
   ```bash
   sudo mount --make-rshared /mnt/decypharr
   ```
3. This does **not** persist across the debrid tool's container restarting (or a host reboot) on its own — it needs to be reapplied every time the underlying mount gets recreated. The simplest robust fix is a self-healing cron entry (run as root):
   ```bash
   * * * * * findmnt -o PROPAGATION /mnt/decypharr --noheadings 2>/dev/null | grep -q shared || mount --make-rshared /mnt/decypharr
   ```

Restart `chronarr-core` once after adding the compose change for it to take effect.
