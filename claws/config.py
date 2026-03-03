"""Local project configuration stored in .claws/project.json."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Optional, Tuple

CONFIG_DIR = ".claws"
CONFIG_FILE = "project.json"


def find_project_config() -> Optional[Path]:
    """Walk up from CWD to find .claws/project.json, like git finds .git."""
    current = Path.cwd()
    while True:
        candidate = current / CONFIG_DIR / CONFIG_FILE
        if candidate.exists():
            return candidate
        parent = current.parent
        if parent == current:
            return None
        current = parent


def load_project_config() -> Dict[str, str]:
    """Return the nearest .claws/project.json as a dict, or {} if not found."""
    path = find_project_config()
    if path is None:
        return {}
    with open(path) as f:
        return json.load(f)


def save_project_config(
    project: str,
    region: str,
    directory: Optional[Path] = None,
) -> Path:
    """Write .claws/project.json in *directory* (default: CWD).

    Creates the .claws directory if it doesn't exist.
    Returns the path to the written file.
    """
    if directory is None:
        directory = Path.cwd()
    config_dir = directory / CONFIG_DIR
    config_dir.mkdir(exist_ok=True)
    config_path = config_dir / CONFIG_FILE
    with open(config_path, "w") as f:
        json.dump({"project": project, "region": region}, f, indent=2)
    return config_path


def resolve(
    project: Optional[str],
    region: Optional[str],
    cfg: Optional[Dict[str, str]] = None,
) -> Tuple[str, str]:
    """Resolve project and region from explicit values, falling back to *cfg*.

    Raises ValueError with a helpful message if either value is still missing.
    *cfg* defaults to the loaded project config when not supplied.
    """
    if cfg is None:
        cfg = load_project_config()
    project = project or cfg.get("project")
    region = region or cfg.get("region")
    missing = []
    if not project:
        missing.append("project")
    if not region:
        missing.append("region")
    if missing:
        raise ValueError(
            f"Missing {', '.join(missing)}. "
            "Pass via --project/--region or create .claws/project.json "
            "(run 'claws init' to generate it automatically)."
        )
    return project, region
