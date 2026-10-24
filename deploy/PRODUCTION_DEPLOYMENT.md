# EC2 production runbook

These are future operator steps. Do not apply or publish until credentials are
configured and the owner authorizes the release. Never paste real `.env` files
into logs or issue comments, and never run `docker compose config` without
`--quiet` or the secret-safe validation pipeline below on production credentials.

## 1. Prepare images away from t3.micro

Use [the image build guide](DOCKER_HUB_DEPLOYMENT.md). Build the API, web and agent
from the same checkout with one immutable release tag and `linux/amd64` platform.
Do not compile .NET or Next.js on the 1 GiB instance. The manual GitHub workflow
`image-build.yml` can build all three; registry publishing defaults to disabled.
Pass the exact production `https://DOMAIN` as the build-time site origin and
the approved public author name; these values cannot be changed by adding
container environment variables after the Next.js image is built.
Configure an authorized registry pull identity on EC2 if images are private.

## 2. Prepare the host and TLS boundary

Use a maintained 64-bit Linux image, Docker Engine with cgroup v2 and Docker Compose >= 5.6.1,
Python 3, at least 5 GiB free Docker disk space (10+ GiB recommended), and room for
database backups outside the Docker filesystem. Keep EBS encrypted. On a t3.micro
configure **at least 2 GiB swap** on encrypted EBS before deploying; make it
persistent across reboots and restrict the swap file to root. Do not create swap
on an unencrypted or ephemeral volume. The script verifies configured swap and
combined RAM/swap before any mutation, but encryption is an infrastructure check.

