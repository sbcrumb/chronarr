from pathlib import Path


class PathMapper:
    """Maps filesystem paths between what Radarr/Sonarr report and what the container sees.

    One PathMapper is created per configured instance at startup, built from
    that instance's root_folders and container_paths. The mapping logic is
    identical for Radarr and Sonarr — only the data differs.
    """

    def __init__(self, root_folders: list, container_paths: list, debug: bool = False):
        self.root_folders = root_folders
        self.container_paths = container_paths
        self.debug = debug

    @staticmethod
    def _normalize(path: str) -> str:
        """Backslash to forward slash — handles UNC paths from Windows/Radarr."""
        return path.replace('\\', '/')

    def map(self, path: str) -> str:
        """Translate an external path to its container equivalent.

        Tries each configured root folder longest-first to avoid prefix collisions
        (e.g. /movies matching before /movies/4k). Returns the original path
        unchanged if nothing matches — let the caller decide what to do.
        """
        normalized = self._normalize(path)
        roots = sorted(enumerate(self.root_folders), key=lambda x: len(x[1]), reverse=True)
        for idx, root in roots:
            norm_root = self._normalize(root)
            if normalized.startswith(norm_root + '/') or normalized == norm_root:
                if idx < len(self.container_paths):
                    rel = normalized[len(norm_root):].lstrip('/')
                    result = str(Path(self.container_paths[idx]) / rel) if rel else self.container_paths[idx]
                    if self.debug:
                        print(f"[path_mapper] {path!r} -> {result!r}")
                    return result
        if self.debug:
            print(f"[path_mapper] no match for {path!r}, returning as-is")
        return path

    # Backward-compat aliases — existing call sites use these names.
    def radarr_path_to_container_path(self, path: str) -> str:
        return self.map(path)

    def sonarr_path_to_container_path(self, path: str) -> str:
        return self.map(path)
