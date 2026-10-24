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

## Durable run budgets and recovery

Migration `0007` adds the PostgreSQL run budget and reservation ledger. Apply the
normal Alembic `upgrade head` step before starting this worker version. Startup
checks both ledger tables. Preparing this source change does not run migrations
on any server.

Production creates a budget store for the run and its current fencing token on
both fresh execution and checkpoint resume. The first limits remain pinned;
another process cannot create a fresh allowance for the same run. Reservations
are persisted before external work. An older attempt's outstanding reservations
become conservative `uncertain` charges; a stale or expired lease cannot refund
them. Recovery of a legacy attempt with no ledger exhausts its unknown allowance
instead of assuming it was free. The ledger stores counts, never prompts,
answers, credentials or private profile content.

The backend exposes provisional timeout state separately from answer content:
`isProvisionalTerminal`, `reconciliationUntil`, and server-computed
`reconciliationRemainingSeconds`. `AgentAcceptance:TerminalRecoveryGraceSeconds`
defaults to 300 (valid range 0-1800); Compose maps it from
`AGENT_TERMINAL_RECOVERY_GRACE_SECONDS`. A later terminal event can reconcile a
backend timeout only within that window. After it closes the backend preserves
the final decision and records the late event as stale. The browser performs a
final authoritative read, with bounded retries, rather than assuming its own
clock establishes the server's final state. Offline final verification is shown
as unknown and requires an explicit status check, never silent resubmission.

## Acceptance evidence

### Development sequence

The current phase is bug fixing and development, with offline regression tests,
isolated PostgreSQL/RabbitMQ checks and loopback browser fixtures. Model-backed
acceptance is deferred until development is complete; the planned first target
is local Ollama. No model server, model download or provider evaluation is
started as part of this phase.

The chat configuration accepts loopback HTTP endpoints, but actual Ollama SSE,
usage and generation/verifier behavior must be checked in that later phase. The
current full-pipeline runner intentionally retains the production embedding
model `text-embedding-3-small` and its 1536-dimensional index. Testing local
embeddings will require an explicit Ollama model/dimension choice and an isolated
index; existing vectors must not be relabeled or mixed with another model. A
local acceptance mode must be kept separate from paid-provider opt-in gates.
This records the planned work, not a claim that Ollama acceptance has passed.

These checks cover separate layers; passing one layer does not certify another:

| Layer | Evidence | External calls |
| --- | --- | --- |
| Contracts, guards, storage and races | Python/.NET regression suites and disposable PostgreSQL/RabbitMQ | Test infrastructure only |
| Real browser lifecycle | `npm run test:agent-browser` in the frontend | Loopback HTTP/WebSocket fixture only; external requests blocked |
| Grounding verifier quality | `python tools/evaluate_grounding.py --scope verifier` | Explicit paid-provider opt-in required |
| Generated answers and retrieval | `python tools/evaluate_grounding.py --scope full-pipeline` | Explicit paid opt-in plus dedicated disposable PostgreSQL and real embeddings |
| EC2 capacity and operational objectives | `tools/operational_acceptance.py` with measured target evidence | Tool itself sends no traffic and performs no deployment |

The browser runner uses an isolated temporary profile and build, does not load
developer dotenv files, and fails if Chrome is unavailable. It exercises real
React effects, Axios and the SignalR client, not the .NET hub's authentication;
backend WebSocket integration tests cover that layer separately.

The public quality corpus covers Turkish/English, paraphrases, role/relationship
reversals, numbers, negation, links and abstention. Checking the corpus makes no
provider request. Live evaluation must be separately authorized and opt in
through both the CLI and `AGENT_RUN_PAID_TESTS=1`; full-pipeline evaluation also
requires `AGENT_ACCEPTANCE_DISPOSABLE_DB=1` and a migrated loopback test database
whose name starts with `blogdb_agent_quality_test`. The runner does not discover
dotenv files and reports public case IDs, aggregate metrics and public fixture
outputs, never credentials or real profile text. Semantic verification remains a
fallible model judgment; exact segment coverage, source quotes, URLs and numbers
are also checked locally. It does not establish a universal truth guarantee.
Runtime generation is followed by bounded semantic verification using the same
configured chat provider. These are additional billable calls within the same
durable run budget. Unavailable verification budget yields abstention or a
partial result, never an unchecked answer presented as verified.

For a separately approved load scenario on the intended EC2 host, memory can be
sampled without starting services or sending requests:

```bash
python tools/operational_acceptance.py collect-memory --seconds 120 --output /tmp/agent-memory.json
```

Combine that measurement with terminal run durations/statuses and the existing
admin observations endpoint's outbox-age/dead-letter deltas. Keep this evidence
outside Git. Use one evidence file and product-approved thresholds per workload
(for example fast QA versus research). Assessment requires the measured commit,
a recent UTC timestamp, explicit target/load attestations and sufficient samples:

```bash
python tools/operational_acceptance.py assess --evidence /tmp/agent-live-evidence.json --policy /tmp/agent-slo.json --expected-commit <release-commit>
```

The policy explicitly supplies `max_p95_run_seconds`, `max_failure_fraction`,
`max_peak_memory_fraction`, `max_outbox_age_seconds`, `max_dead_letters`,
`minimum_runs`, and `minimum_memory_samples`. No latency or capacity target is
silently presented as an industry standard. Missing, stale, non-target or
different-revision evidence returns `not_measured` with exit code 2. Unit-test
samples and loopback fixtures cannot count as measured EC2 capacity. Real model
and EC2 acceptance remain pending until those authorized runs actually occur.

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