Compose 5.6.1 is the minimum supported exporter and is pinned in CI. Older
versions can omit an explicit `create_host_path: false` when rendering JSON;
the private-profile gate requires this value and rejects ambiguous mount options.
The deployment script checks the CLI version before rendering configuration or
contacting the daemon. See the [official release](https://github.com/docker/compose/releases/tag/v5.6.1).

Terminate HTTPS at an ALB with a managed certificate for `DOMAIN` and
`www.DOMAIN`. Redirect ALB HTTP to HTTPS and forward HTTPS traffic to Nginx port 80.
The EC2 security group must allow port 80 **only from the ALB security group**;
Nginx trusts the ALB's forwarded protocol headers. Set target health to `/health`.
Allow SSH only from the administration network. Do not open 3000, 5432, 5672,
6379, 8080 or the RabbitMQ management port. Outbound HTTPS and DNS must reach the
selected LLM provider and `api.openai.com` for embeddings.

Prepare bind directories for the non-root API image:

```bash
cd /path/to/blogapp/deploy
sudo install -d -o 1001 -g 1001 -m 750 uploads uploads/images keys
cp .env.example .env
chmod 600 .env
# Edit .env locally; keep existing DB credentials/database when upgrading.
```

Generate independent secrets, for example with `openssl rand -hex 32`. The
preflight rejects empty/placeholder secrets and reused broker role passwords.
`JWT_SECRET` needs at least 64 characters, the content service key at least 32,
DB/cache/broker secrets at least 24 and admin password at least 12. DB passwords
must not contain `;` or double quotes; cache passwords must not contain commas.
Random hex values avoid Compose and connection-string quoting problems.

Install the approved author-profile bundle separately from the release images.
Set `AUTHOR_PROFILE_HOST_DIR` to its absolute Linux host path, for example
`/opt/blogapp-private/author-profile`. Copy the private bundle using an approved
private transfer channel to encrypted EBS; never commit it, add it to an artifact,
or upload it to GitHub, a Docker build context, an image or a registry. The API
and worker mount exactly this same directory read-only, and Compose refuses to
create a missing directory. The tracked sample profile remains a development/test
fixture and is rejected by the production gate.

On the server, restrict this directory and its three required files to the release
operator and container GID 1001. For example, install directories with ownership
`release-operator:1001` and
mode 750, and `manifest.json`, `profile.json`, `source/author-profile.source.md`
with ownership `release-operator:1001` and mode 640. Container UID/GID 1001 needs read permission
and directory traversal; other host users must have no access. Do not change the
bundle bytes when transferring: the shared preflight validator verifies the
manifest/content/source hashes before both runtimes read the same bundle.
Run the shared validation before deployment:

```bash
python3 profile_bundle.py validate /opt/blogapp-private/author-profile
bash deploy.sh --check
```

The built API has an independent exact-reader offline check, which does not
construct a host or connect to a database:

```bash
dotnet /path/to/published/BlogApp.Presentation.Api.dll --validate-author-profile /opt/blogapp-private/author-profile
```

Host preflight validates the approved production identity, every declared hash,
the readonly identical mounts, and UID/GID 1001 file access. Configuration-only
validation checks mount wiring without reading private files. Never paste the
bundle, raw source text, or full environment into CI logs. Back up the private
bundle separately to encrypted private storage; restoring images alone does not
restore this source.

Set `AGENT_LLM_MODEL` to the actual selected model. `AGENT_LLM_API_KEY` may also
supply embeddings when it is an OpenAI key using the default OpenAI LLM endpoint.
For another LLM provider, set `AGENT_EMBEDDING_API_KEY` to a separate OpenAI key.
Embeddings always use OpenAI `text-embedding-3-small` with 1536 dimensions. Text
chunks and user questions are transmitted to OpenAI; there is no local hash or
JSON embedding substitute. Existing canonical profile JSON remains source
content, and messaging JSON remains the wire contract.

## 3. Verify storage before the first apply

Existing installations retain the external `deploy_postgres_data` volume at
`/var/lib/postgresql` and `deploy_redis_data`. The Postgres major version stays 18;
there is no pgvector image replacement or data-directory move. Verify the
running container's actual mount, database version, database name and restore
procedure before upgrading. If the historical data is in a different or
anonymous volume, stop and migrate it explicitly from a verified backup; never
create an empty volume over existing data. Do not run `down -v` or `volume prune`.

For an existing release the apply script identifies the PostgreSQL container by
this volume and refuses migration if a compressed `pg_dump` fails. Copy that dump
to encrypted off-host storage and test restore independently. The script does not
claim its local backup file is a complete disaster-recovery system.

## 4. Validate, then apply only when authorized

```bash
# Default action: validate secrets/config/resources/storage without changing containers.
bash deploy.sh --check
# A brand-new installation has no existing external volumes:
bash deploy.sh --check --first-install
```

The later authorized apply commands are:

```bash
# Existing installation; successful DB backup is mandatory.
bash deploy.sh --apply
# New installation only; refused if the existing PostgreSQL volume/container exists.
bash deploy.sh --apply --first-install
```

Apply pulls prebuilt images, provisions salted broker role definitions, starts
database/cache/broker, runs the Python migration once per release, then starts
API/worker/frontend/Nginx with bounded health waits. The API is the sole broker
topology declarer. Its EF startup migrations finish before the worker fetches
content. The worker cannot start if Alembic fails or required provider settings
are absent. No paid model call is made by the script's health checks; content sync
and user runs can incur provider charges after worker startup.

RabbitMQ 4.3.6 uses a non-management image, a fixed hostname and persisted storage.
Definitions contain salted SHA-256 hashes only. The generated volume is restricted
to this stack. To rotate persisted broker credentials, first use the documented RabbitMQ
CLI credential-rotation procedure, update the matching environment values,
close old user connections and restart broker/API/worker together. Boot imports
seed a blank broker; editing .env or regenerating definitions alone must not be
treated as a verified password rotation. Password changes in PostgreSQL/Redis/JWT/admin accounts have
separate stateful rotation procedures; editing `.env` alone does not update an
existing database role or seeded admin account.

## 5. Acceptance before routing users

Health is necessary but insufficient. With live-call approval and real keys:

1. Confirm all seven runtime services are healthy, both setup jobs exited 0, and
   `/health/ready` plus `/health/agent` pass from inside the API container.
2. Publish/edit a real article, wait for the real embedding/index update, and ask
   a Turkish question whose answer is in that article. Verify cited text matches
   the stored revision and no static sample content appears.
3. Restart only the Python worker and repeat retrieval; persisted vectors must
   still resolve without replacing them with hash/JSON fixtures. Verify changed
   or deleted content does not remain retrievable under its old revision.
   Restart while a run awaits user input and verify its checkpoint resumes from
   the persistent `deploy_agent_state` volume.
4. In a real browser through HTTPS, verify guest/authenticated agent acceptance,
   incremental events, cancellation/resume where offered, `/hubs/agent-runs`
   WebSocket negotiation and `/hubs/public-cache` updates. Confirm the internal
   `/api/v1/agent/internal/` path returns 404 at the public proxy.
5. Observe idle startup, first index, repeated Q&A and a research run with
   `docker stats`, `free -m`, `vmstat 1`, RabbitMQ alarms/outbox backlog and EC2
   CPU credits. Require no OOMKilled container, no sustained swap thrashing,
   no broker memory/disk alarm, bounded backlog and acceptable user latency.
   Test a reboot and verify persistent data plus automatic service restart.
6. Test provider timeout/rate-limit and broker interruption: surface an explicit
   error/backlog, preserve accepted work, and confirm recovery. A green offline
   build or heartbeat does not certify provider credentials or response quality.

If this fails on t3.micro, increase memory or move PostgreSQL/broker off-host;
do not remove feature paths, lower safety thresholds or label an unmeasured
configuration production-validated. Compose ceilings total 1424 MiB plus the host
and migration spikes; swap is required here and is not a performance guarantee.

## 6. Operations and rollback

```bash
docker compose --env-file .env -f docker-compose.prod.yml ps
docker compose --env-file .env -f docker-compose.prod.yml logs --tail=100 api ai-agent
docker stats --no-stream
```

Use external monitoring for failed/healthy transitions: Docker Compose does not
automatically restart a merely unhealthy container; the worker exits on fatal
supervised-task failure, while dependency alarms require operator action. Log
rotation is bounded. Rotate/restrict logs and backups as they can contain content.

For application rollback, select the previously verified `RELEASE_TAG` for all
three images together, review compatibility of both EF and Alembic migrations,
and run validation before applying. Do not downgrade databases or run the legacy
`rollback-migration.sh` automatically. A schema rollback/data restore requires a
reviewed maintenance procedure and a tested restore, with worker/API writers
stopped. Preserve `uploads`, data-protection `keys`, PostgreSQL and RabbitMQ data.
Back up and restore `deploy_agent_state` consistently with agent job state; it
contains durable execution checkpoints and may contain private user input.

## Configuration references

- [RabbitMQ boot-time definitions](https://www.rabbitmq.com/docs/definitions)
- [RabbitMQ absolute memory watermark](https://www.rabbitmq.com/docs/memory)
- [RabbitMQ production resource guidelines](https://www.rabbitmq.com/docs/production-checklist)
- [Compose dependency conditions](https://docs.docker.com/reference/compose-file/services/)

- [RabbitMQ credential rotation](https://www.rabbitmq.com/docs/access-control#credential-rotation)
- [RabbitMQ release support](https://www.rabbitmq.com/release-information)
- [Node.js supported releases](https://nodejs.org/en/about/previous-releases)
- [Docker build context ignore files](https://docs.docker.com/build/concepts/context/)
- [.NET garbage collector memory limits](https://learn.microsoft.com/en-us/dotnet/core/runtime-config/garbage-collector)
