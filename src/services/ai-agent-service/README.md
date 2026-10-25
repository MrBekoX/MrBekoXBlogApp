# AI agent service

The Python 3.13 worker consumes blog agent jobs from RabbitMQ, retrieves verified
blog and profile content, and publishes run events to the .NET backend. Chat
completion uses the configured OpenAI-compatible model. Embeddings use OpenAI
`text-embedding-3-small` with 1536 dimensions.

The production composition lives in `app/service_main.py`. Model credentials,
database access, and the backend content service must be configured before
starting it. Missing credentials are configuration errors; no synthetic model
response or hashing embedding is substituted.

## Configuration

Copy `.env.example` to a local `.env` and fill its required values. Never commit
that file. Process environment values take precedence over `.env` values. The
loader searches only up to this service's root; `AGENT_ENV_FILE` can select an
explicit file independently of the working directory.

Required provider settings:

| Variable | Purpose |
| --- | --- |
| `AGENT_LLM_API_KEY` | Chat completion API key |
| `AGENT_LLM_MODEL` | Explicit chat model identifier |
| `AGENT_EMBEDDING_API_KEY` | Embedding API key; defaults to `AGENT_LLM_API_KEY` |
| `AGENT_EMBEDDING_MODEL` | `text-embedding-3-small` |
| `AGENT_EMBEDDING_BATCH_SIZE` | Embedding request batch size, at most 32 |
| `AGENT_DB_PASSWORD` | Password for the worker's PostgreSQL connection |
| `AGENT_CONTENT_BASE_URL` | Backend internal content API |
| `AGENT_CONTENT_SERVICE_KEY` | Shared key for the internal content API |

Chat capabilities are explicit: `AGENT_LLM_OUTPUT_TOKEN_PARAMETER` selects
`max_tokens` (the existing default) or `max_completion_tokens`;
`AGENT_LLM_SUPPORTS_TEMPERATURE` and `AGENT_LLM_STREAM_USAGE` default to `true`.
Choose them from the actual endpoint/model documentation. Unsupported requested
temperature or an invalid token parameter fails before HTTP; model names never
silently switch providers or APIs. Transport tests do not certify a configured
third-party model's semantic or parameter compatibility.

Run token admission covers chat and uncached query embeddings. Content indexing
has a separate durable owner for each article revision/hash and embedding model.
`AGENT_CONTENT_SYNC_MAX_EMBEDDING_TOKENS` defaults to 1,048,576 and
`AGENT_CONTENT_SYNC_MAX_EMBEDDING_REQUESTS` to 2,177, derived from the existing
input byte/split bounds. These are engineering limits, not monetary targets.
Limits are pinned on first reservation; raising configuration does not replenish
an existing owner's allowance. Apply migration `0008` before the new worker.
Reported, estimated and uncertain usage stay distinguishable in the ledger;
pending/uncertain calls retain admission cost after retries or crashes.

Embedding usage is separate from the existing wire chat `UsageRecord`; it is
available through the ledger and content-free telemetry. A cache hit does not
issue or charge a new embedding request. Indexing limits are per source version,
not a global account spending limit across arbitrarily many authorized edits.

The embedding endpoint has its own `AGENT_EMBEDDING_BASE_URL`; it does not inherit
the chat provider's base URL. Configure a separate embedding key when the chat
provider does not support the OpenAI embedding API.

Canonical author profile JSON contains versioned source content and provenance.
It remains an input to retrieval and citation validation. It does not provide
embedding vectors or replace the embedding model.

Real profile preparation stays private. The generic `deploy/profile_bundle.py`
tool preserves approved Markdown bytes and builds a Git-ignored bundle; both
services mount that same bundle read-only at runtime. Never put personal source
or generated profile files in Git, build contexts, image layers or registries.
Run `python tools/verify_profile.py /absolute/private/profile-directory` for an
offline check of the worker's exact profile reader and request-local owner route.

For the complete production stack and resource limits, see
[`deploy/PRODUCTION_DEPLOYMENT.md`](../../../deploy/PRODUCTION_DEPLOYMENT.md).
Preparing the files does not start the stack or call the provider.

## Local setup and checks

From this directory, using a Python 3.13 environment:

The dev/storage hash lock is validated on Linux/WSL, matching CI. A native
Windows Python installation was not verified; keep Windows and Linux virtual
environments separate and use the actual working interpreter path.

```bash
python -m pip install --require-hashes -r requirements.lock -r requirements-dev.lock
python -m pip install --no-deps --no-build-isolation -e .
python -m pip check
python -m pytest tests -q \
  --ignore=tests/messaging_broker \
  --ignore=tests/intake \
  --ignore=tests/events \
  --ignore=tests/worker \
  --ignore=tests/control \
  --ignore=tests/content_sync \
  --ignore=tests/integration
python ../../content/author-profile/tools/update_manifest.py --check
```

For real PostgreSQL migration and storage checks without Docker or model calls:

```bash
python tools/verify_storage.py
```

