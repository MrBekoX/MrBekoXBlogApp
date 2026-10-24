#!/usr/bin/env bash
# Validation is the default. Applying a release is an explicit, separate action.
set -euo pipefail
umask 077
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"

apply=false
first_install=false
for argument in "$@"; do
    case "$argument" in
        --apply) apply=true ;;
        --first-install) first_install=true ;;
        --check) ;;
        --help)
            printf '%s\n' 'Usage: ./deploy.sh [--check] [--apply [--first-install]]' \
                'Default: validate configuration, Linux resources and existing volume state only.' \
                '--apply: pull images, back up PostgreSQL, migrate, start, verify all services.' \
                '--first-install: create named data volumes only when no PostgreSQL container/volume exists.'
            exit 0 ;;
        *) printf 'Unknown option: %s\n' "$argument" >&2; exit 1 ;;
    esac
done
command -v docker >/dev/null || { echo 'Docker is required' >&2; exit 1; }
command -v python3 >/dev/null || { echo 'Python 3 is required for preflight' >&2; exit 1; }
# Older exporters can omit explicit create_host_path:false from normalized JSON.
# Check the supported exporter before reading configuration or contacting Docker.
compose_version=$(docker compose version --short)
python3 - "$compose_version" <<'PY'
import re
import sys
match = re.fullmatch(r'v?(\d+)\.(\d+)\.(\d+)(?:[-+][0-9A-Za-z.-]+)?', sys.argv[1].strip())
if match is None or tuple(map(int, match.groups())) < (5, 6, 1):
    raise SystemExit('Docker Compose >= 5.6.1 is required to preserve explicit private bind-mount options')
PY
[[ -f .env ]] || { echo 'Copy .env.example to .env and configure credentials first' >&2; exit 1; }
# Never source .env (Compose dotenv syntax is data, not shell code).
compose=(docker compose --env-file .env -f docker-compose.prod.yml)
export DEPLOY_DOCKER_ROOT
DEPLOY_DOCKER_ROOT=$(docker info --format '{{.DockerRootDir}}')
[[ $(docker info --format '{{.CgroupVersion}}') == 2 ]] || {
    echo 'A cgroup v2 Docker host is required for predictable RAM/swap accounting' >&2; exit 1;
}
"${compose[@]}" config --format json | python3 preflight.py

existing_pg=$(docker ps -aq --filter volume=deploy_postgres_data)
pg_volume=false
docker volume inspect deploy_postgres_data >/dev/null 2>&1 && pg_volume=true
if "$first_install"; then
    if "$pg_volume" || [[ -n "$existing_pg" ]]; then
        echo '--first-install refused: PostgreSQL data/container already exists; use normal --apply' >&2
        exit 1
    fi
else
    "$pg_volume" || { echo 'Existing deploy_postgres_data missing; audit storage or use --first-install for a new installation' >&2; exit 1; }
    docker volume inspect deploy_redis_data >/dev/null 2>&1 || { echo 'Existing deploy_redis_data missing; audit volume configuration first' >&2; exit 1; }
fi
if ! "$apply"; then
    echo 'Validation completed. No images pulled, migrations applied or containers changed.'
    exit 0
fi

mkdir -p backups
if ! "$first_install"; then
    # Locate by retained volume, including the old release's explicit container name.
    # A failed backup always aborts an existing installation's upgrade.
    [[ $(printf '%s\n' "$existing_pg" | sed '/^$/d' | wc -l) -eq 1 ]] || {
        echo 'Expected exactly one PostgreSQL container mounting deploy_postgres_data; upgrade aborted' >&2; exit 1;
    }
    [[ $(docker inspect -f '{{.State.Running}}' "$existing_pg") == true ]] || {
        echo 'Existing PostgreSQL is stopped; start and back up the old release first' >&2; exit 1;
    }
    backup="backups/blogdb-$(date -u +%Y%m%dT%H%M%SZ).dump"
    docker exec "$existing_pg" sh -c 'exec pg_dump -Fc -U "$POSTGRES_USER" -d "$POSTGRES_DB"' > "$backup"
    [[ -s "$backup" ]] || { echo 'Database backup is empty; upgrade aborted' >&2; exit 1; }
    echo "Database backup created: $backup"
fi
"${compose[@]}" pull
if "$first_install"; then
    docker volume create deploy_postgres_data >/dev/null
    docker volume create deploy_redis_data >/dev/null
fi
# Explicitly rerun bootstrap and migration on every release (even with unchanged image IDs).
"${compose[@]}" up --no-deps --force-recreate --abort-on-container-exit --exit-code-from rabbitmq-definitions rabbitmq-definitions
"${compose[@]}" up -d --wait --wait-timeout 240 postgres redis
# Reimport role definitions on broker restart, including explicitly rotated credentials.
"${compose[@]}" up -d --no-deps --force-recreate --wait --wait-timeout 240 rabbitmq
"${compose[@]}" up --no-deps --force-recreate --abort-on-container-exit --exit-code-from agent-migrate agent-migrate
"${compose[@]}" up -d --wait --wait-timeout 300 api ai-agent frontend nginx
"${compose[@]}" exec -T api curl -fsS http://localhost:8080/health/agent >/dev/null
"${compose[@]}" exec -T ai-agent python -m app.healthcheck
"${compose[@]}" ps
printf '%s\n' 'Release started; infrastructure/worker health checks passed.' \
    'Complete the real embedding, index-restart, article Q&A and browser SignalR acceptance checks before routing traffic.'
