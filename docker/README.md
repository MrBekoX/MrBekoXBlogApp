# Local complete stack

`docker-compose.yml` runs PostgreSQL, Redis, a loopback-only management broker,
.NET API, the real Python worker, a one-shot Python migration and Next.js. This
file is for a development workstation. Use `deploy/docker-compose.prod.yml` for
EC2, with role-separated broker identities and the EC2 preflight/runbook.

Copy `.env.example` to `.env` and configure the actual database, broker, JWT,
admin, internal-service and provider settings locally. Set `PUBLIC_AUTHOR_NAME` to the approved public author name; the local frontend
build uses `http://localhost:FRONTEND_PORT` as its site origin. Existing `.env` values
are not changed by this preparation. `AGENT_LLM_MODEL` is explicit; embeddings
use OpenAI `text-embedding-3-small` with 1536 dimensions. A separate
`AGENT_EMBEDDING_API_KEY` is required when the LLM is not using OpenAI. The stack has no demo model provider or JSON vector fallback. Its tracked
canonical author bundle in the code image is a development/test fixture. Both
local and production runtimes require the approved private bundle mounted
read-only through `AUTHOR_PROFILE_HOST_DIR`; missing folders are not created.
Private bundles/sources and checkpoints are excluded from Docker build contexts
and must never be committed, baked into images or uploaded to a registry.
Starting the real worker can incur embedding charges during content sync.

Prepare the approved bundle privately before starting the local stack. If it has
not already been prepared, use the generic tool from the repository root:

```bash
python deploy/profile_bundle.py build --source /absolute/private/approved-profile.source.md --output private/production-author-profile --as-of YYYY-MM-DD --approved
python deploy/profile_bundle.py validate private/production-author-profile
```

Choose the approved source's actual as-of date. Existing nonempty output is never
overwritten. The local default `../private/production-author-profile` resolves
from `docker/` to the Git-ignored repository `private/` directory. Both services
mount those exact same bytes; the API uses `/app/content/author-profile` and the
worker uses `/srv/content/author-profile`. A custom local path can be absolute or
relative to `docker/`; production requires an absolute Linux host path. Keep the
source and bundle outside images, registries, Git and public artifacts.

The exact API reader also supports an offline check before database or HTTP
startup, using a previously built API binary:

```bash
dotnet src/backend/Presentation/API/bin/Release/net10.0/BlogApp.Presentation.Api.dll --validate-author-profile /absolute/private/profile-bundle
```

Optional `PUBLIC_GITHUB_URL`, `PUBLIC_TWITTER_URL`, `PUBLIC_LINKEDIN_URL` and
`PUBLIC_TWITTER_HANDLE` values must be explicitly approved public metadata.
Empty values omit those links. They are build inputs, so changing them requires
rebuilding the frontend; no private biography is used as a build argument.

When starting containers and live provider calls are authorized:

```powershell
cd D:\MrBekoXBlogApp\docker
docker compose --env-file .env config --quiet
docker compose --env-file .env up -d --build --wait --wait-timeout 300
docker compose --env-file .env ps
```

The frontend listens on 127.0.0.1:3000 and the API on 127.0.0.1:8080 by default.
Both SignalR hubs connect to the API. PostgreSQL/cache/broker ports bind only
loopback. This local broker uses an explicit bootstrap identity with full
permissions; production instead uses separate backend/agent/topology roles.

Local volume names are preserved. PostgreSQL 18 keeps this file's historical
`/var/lib/postgresql/data` mount with explicit `PGDATA` at the same path; the
production file retains its different PG18 parent-directory mount. Before
changing an existing local PostgreSQL 18 installation, inspect its actual data
mount and make a backup. If data is in an anonymous or different volume, restore
it through a reviewed migration rather than creating an empty database.
Default broker credentials are seeded only for a fresh broker: changing `.env`
does not update a persisted user. Preserve the existing identity or rotate it
with RabbitMQ administration tools; never delete volumes to change credentials.
The named `agent_state` volume preserves worker checkpoints across replacement.

Agent migrations run before the API, whose own migrations/content sync then
start before the worker. `python -m app.healthcheck` inspects worker task health;
it does not send model requests. Observe model/index errors in the real logs.
Do not publish live keys, `.env`, broker definitions or database backups.
