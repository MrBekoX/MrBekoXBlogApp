"""Run backend content/bootstrap tests against disposable localhost PostgreSQL.

Run with the optional storage-test dependencies installed. On WSL, a Windows
.NET SDK is supported through WSLENV's process-local /w variable forwarding.
The temporary server binds only 127.0.0.1, uses local test-only trust auth, and
is stopped in finally. No developer .env, production database or model API is
used. Existing PostgreSQL processes and databases are never selected.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import os
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile


DEFAULT_FILTER = "|".join(
    "FullyQualifiedName~BlogApp.Presentation.Api.Tests.Messaging.Content." + name
    for name in (
        "DbSeederBootstrapTests",
        "ContentSyncStartupServiceTests",
        "ContentSnapshotSyncServiceTests",
        "AgentResultPresentationGuardTests",
    )
)


@contextmanager
def temporary_postgres():
    from embedded_postgres._commands import initdb, pg_ctl

    with tempfile.TemporaryDirectory(prefix="blogapp-backend-storage-") as directory:
        root = Path(directory).resolve()
        cluster = root / "pgdata"
        cluster.mkdir()
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as reservation:
            reservation.bind(("127.0.0.1", 0))
            port = reservation.getsockname()[1]
        try:
            initdb(["--auth-local=trust", "--auth-host=trust", "--encoding=utf8", "-U", "postgres"], pgdata=cluster)
            pg_ctl([
                "-w", "-t", "20", "-l", str(root / "postgres.log"),
                "-o", f"-h 127.0.0.1 -p {port} -k {root}", "start",
            ], pgdata=cluster, timeout=30)
            yield port
        finally:
            # Check the unique cluster's own PID file even when startup raised
            # after starting its process. Never act on an existing cluster.
            if (cluster / "postmaster.pid").exists():
                try:
                    pg_ctl(["-w", "-t", "20", "-m", "immediate", "stop"], pgdata=cluster, timeout=30)
                except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
                    import psutil

                    # A failed pg_ctl must not leave a detached test server.
                    # Verify its exact PGDATA before touching the owned PID.
                    try:
                        pid = int((cluster / "postmaster.pid").read_text().splitlines()[0])
                        process = psutil.Process(pid)
                        if str(cluster) not in process.cmdline():
                            raise RuntimeError("Temporary PostgreSQL PID no longer matches its owned data directory")
                        process.terminate()
                        try:
                            process.wait(timeout=5)
                        except psutil.TimeoutExpired:
                            process.kill()
                            process.wait(timeout=5)
                    except (FileNotFoundError, psutil.NoSuchProcess):
                        pass  # pg_ctl completed its stop while the timeout fired.


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--filter", default=DEFAULT_FILTER)
    parser.add_argument("--no-build", action="store_true")
    parser.add_argument("--configuration", choices=("Debug", "Release"), default="Release")
    parser.add_argument("--dotnet", help="Explicit .NET executable, including a Windows dotnet.exe under WSL")
    args = parser.parse_args()
    service = Path(__file__).resolve().parents[1]
    repo = service.parents[2]
    project = repo / "src/backend/Presentation/Api.Tests/BlogApp.Presentation.Api.Tests.csproj"
    dotnet = args.dotnet or shutil.which("dotnet") or "/mnt/c/Program Files/dotnet/dotnet.exe"
    if not Path(dotnet).is_file():
        parser.error("A local .NET SDK is required; pass --dotnet if necessary.")
    windows_sdk = Path(dotnet).suffix.casefold() == ".exe" and os.name != "nt"
    project_argument = str(project)
    if windows_sdk:
        project_argument = subprocess.check_output(["wslpath", "-w", str(project)], text=True).strip()
    with temporary_postgres() as port:
        env = dict(os.environ)
        env["BLOGAPP_TEST_PG_CONNECTION"] = (
            f"Host=127.0.0.1;Port={port};Username=postgres;Database=postgres;"
            "Pooling=false;Timeout=10;Command Timeout=30"
        )
        env["DOTNET_CLI_TELEMETRY_OPTOUT"] = "1"
        env["DOTNET_NOLOGO"] = "1"
        if windows_sdk:
            forwarded = {"BLOGAPP_TEST_PG_CONNECTION", "DOTNET_CLI_TELEMETRY_OPTOUT", "DOTNET_NOLOGO"}
            entries = [entry for entry in env.get("WSLENV", "").split(":")
                       if entry and entry.split("/", 1)[0] not in forwarded]
            env["WSLENV"] = ":".join(entries + [name + "/w" for name in sorted(forwarded)])
        command = [dotnet, "test", project_argument, "--no-restore", "--configuration", args.configuration, "--filter", args.filter,
                   "--logger", "console;verbosity=normal"]
        if args.no_build:
            command.append("--no-build")
        print("Disposable PostgreSQL ready on localhost; running backend content/bootstrap tests.", flush=True)
        subprocess.run(command, cwd=repo, env=env, check=True, timeout=600)
    print("Backend storage checks passed; temporary PostgreSQL stopped.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
