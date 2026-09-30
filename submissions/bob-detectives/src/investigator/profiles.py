"""The two agents built on the same framework."""

from __future__ import annotations

import os

PROFILES = {
    "investigator": {
        "name": "Investigator", "cli": "src/investigate", "mode": "investigator", "workdir": "investigation",
        "notes": "investigation/notes/case_memory.md", "finding_prefix": "F",
        "blurb": "Who did it, how sure, and where every piece of the reasoning comes from.",
    },
    "guard": {
        "name": "Security Guard", "cli": "src/guard", "mode": "securityguard", "workdir": "security",
        "notes": "investigation/notes/security_memory.md", "finding_prefix": "S",
        "blurb": "What is still weak, why the process let it happen, and what to do about it — no suspects.",
    },
}


def current() -> str:
    a = os.environ.get("INVESTIGATE_AGENT", "investigator")
    return a if a in PROFILES else "investigator"


def get(agent: str | None = None) -> dict:
    return {"id": agent or current(), **PROFILES[agent or current()]}
