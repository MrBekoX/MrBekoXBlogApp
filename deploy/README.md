# Production release preparation

This directory defines the complete blog stack: PostgreSQL 18, Redis, RabbitMQ,
.NET API, Python AI worker, Next.js and Nginx, plus two one-shot setup jobs.
Preparing these files does not deploy anything. Actual credentials remain empty
in `.env.example`; `deploy.sh` validates only unless `--apply` is passed.

Read [PRODUCTION_DEPLOYMENT.md](PRODUCTION_DEPLOYMENT.md) for the EC2 runbook and
[DOCKER_HUB_DEPLOYMENT.md](DOCKER_HUB_DEPLOYMENT.md) for release image preparation.

## Runtime behavior

- OpenAI `text-embedding-3-small` always supplies real 1536-dimensional embeddings.
- The LLM is external and selected through `AGENT_LLM_MODEL`; there is no mock mode.
- Agent state and real embeddings are persisted in the existing PostgreSQL database
  under the Python-owned `agent` schema. A separate vector database is unnecessary.
- API, web and worker images share one explicit `RELEASE_TAG`, including migration
  code from that checkout. Production profile data is supplied separately through
  one private host directory, mounted read-only into both API and worker.
- Private author-profile/source files never enter Git, Docker build contexts,
  images or registries. The tracked sample bundle serves development/tests only.
- Worker checkpoints use the persistent `deploy_agent_state` volume so an
  awaiting-input run can resume after container replacement. Include it in backups.
- Python Alembic migrations finish before API/worker startup. The API applies its
  own EF migrations; the two migration chains own separate schemas.
- Backend, worker and topology provisioning use different RabbitMQ identities.
  No broker, database, cache or worker port is published to the internet.
- Nginx handles both SignalR hubs and blocks the internal content API at the edge.
- The worker requires real provider credentials and supervised task health. Its
  health check does not call a paid provider. Actual model quality and indexing
  acceptance require the later authorized live checks in the runbook.

## EC2 t3.micro boundary

A t3.micro has 1 GiB RAM. This stack's steady-service memory ceilings total
1424 MiB, excluding the host and short-lived migrations. The ceilings are maximum
budgets, not measured consumption. **An unswapped 1 GiB deployment is rejected.**
The runbook requires at least 2 GiB encrypted-EBS-backed swap, prebuilt amd64
images, bounded queues/concurrency and observation under the actual workload.
Swap allows memory pressure to be handled; it does not prove acceptable latency.
If the acceptance limits fail, increase instance memory or move infrastructure
off-host before exposing the service. No successful t3.micro runtime measurement
is claimed by this preparation.

## Files

| File | Purpose |
| --- | --- |
| `docker-compose.prod.yml` | Full runtime stack and migration/startup ordering |
| `.env.example` | Empty required secrets and explicit model/release selection |
| `preflight.py` | Secret-safe configuration, private-bundle and Linux resource gate |
| `profile_bundle.py` | Shared source/hash validator and private bundle preparation |
| `deploy.sh` | Default read-only validation; explicit apply/backup/health sequence |
| `deploy-to-hub.ps1` | Three local image builds; registry push is opt-in |
| `rabbitmq-definitions.py` | Salted password hashes and broker role permissions |
| `rabbitmq.conf` | Boot import, absolute memory watermark, bounded channels |
| `nginx.conf` | Domain-templated proxy and SignalR upgrades/streaming |
| `tests/test_preflight.py` | Offline validation of release rejection conditions |

The existing external `deploy_postgres_data:/var/lib/postgresql` and
`deploy_redis_data` names are preserved. Never remove volumes to make an upgrade
pass. Existing installations must back up successfully before migration.
