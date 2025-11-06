"""
Version utility module for Chronarr
Provides centralized version string management
"""
from pathlib import Path


def get_version() -> str:
    """
    Get application version from VERSION file

    Returns version string with optional branch suffix:
    - Production: e.g., "2.0.1"
    - Dev branch: e.g., "2.0.1-dev"
    - Feature branch: e.g., "2.0.1-feature-name"
    """
    try:
        version = (Path(__file__).parent / "VERSION").read_text().strip()
    except:
        version = "0.1.0"

    # Check if running from dev/feature branch (detect at runtime)
    try:
        # Try to read git branch from .git/HEAD
        git_head_path = Path(__file__).parent / ".git" / "HEAD"
        if git_head_path.exists():
            head_content = git_head_path.read_text().strip()
            if "ref: refs/heads/dev" in head_content:
                version = f"{version}-dev"
            elif head_content.startswith("ref: refs/heads/"):
                # Extract branch name for feature branches
                branch = head_content.replace("ref: refs/heads/", "")
                if branch not in ["main", "master"]:
                    version = f"{version}-{branch}"
    except:
        pass

    return version
