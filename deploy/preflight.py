"""Validate rendered Compose JSON without printing secrets or executing .env files.

Usage: docker compose --env-file .env -f docker-compose.prod.yml config --format json
       | python3 preflight.py [--config-only]
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import shutil
import stat
import sys
from pathlib import Path, PurePosixPath


def profile_mount(config: dict) -> tuple[str, list[str]]:
    """Require the same private, read-only Linux host bundle for both runtimes."""
    errors = []
    sources = []
    for service, target in (("api", "/app/content/author-profile"),
                            ("ai-agent", "/srv/content/author-profile")):
        mounts = [volume for volume in config.get("services", {}).get(service, {}).get("volumes", [])
                  if isinstance(volume, dict) and volume.get("target") == target]
        if len(mounts) != 1:
            errors.append(f"{service} requires exactly one private author-profile bind mount")
            continue
        mount = mounts[0]
        source = str(mount.get("source") or "")
        path = PurePosixPath(source)
        if (mount.get("type") != "bind" or not mount.get("read_only")
                or mount.get("bind", {}).get("create_host_path") is not False
                or not path.is_absolute() or source == "/" or ".." in path.parts
                or "\\" in source):
            errors.append(f"{service} author profile must use an explicit existing absolute Linux host path with a read-only bind")
        sources.append(source)
    if len(sources) == 2 and sources[0] != sources[1]:
        errors.append("API and worker must mount the same private author-profile host directory")
    return (sources[0] if len(sources) == 2 and sources[0] == sources[1] else ""), errors


def validate_private_profile(directory: str) -> list[str]:
    """Use the shared source/hash validator; report permission errors without PII."""
    path = Path(directory)
    if not directory or not path.is_dir():
        return ["Install the approved private author-profile bundle before applying"]
    spec = importlib.util.spec_from_file_location(
        "blogapp_profile_bundle_validator", Path(__file__).with_name("profile_bundle.py"))
    if spec is None or spec.loader is None:
        return ["The shared production author-profile validator is missing"]
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
        errors = list(module.validate_bundle(path, require_production=True))
    except (ImportError, OSError):
        return ["The production author-profile validator or bundle cannot be read"]
    if errors:
        return errors
    for relative in (".", "source", "manifest.json", "profile.json", "source/author-profile.source.md"):
        item = path / relative
        try:
            mode = item.stat()
        except OSError:
            return ["Required private author-profile files must be readable"]
        permissions = stat.S_IMODE(mode.st_mode)
        required = 5 if item.is_dir() else 4
        granted = ((permissions >> 6) & 7 if mode.st_uid == 1001 else
                   (permissions >> 3) & 7 if mode.st_gid == 1001 else permissions & 7)
        if granted & required != required:
            return ["The private author-profile bundle must be readable by container UID/GID 1001"]
        if permissions & 7:
            return ["Private author-profile files/directories must not grant access to other host users"]
    return []


def validate_config(config: dict) -> list[str]:
    errors: list[str] = []
    services = config.get("services", {})
    required_services = {"postgres", "redis", "rabbitmq", "rabbitmq-definitions",
                         "agent-migrate", "api", "ai-agent", "frontend", "nginx"}
    if not required_services.issubset(services):
        return ["Compose must contain the complete API, worker, migration, broker and frontend stack"]
    api = services["api"].get("environment", {})
    agent = services["ai-agent"].get("environment", {})
    broker = services["rabbitmq-definitions"].get("environment", {})
    postgres = services["postgres"].get("environment", {})
    redis = services["redis"].get("environment", {})
    required = [
        (api, "JwtSettings__Secret", 64),
        (api, "AdminUser__Password", 12),
        (api, "AgentService__InternalApiKey", 32),
        (postgres, "POSTGRES_PASSWORD", 24),
        (redis, "REDISCLI_AUTH", 24),
        (agent, "AGENT_LLM_API_KEY", 16),
        *[(broker, key, 24) for key in ("RABBITMQ_BACKEND_PASSWORD",
                                       "RABBITMQ_AGENT_PASSWORD", "RABBITMQ_DECLARER_PASSWORD")],
    ]
    for env, key, minimum in required:
        value = str(env.get(key) or "").strip()
        if len(value) < minimum or re.search(r"change.?me|your[-_ ]|placeholder|example|<.*>", value, re.I):
            errors.append(f"{key} must be configured with a secret of at least {minimum} characters")
    if len({broker.get(key) for key in broker}) != 3:
        errors.append("Broker roles must have three different passwords")
    if re.search(r'[;"\r\n]', str(postgres.get("POSTGRES_PASSWORD", ""))):
        errors.append("POSTGRES_PASSWORD must not contain connection-string separators; use a random hex secret")
    if re.search(r'[,\r\n]', str(redis.get("REDISCLI_AUTH", ""))):
        errors.append("REDIS_PASSWORD must not contain connection-string separators; use a random hex secret")
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", str(postgres.get("POSTGRES_USER", ""))):
        errors.append("POSTGRES_USER must be a simple PostgreSQL role name")
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", str(postgres.get("POSTGRES_DB", ""))):
        errors.append("POSTGRES_DB must be a simple database name")
    if "@" not in str(api.get("AdminUser__Email", "")):
        errors.append("ADMIN_EMAIL must be configured")
    domain = str(services["nginx"].get("environment", {}).get("DOMAIN", ""))
    if not re.fullmatch(r"(?=.{1,253}$)(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,63}", domain):
        errors.append("DOMAIN must be a public DNS name without scheme, path or port")
    if not str(agent.get("AGENT_LLM_MODEL", "")).strip():
        errors.append("AGENT_LLM_MODEL must be selected explicitly")
    if agent.get("AGENT_EMBEDDING_MODEL") != "text-embedding-3-small" or str(agent.get("AGENT_EMBEDDING_DIMENSIONS")) != "1536":
        errors.append("Embedding model must be text-embedding-3-small with 1536 dimensions")
    embedding_key = str(agent.get("AGENT_EMBEDDING_API_KEY") or "")
    if embedding_key and (len(embedding_key) < 16 or re.search(r"change.?me|placeholder|your[-_ ]", embedding_key, re.I)):
        errors.append("AGENT_EMBEDDING_API_KEY must be a valid secret when supplied")
    if not embedding_key and str(agent.get("AGENT_LLM_BASE_URL", "")).rstrip("/") != "https://api.openai.com/v1":
        errors.append("A non-OpenAI LLM endpoint requires a separate OpenAI AGENT_EMBEDDING_API_KEY")
    if agent.get("AGENT_CONTENT_BASE_URL") != "http://api:8080/api/v1":
        errors.append("Agent internal content URL must target the API service")
    if agent.get("AGENT_CONTENT_SERVICE_KEY") != api.get("AgentService__InternalApiKey"):
        errors.append("Agent and API internal authentication keys must match")
    if str(agent.get("AGENT_TOPOLOGY_DECLARE", "")).lower() not in ("false", "0"):
        errors.append("The production worker must not declare broker topology")
    tags = []
    for name, prefix in (("api", "api-"), ("frontend", "web-"), ("ai-agent", "agent-")):
        image = str(services[name].get("image", ""))
        repository, _, tag = image.rpartition(":")
        if not repository or not tag.startswith(prefix) or tag[len(prefix):] in ("", "latest"):
            errors.append(f"{name} image must have a release-specific {prefix} tag")
        tags.append((repository, tag[len(prefix):]))
    if len(set(tags)) != 1:
        errors.append("API, frontend and worker images must use the same repository and release tag")
    if services["agent-migrate"].get("image") != services["ai-agent"].get("image"):
        errors.append("Migrations and worker must use the same image")
    _, mount_errors = profile_mount(config)
    errors.extend(mount_errors)
    return errors


def validate_host(config: dict) -> list[str]:
    errors = []
    if not sys.platform.startswith("linux"):
        return ["Production host preflight must run on Linux; use --config-only for static validation"]
    memory = {}
    for line in Path("/proc/meminfo").read_text().splitlines():
        key, value = line.split(":", 1)
        memory[key] = int(value.strip().split()[0]) * 1024
    mib = 1024 * 1024
    ram, swap = memory["MemTotal"], memory["SwapTotal"]
    if ram < 850 * mib:
        errors.append("Host requires at least 850 MiB usable RAM")
    if ram < 1536 * mib and swap < 2048 * mib:
        errors.append("A t3.micro class host requires at least 2 GiB configured swap on encrypted EBS")
    if ram + swap < 2800 * mib:
        errors.append("Host requires at least 2800 MiB combined RAM and swap")
    root = Path(os.environ.get("DEPLOY_DOCKER_ROOT", "/var/lib/docker"))
    while not root.exists():
        root = root.parent
    if shutil.disk_usage(root).free < 5 * 1024**3:
        errors.append("Docker filesystem requires at least 5 GiB free space before pulling release images")
    for name in ("uploads", "keys"):
        folder = Path(__file__).resolve().parent / name
        if not folder.is_dir() or folder.stat().st_uid != 1001 or folder.stat().st_gid != 1001:
            errors.append(f"Prepare deploy/{name} owned by container UID:GID 1001:1001 before applying")
    source, mount_errors = profile_mount(config)
    if not mount_errors:
        errors.extend(validate_private_profile(source))
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config-only", action="store_true")
    args = parser.parse_args()
    try:
        config = json.load(sys.stdin)
    except (ValueError, TypeError):
        print("Preflight failed: no valid rendered Compose JSON received", file=sys.stderr)
        return 1
    errors = validate_config(config)
    if not args.config_only:
        errors.extend(validate_host(config))
    for error in errors:
        print(f"Preflight failed: {error}", file=sys.stderr)
    if errors:
        return 1
    print("Preflight passed (configuration only)." if args.config_only else
          "Preflight passed; memory limits require observation under the actual workload.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
