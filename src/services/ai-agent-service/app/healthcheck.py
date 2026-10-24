"""Check the supervised worker heartbeat without contacting a model API."""

from __future__ import annotations

import os
import time
from pathlib import Path


def heartbeat_path() -> Path:
    return Path(os.environ.get("AGENT_HEALTH_FILE", "/tmp/blogapp-agent-heartbeat"))


def healthy() -> bool:
    try:
        age = time.time() - heartbeat_path().stat().st_mtime
        return 0 <= age <= 30
    except OSError:
        return False


if __name__ == "__main__":
    raise SystemExit(0 if healthy() else 1)
