"""Run real PostgreSQL migration/storage checks in a disposable local cluster.

Install the optional tools with: uv pip install -e ".[dev,storage-test]".
No model API, Docker daemon, production database or developer .env is used.
"""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import tempfile


def main() -> int:
    import embedded_postgres

    service = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix="blogapp-semantic-storage-") as directory:
        server = embedded_postgres.get_server(directory, cleanup_mode="stop")
        try:
            uri = server.get_uri()
            env = dict(os.environ, AGENT_ENV_FILE=os.devnull, AGENT_TEST_DB_URL=uri,
                       AGENT_DB_URL=uri.replace("postgresql://", "postgresql+asyncpg://", 1),
                       AGENT_DB_SCHEMA="agent", AGENT_RUN_PAID_TESTS="0", AGENT_RUN_NETWORK_TESTS="0")
            base = [sys.executable, "-m", "alembic", "-c", "migrations/alembic.ini"]
            subprocess.run([*base, "upgrade", "head"], cwd=service, env=env, check=True)
            subprocess.run([sys.executable, "-m", "pytest", "tests/storage", "-q"], cwd=service, env=env, check=True)
            subprocess.run([*base, "downgrade", "0005"], cwd=service, env=env, check=True)
            subprocess.run([*base, "upgrade", "head"], cwd=service, env=env, check=True)
            print("Real PostgreSQL migration, storage constraints, tombstone and restart checks passed.")
        finally:
            server.cleanup()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
