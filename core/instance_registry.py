"""
Instance registry for Radarr and Sonarr clients.

Builds one client and one PathMapper per configured instance at startup.
Processors and webhook handlers resolve the right client/mapper from here
rather than each constructing their own from env vars.
"""
from typing import Dict, Optional, Union

from clients.radarr_client import RadarrClient
from clients.radarr_db_client import RadarrDbClient
from clients.sonarr_client import SonarrClient
from clients.sonarr_db_client import SonarrDbClient
from config.settings import RadarrInstance, SonarrInstance
from core.logging import _log
from core.path_mapper import PathMapper

# Type aliases
AnyRadarrClient = Union[RadarrClient, RadarrDbClient]
AnySonarrClient = Union[SonarrClient, SonarrDbClient]


def _build_radarr_client(instance: RadarrInstance) -> Optional[AnyRadarrClient]:
    """Return the best available client for a Radarr instance.

    Tries DB client first (faster, no API rate limits). Falls back to API
    client if no DB is configured or the connection fails.
    """
    if instance.db_type:
        try:
            if instance.db_type == "sqlite":
                client = RadarrDbClient(
                    db_type="sqlite",
                    db_path=instance.db_path or None,
                )
            else:
                client = RadarrDbClient(
                    db_type=instance.db_type,
                    db_host=instance.db_host or None,
                    db_port=instance.db_port,
                    db_name=instance.db_name or None,
                    db_user=instance.db_user or None,
                    db_password=instance.db_password or None,
                )
            _log("INFO", f"[{instance.name}] Using Radarr direct database access")
            return client
        except Exception as e:
            _log("WARNING", f"[{instance.name}] Radarr DB connection failed, falling back to API: {e}")

    if instance.url and instance.api_key:
        _log("INFO", f"[{instance.name}] Using Radarr API client")
        return RadarrClient(
            base_url=instance.url,
            api_key=instance.api_key,
        )

    _log("WARNING", f"[{instance.name}] No Radarr client available — no DB or API configured")
    return None


def _build_sonarr_client(instance: SonarrInstance) -> Optional[AnySonarrClient]:
    """Return the best available client for a Sonarr instance."""
    if instance.db_type:
        try:
            if instance.db_type == "sqlite":
                client = SonarrDbClient(
                    db_type="sqlite",
                    db_path=instance.db_path or None,
                )
            else:
                client = SonarrDbClient(
                    db_type=instance.db_type,
                    db_host=instance.db_host or None,
                    db_port=instance.db_port,
                    db_name=instance.db_name or None,
                    db_user=instance.db_user or None,
                    db_password=instance.db_password or None,
                )
            _log("INFO", f"[{instance.name}] Using Sonarr direct database access")
            return client
        except Exception as e:
            _log("WARNING", f"[{instance.name}] Sonarr DB connection failed, falling back to API: {e}")

    if instance.url and instance.api_key:
        _log("INFO", f"[{instance.name}] Using Sonarr API client")
        return SonarrClient(
            base_url=instance.url,
            api_key=instance.api_key,
        )

    _log("WARNING", f"[{instance.name}] No Sonarr client available — no DB or API configured")
    return None


class InstanceRegistry:
    """Central store of all Radarr and Sonarr clients and path mappers, keyed by instance name."""

    def __init__(self, radarr_instances, sonarr_instances):
        self._radarr: Dict[str, AnyRadarrClient] = {}
        self._sonarr: Dict[str, AnySonarrClient] = {}
        self._radarr_mappers: Dict[str, PathMapper] = {}
        self._sonarr_mappers: Dict[str, PathMapper] = {}
        # Connection status keyed by instance name — used by /setup and startup reporting.
        # {"connected": True, "method": "direct_db"|"api"} or {"connected": False}
        self._radarr_status: Dict[str, dict] = {}
        self._sonarr_status: Dict[str, dict] = {}

        for inst in radarr_instances:
            client = _build_radarr_client(inst)
            if client:
                self._radarr[inst.name] = client
                method = "direct_db" if isinstance(client, RadarrDbClient) else "api"
                self._radarr_status[inst.name] = {"connected": True, "method": method}
            else:
                self._radarr_status[inst.name] = {"connected": False}
            self._radarr_mappers[inst.name] = PathMapper(
                root_folders=inst.root_folders,
                container_paths=inst.movie_paths,
            )

        for inst in sonarr_instances:
            client = _build_sonarr_client(inst)
            if client:
                self._sonarr[inst.name] = client
                method = "direct_db" if isinstance(client, SonarrDbClient) else "api"
                self._sonarr_status[inst.name] = {"connected": True, "method": method}
            else:
                self._sonarr_status[inst.name] = {"connected": False}
            self._sonarr_mappers[inst.name] = PathMapper(
                root_folders=inst.root_folders,
                container_paths=inst.tv_paths,
            )

        _log("INFO", f"Instance registry: {len(self._radarr)} Radarr, {len(self._sonarr)} Sonarr")

    def radarr(self, name: str = "radarr") -> Optional[AnyRadarrClient]:
        """Look up a Radarr client by instance name."""
        return self._radarr.get(name)

    def sonarr(self, name: str = "sonarr") -> Optional[AnySonarrClient]:
        """Look up a Sonarr client by instance name."""
        return self._sonarr.get(name)

    def radarr_mapper(self, name: str = "radarr") -> Optional[PathMapper]:
        """Look up the PathMapper for a Radarr instance."""
        return self._radarr_mappers.get(name)

    def sonarr_mapper(self, name: str = "sonarr") -> Optional[PathMapper]:
        """Look up the PathMapper for a Sonarr instance."""
        return self._sonarr_mappers.get(name)

    def radarr_status(self, name: str = "radarr") -> dict:
        """Return connection status for a Radarr instance by name.

        Returns {"connected": True, "method": "direct_db"|"api"} or {"connected": False}.
        """
        return self._radarr_status.get(name, {"connected": False})

    def sonarr_status(self, name: str = "sonarr") -> dict:
        """Return connection status for a Sonarr instance by name."""
        return self._sonarr_status.get(name, {"connected": False})

    def all_radarr_statuses(self) -> Dict[str, dict]:
        return dict(self._radarr_status)

    def all_sonarr_statuses(self) -> Dict[str, dict]:
        return dict(self._sonarr_status)

    def all_radarr(self) -> Dict[str, AnyRadarrClient]:
        return dict(self._radarr)

    def all_sonarr(self) -> Dict[str, AnySonarrClient]:
        return dict(self._sonarr)

    @property
    def radarr_names(self):
        return list(self._radarr.keys())

    @property
    def sonarr_names(self):
        return list(self._sonarr.keys())


def build_registry(config) -> InstanceRegistry:
    """Build the instance registry from a ChronarrConfig object."""
    return InstanceRegistry(config.radarr_instances, config.sonarr_instances)
