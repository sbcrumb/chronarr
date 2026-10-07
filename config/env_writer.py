"""
Env file writer for the setup wizard.

Everything the wizard adds goes through here — turning a form submission
into env var names, and writing those into .env / .env.secrets a few keys
at a time without disturbing anything else already in either file. Nothing
in this module talks to the network or a database; it's just the
file-writing half of "add an instance". The actual connection testing and
name-collision checks against the live registry happen in the route
handler, before build_env_updates()/upsert_env_file() are ever called —
by the time we're writing, everything should already be validated.
"""
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple


# Env var suffixes that are secrets and always belong in .env.secrets,
# never .env. Keep this in sync with what _load_radarr_instance /
# _load_sonarr_instance in config/settings.py actually read — if a new
# secret-shaped field gets added there, it needs to be added here too.
SECRET_SUFFIXES = ("API_KEY", "DB_PASSWORD")

# Same reserved segments settings.py already refuses to treat as instance
# names (RADARR_DB_* and RADARR_WEBHOOK_* aren't instances called "DB" or
# "WEBHOOK"). Duplicated here rather than imported so this module has no
# dependency on settings.py loading environment variables at import time.
RESERVED_NAME_SEGMENTS = {"DB", "WEBHOOK"}

# Letters, digits, underscores only — no hyphens. This becomes part of an
# env var name and a URL path segment (the webhook route), so it has to be
# shell- and URL-safe. Same rule the multi-instance docs already spell out
# for people naming instances by hand.
_NAME_SEGMENT_RE = re.compile(r"^[A-Za-z0-9_]+$")


class InstanceNameError(ValueError):
    """A user-supplied instance name isn't safe to use as an env var segment."""


def validate_name_segment(raw_name: str, existing_names: set, media_type: str, require_exists: bool = False) -> str:
    """Turn a user-typed instance name into a validated env var name segment.

    Uppercases it (env vars are conventionally upper-case), then checks the
    character set, the reserved-word list, and whether it collides with an
    instance that's already running.

    existing_names should come from the live InstanceRegistry, not just
    whatever's currently in .env — someone may have hand-edited the file
    since the last restart, and the registry is what's actually in use.
    Those are full instance names (e.g. "sonarr_strm"), not bare segments
    (e.g. "strm") — media_type is what lets this function build the same
    full name to compare against, the way instance_name is built everywhere
    else in the wizard (f"{media_type}_{segment.lower()}").

    require_exists flips the collision check: normally a name must NOT
    already exist (adding a new instance is the default assumption); with
    require_exists=True it must ALREADY exist instead — used when editing
    or deleting a specific instance, where the opposite mistake (a typo'd
    name matching nothing) is the one worth catching.
    """
    name_segment = raw_name.strip().upper()

    if not name_segment:
        raise InstanceNameError("Instance name can't be empty")

    if not _NAME_SEGMENT_RE.match(name_segment):
        raise InstanceNameError(
            "Instance name can only contain letters, numbers, and underscores — "
            "no hyphens or spaces. This becomes part of an env var name and a "
            "webhook URL, so it has to stay simple."
        )

    if name_segment in RESERVED_NAME_SEGMENTS:
        raise InstanceNameError(f"'{name_segment}' is a reserved word and can't be used as an instance name")

    full_name = f"{media_type}_{name_segment.lower()}"
    exists = full_name in existing_names
    if require_exists and not exists:
        raise InstanceNameError(f"No instance named '{full_name}' exists to edit or delete")
    if not require_exists and exists:
        raise InstanceNameError(f"An instance named '{full_name}' already exists")

    return name_segment


def build_env_updates(
    media_type: str, name_segment: str, fields: Dict[str, object]
) -> Tuple[Dict[str, str], Dict[str, str]]:
    """Turn a wizard form submission into the env vars it becomes.

    media_type is "radarr" or "sonarr". fields is whatever the form
    collected — only the known field names below are ever read, so a stray
    key in the request body can't sneak an arbitrary env var into either
    file. name_segment == "" means the default instance (RADARR_URL rather
    than RADARR_4K_URL).

    Returns (env_updates, secret_updates), two plain {KEY: value} dicts
    ready to hand to upsert_env_file() — one per file.
    """
    prefix = f"{media_type.upper()}_{name_segment}_" if name_segment else f"{media_type.upper()}_"

    # Radarr and Sonarr each only have one of these — asking for both would
    # be a caller bug, not something worth silently tolerating.
    path_field = "movie_paths" if media_type == "radarr" else "tv_paths"
    path_var = "MOVIE_PATHS" if media_type == "radarr" else "TV_PATHS"

    field_to_suffix = {
        "url": "URL",
        "api_key": "API_KEY",
        "root_folders": "ROOT_FOLDERS",
        path_field: path_var,
        "db_type": "DB_TYPE",
        "db_host": "DB_HOST",
        "db_port": "DB_PORT",
        "db_name": "DB_NAME",
        "db_user": "DB_USER",
        "db_password": "DB_PASSWORD",
        "db_path": "DB_PATH",
    }

    env_updates: Dict[str, str] = {}
    secret_updates: Dict[str, str] = {}

    for field_name, suffix in field_to_suffix.items():
        value = fields.get(field_name)
        if value in (None, ""):
            continue
        if isinstance(value, list):
            value = ",".join(str(v).strip() for v in value if str(v).strip())
            if not value:
                continue
        key = f"{prefix}{suffix}"
        target = secret_updates if suffix in SECRET_SUFFIXES else env_updates
        target[key] = str(value)

    return env_updates, secret_updates


