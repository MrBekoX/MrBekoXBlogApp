# Configuration

`app/service_main.py` composes the production worker from environment settings.
The service-local `.env` loader fills missing environment variables only. See
`../.env.example` for the full settings list and defaults. The deployment stack
sets the environment explicitly; secrets belong in an untracked environment file
or the host's secret configuration.

## Providers

Chat completion requires `AGENT_LLM_API_KEY` and `AGENT_LLM_MODEL`. The optional
`AGENT_LLM_BASE_URL` selects an OpenAI-compatible chat endpoint. The worker refuses
to start when required provider settings are missing or malformed.

Embeddings use `text-embedding-3-small`, 1536 dimensions, and the independent
`AGENT_EMBEDDING_BASE_URL` (default `https://api.openai.com/v1`). Set
`AGENT_EMBEDDING_API_KEY`, or reuse `AGENT_LLM_API_KEY` for OpenAI. The batch size is
bounded to 32 to limit request memory on a small host. Provider failures remain
explicit failures; they do not fall back to locally generated substitute vectors.

Profile JSON and manifests are canonical input content and version metadata.
Message JSON schemas describe contracts. Neither format implements an embedding
model. Model identifiers, source revisions, and content hashes isolate persisted
vectors from incompatible source versions.

## Budgets and retrieval

`BudgetProfile` is server-owned. Calls reserve capacity before execution and
commit actual usage afterward. Model output cannot increase limits. Content
chunking and retrieval context limits bound the worker's input and memory use.

The EC2 production configuration limits worker concurrency, broker prefetch, and
database connection pools. Those limits must be considered together with the API,
frontend, PostgreSQL, RabbitMQ, and reverse proxy on the same host. Resource
settings are preparation; actual EC2 peak memory use requires a runtime check.

## Web tools

`WebToolSettings` controls response sizes, allowed ports, redirects, DNS
resolution, and timeouts. Private, loopback, link-local, and metadata destinations
are blocked in production. The loopback setting is restricted to local HTTP
transport safety tests. Research needs a configured search endpoint; unavailable
search is reported as a configuration error.

## Optional deep research

Set `AGENT_WEB_SEARCH_URL` to a public HTTPS search-normalizer endpoint. Its
contract is `GET ?q=<query>&count=<limit>` returning
`{"results":[{"title":"...","url":"https://...","snippet":"..."}]}`.
An optional `AGENT_WEB_SEARCH_API_KEY` is sent as a Bearer credential to that
endpoint only; fetched source pages never receive it. Credentials, query strings
and fragments are not allowed in the configured URL. Production SSRF checks and
response/time limits apply to search and source reads.

The production worker binds fresh research tools to each run's budget. Without
this configuration, deep research fails explicitly with `config_error` before
calling the model; it never returns a report pretending to have read an article
or searched the web. Fast article QA and analysis remain available. Model drafts
in these article flows are checked before any answer text is published. Numeric,
negation and literal-identifier checks are conservative heuristics, not a claim
of perfect semantic validation; unsupported segments are omitted or the answer
abstains.

The production server defaults to 24 internal retrieval attempts, up to 12 source
pages and, only when search is configured, 8 searches. `AGENT_MAX_TOOL_CALLS` and
`AGENT_MAX_WEB_SEARCH_CALLS` configure these ceilings, including zero to disable
external research. A zero external budget is never rounded up; internal bounded
article retrieval does not grant permission to search or fetch external pages.

Chat token accounting includes the system message, prompt and bounded output.
When a provider omits usage, conservative estimates are marked as estimates.
This is not a currency cap across all providers: separately billed embedding
requests have their own bounded input/batch sizes and persistent cache.

## Checkpoints and compatibility

`FileCheckpointStore` stores opaque checkpoint payloads with atomic replacement
and fsync on the worker's persistent volume. It assumes one host and one worker
process. Checkpoint envelopes bind the execution identity and source revisions;
incompatible versions are rejected explicitly. See `state-schema-versions.md`.

## Verification

CI runs deterministic configuration, schema, policy, filesystem, chunking, and
HTTP safety checks. Separate infrastructure checks use real PostgreSQL and
RabbitMQ. No scripted AI provider or generated offline agent-quality evaluation
is shipped. A live embedding/chat acceptance run must be performed separately
after supplying real credentials; it is not implied by a passing static suite.