The runner creates a disposable local PostgreSQL cluster, applies the complete
Alembic chain, checks persistent removal/restart behavior and vector constraints,
then verifies the new migration's downgrade/upgrade. It does not simulate an AI
provider or certify semantic answer quality.

Paid provider acceptance is separate and opt-in. After the owner authorizes real
calls, provide a **dedicated migrated test database**, provider keys and set
`AGENT_RUN_PAID_TESTS=1`, then run
`python -m pytest tests/live/test_openai_semantic_retrieval.py -q`.
Normal test runs skip it. It creates real vectors and checks index persistence,
article scoping and removal. Use test database credentials, never production.

Production SQL storage uses typed `real[]` vectors and bounded article-scoped
cosine/BM25 retrieval. A search loads at most 512 chunks; larger scopes are
rejected explicitly to protect the small worker's memory. Large source chunks
are split into bounded real OpenAI requests and their vectors are pooled; no
synthetic vector fallback exists.

The fast checks exercise real configuration validation, model and wire schemas,
filesystem checkpoints, input policies, content chunking, and citation rules.
Local HTTP tests exercise HTTP parsing and SSRF checks without calling an AI
provider. Synthetic agent providers, scripted agent acceptance harnesses, and
their generated evaluation reports have been removed.

The infrastructure suites require actual PostgreSQL and RabbitMQ instances and
their documented test credentials. Run those serially against disposable test
databases and vhosts. They are not provider acceptance tests. External web checks
require `AGENT_RUN_NETWORK_TESTS=1`.

After configuring credentials and infrastructure, apply migrations and start the
worker:

```bash
python -m alembic -c migrations/alembic.ini upgrade head
python -m app.service_main
```

Running these commands starts real services and can make billable provider
requests once jobs arrive. Provider quality and EC2 memory capacity require live
validation after deployment credentials are supplied.

## Internal interfaces

`prepare_and_route`, `execute_plan`, and `resume` are the worker's core entry
points. A routing decision is retained through checkpoint continuation. The
backend validates article revisions, profile snapshots, permissions, and action
approval; clients communicate with the backend and its SignalR stream.

See `docs/entry-points.md`, `docs/port-contracts.md`,
`docs/configuration.md`, and `docs/state-schema-versions.md` for interface details.

## Capabilities and recovery boundaries

| Intent | Production source | Availability |
| --- | --- | --- |
| Article QA / analysis | Backend-authorized published article snapshot and PostgreSQL retrieval | Requires matching article revision/hash and configured real providers |
| Who am I / profile | Pinned canonical profile snapshot and provenance | Requires the approved mounted source; no web tools are supplied |
| Research | Article evidence plus explicitly configured restricted web tools | External search is unavailable without its provider; budgets/deadline still apply |
| Collaboration | Durable checkpoint plus backend-validated approval/action result | `needs_input` persists across worker restart; the agent cannot validate its own action |
| Project guidance | No structured project repository is wired by default | Returns honest partial/unavailable guidance; no invented project records |
| Content suggestion | No article catalogue is wired by default | Returns a partial availability response; article QA retrieval is a separate capability |

After migration `0009`, production checkpoint payloads and their job fence checks
commit in the same PostgreSQL transaction, including lease/deadline/cancellation
checks. A DB connection loss cannot commit an old filesystem mutation after a
newer owner. Existing file checkpoints are a legacy import source; after DB
authority starts, later legacy files cannot override it. Drain/quiesce old
file-writing workers before the first import. Custom/local worker injection
must provide the same guarded factory to claim this guarantee. Job recovery is
bounded at-least-once execution: research/QA graph nodes may run again. Durable
cost admission and backend action idempotency do not make provider calls exactly once.

## Optional telemetry and evaluation

Set `AGENT_OTEL_ENDPOINT` to a full OTLP/HTTP `/v1/traces` endpoint to enable
standard OpenTelemetry trace and metric exporters. Metrics use the sibling
`/v1/metrics` path. Empty disables export. `AGENT_OTEL_TIMEOUT_SECONDS` defaults
to 1 and accepts 0.1–10 seconds. Queues, timeout and shutdown are bounded; export
failures do not change agent outcomes. W3C trace parentage passes through versioned
envelopes. Prompt/profile/answer/auth content is excluded; metric dimensions do
not contain run, conversation or trace IDs. GenAI fields follow the development
conventions documented in the readiness specification, not a stability guarantee.

```bash
python tools/evaluate_grounding.py --check-corpus --scope all
# Assess bounded observations captured separately; this makes no provider call.
python tools/evaluate_grounding.py --readiness-results /path/to/observations.json
```

The approved nine-case paid corpus remains separately bounded. The additional
24-case TR/EN readiness dataset validates schema/coverage offline and can assess
explicitly supplied observations; it does not execute those cases or infer live
quality from labels. Reports distinguish missing measurements and record dataset,
prompt and commit identities. No model judge has been human-calibrated here.

See the repository [specification](../../../agent-readiness/spec.md),
[findings](../../../agent-readiness/findings.md) and
[verification ledger](../../../agent-readiness/verification.md) for current proof
and open real-provider/full-service/deployment acceptance.