def upsert_env_file(path: Path, updates: Dict[str, str], instance_label: str = "") -> bool:
    """Write `updates` into the env file at `path`, touching only those keys.

    An existing KEY=value line gets its value replaced in place — every
    comment, blank line, and unrelated var is left exactly as it was. Keys
    that don't already exist are appended at the end under a small header
    comment, so it's obvious later which lines the wizard added versus
    what was hand-written.

    Returns True if the file was created or changed, False if every
    requested value already matched what was on disk.
    """
    if not updates:
        return False

    remaining = dict(updates)  # don't mutate the caller's dict as we consume it
    lines: List[str] = path.read_text().splitlines() if path.exists() else []
    changed = False

    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in line:
            continue
        key = line.split("=", 1)[0].strip()
        if key in remaining:
            new_line = f"{key}={remaining.pop(key)}"
            if new_line != line:
                lines[i] = new_line
                changed = True

    # Anything still left in `remaining` wasn't in the file at all — append it.
    if remaining:
        if lines and lines[-1].strip():
            lines.append("")
        if instance_label:
            lines.append(f"# --- {instance_label} (added via setup wizard) ---")
        for key, value in remaining.items():
            lines.append(f"{key}={value}")
        changed = True

    if changed:
        path.write_text("\n".join(lines) + "\n")

    return changed


def remove_instance_keys(path: Path, prefix: str, instance_label: str = "") -> bool:
    """Remove every KEY=value line whose key starts with `prefix` from the file.

    This is the delete half of the wizard — the mirror of upsert_env_file().
    `prefix` is the same "SONARR_STRM_" shape build_env_updates() already
    builds keys with, so a delete removes exactly what an add would have
    written, no more. Also drops the wizard's own "# --- name (added via
    setup wizard) ---" header line for this instance if present — anything
    else in the file, including other comments, is left untouched.

    Returns True if anything was actually removed, False if the file had
    nothing matching (deleting an instance that was never in this file, or
    was hand-written under a different naming convention).
    """
    if not path.exists():
        return False

    lines = path.read_text().splitlines()
    kept: List[str] = []
    changed = False
    header_marker = f"# --- {instance_label} (" if instance_label else None

    for line in lines:
        stripped = line.strip()
        if header_marker and stripped.startswith(header_marker):
            changed = True
            continue
        if stripped and not stripped.startswith("#") and "=" in line:
            key = line.split("=", 1)[0].strip()
            if key.startswith(prefix):
                changed = True
                continue
        kept.append(line)

    if changed:
        path.write_text("\n".join(kept) + ("\n" if kept else ""))

    return changed


def read_env_files(env_path: Path, secrets_path: Path) -> Dict[str, str]:
    """Read both files' raw text, for a backup. A missing file comes back as "".

    Deliberately just the raw text, not parsed key/value pairs — a backup
    should round-trip exactly, comments and formatting included, not just
    the values.
    """
    return {
        "env": env_path.read_text() if env_path.exists() else "",
        "env_secrets": secrets_path.read_text() if secrets_path.exists() else "",
    }


def write_env_files(env_path: Path, secrets_path: Path, env_content: str, secrets_content: str) -> None:
    """Overwrite both files verbatim — this is what restoring a backup does.

    Unlike upsert_env_file(), nothing is merged here: whatever text is
    passed in becomes the entire file. Call backup_env_files() first if
    the current content is worth keeping, which the wizard's restore
    endpoint always does.
    """
    env_path.write_text(env_content)
    secrets_path.write_text(secrets_content)


def backup_env_files(env_path: Path, secrets_path: Path, backups_dir: Path) -> Optional[Path]:
    """Snapshot both files' current content into backups_dir, before something overwrites them.

    Same JSON shape a manual backup download uses, so a snapshot taken here
    can be fed straight back into a restore if needed. Returns the path to
    the snapshot, or None if neither file exists yet — nothing to back up
    on a fresh install.
    """
    if not env_path.exists() and not secrets_path.exists():
        return None

    backups_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    snapshot_path = backups_dir / f"env-backup-{timestamp}.json"

    # Two snapshots requested in the same second would collide — add a
    # counter suffix rather than silently overwriting an earlier one.
    counter = 1
    while snapshot_path.exists():
        snapshot_path = backups_dir / f"env-backup-{timestamp}-{counter}.json"
        counter += 1

    snapshot = {"exported_at": datetime.now(timezone.utc).isoformat(), **read_env_files(env_path, secrets_path)}
    snapshot_path.write_text(json.dumps(snapshot, indent=2))

    return snapshot_path
