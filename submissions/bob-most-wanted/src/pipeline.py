"""Typed contract for the future data processing pipeline."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from unified_data import UnifiedData


class Pipeline(Protocol):
    """Interface for a pipeline that processes a directory of source files."""

    def run(self, input_path: Path) -> UnifiedData:
        """Process all data sources under *input_path* and return unified records."""
        ...
