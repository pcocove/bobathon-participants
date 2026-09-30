"""Atomic JSON storage for analysis artefacts."""
from __future__ import annotations

import json
import os
import tempfile
import threading
from pathlib import Path

_lock = threading.Lock()


def write_json(path: Path, data, indent: int | None = 1) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with _lock:
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-", suffix=".json")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=indent)
                f.write("\n")
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, path)
        except BaseException:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise


def read_json(path: Path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default
