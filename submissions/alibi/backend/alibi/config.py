"""Paths, team name and UI rules. No case-specific content."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

ALIBI_DIR = Path(__file__).resolve().parents[2]          # submissions/<team>/
REPO_ROOT = ALIBI_DIR.parents[1]                          # Repository-Wurzel
CONFIG_FILE = ALIBI_DIR / "alibi.config.json"


def _find_bundle(start: Path) -> Path | None:
    """Finds the case folder: a directory with README.md, interviews/ and slack_export/."""
    env = os.environ.get("ALIBI_BUNDLE")
    if env:
        p = Path(env).expanduser().resolve()
        return p if p.is_dir() else None
    candidates = []
    for readme in start.rglob("README.md"):
        d = readme.parent
        if "submissions" in d.parts or "node_modules" in str(d) or ".nosync" in str(d):
            continue
        if (d / "interviews").is_dir() and (d / "slack_export").is_dir():
            candidates.append(d)
    candidates.sort(key=lambda p: len(p.parts))
    return candidates[0] if candidates else None


@dataclass
class Settings:
    team: str = "alibi"
    bundle: Path | None = None
    template: Path = REPO_ROOT / "verdict_template.json"
    state_dir: Path = ALIBI_DIR / "state"
    verdict_path: Path = ALIBI_DIR / "verdict.json"
    # UI rule for the sheep game – not a statistical threshold proven by the case.
    sheep_threshold: float = 0.80
    bob_workers: int = 4
    bob_timeout_s: int = 900
    bob_command: list[str] = field(default_factory=lambda: ["bob"])
    label_package_chars: int = 60000
    # read-only share (e.g. on a server): no Bob calls, no write actions via the API
    readonly: bool = False

    @property
    def team_dir(self) -> Path:
        return REPO_ROOT / "submissions" / self.team


def load_settings() -> Settings:
    s = Settings()
    if CONFIG_FILE.exists():
        data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        for k, v in data.items():
            if k in ("bundle", "template") and v:
                p = Path(v)
                setattr(s, k, (p if p.is_absolute() else (REPO_ROOT / p)).resolve())
            elif hasattr(s, k) and not k.startswith("_"):
                setattr(s, k, v)
    s.team = os.environ.get("ALIBI_TEAM", s.team)
    if os.environ.get("ALIBI_READONLY", "").lower() in ("1", "true", "yes"):
        s.readonly = True
    if s.bundle is None:
        s.bundle = _find_bundle(REPO_ROOT)
    # Export immer in den eigenen Teamordner.
    s.verdict_path = s.team_dir / "verdict.json"
    s.state_dir.mkdir(parents=True, exist_ok=True)
    return s


SETTINGS = load_settings()


def template_names() -> list[str]:
    """The eight names from verdict_template.json – the authoritative source."""
    data = json.loads(SETTINGS.template.read_text(encoding="utf-8"))
    return [s["name"] for s in data["suspects"]]
