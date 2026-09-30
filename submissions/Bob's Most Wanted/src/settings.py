"""Application settings loaded from a JSON configuration file."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel


class Settings(BaseModel):
    """Runtime configuration for the bobathon pipeline."""

    input_path: Path
    output_path: Path
    default_timezone: str = "Europe/Zurich"


def load_settings(path: Path) -> Settings:
    """Load and validate settings from a JSON file at *path*."""
    with path.open(encoding="utf-8") as fh:
        data = json.load(fh)
    return Settings.model_validate(data)
