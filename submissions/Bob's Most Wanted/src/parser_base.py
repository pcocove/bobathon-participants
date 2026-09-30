"""Protocol contract for data parsers."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from unified_data import DataPoint


class DataParser(Protocol):
    """Interface that every concrete parser must satisfy."""

    def parse(self, path: Path) -> list[DataPoint]:
        """Parse a file and return a list of normalised DataPoint records."""
        ...
