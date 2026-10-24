# Deployment preparation validation

Date: 2026-10-24. Scope: prepare the complete application and real AI worker for
EC2 t3.micro, without deployment, registry publication or paid provider calls.

## Implemented behavior

| Requirement | Current implementation |
| --- | --- |
| Real embeddings | OpenAI `text-embedding-3-small`, 1536 dimensions; required credentials, bounded requests, cancellation, response validation and explicit failures |
| Persistent retrieval | PostgreSQL `real[]` vectors, content-addressed embedding cache, atomic revision replacement and persistent removal tombstones; migration `0006` |
| Remove simulated AI | Packaged fake providers, hashing embeddings, scripted AI eval/question datasets and dependent mock AI flow suites removed; deterministic algorithms, HTTP safety and real infrastructure checks retained |
| Worker lifecycle | Supervised task completion, heartbeat health, bounded pool shutdown, content consumer and initial snapshot projection, persistent checkpoints |
| Production bootstrap | Create-only administrator with concurrency/retry protection; startup content snapshot committed to the durable outbox before HTTP readiness |
| Private identity | Approved source copied byte-for-byte into an ignored private bundle; same bundle mounted read-only into API and worker, with request-local owner identity |
| Keep personal files private | Original and derived files excluded from Git and all Docker build contexts; no private source in image layers, registry artifacts or tracked configuration |
| Release preparation | Complete Compose stack, required secrets, image tags, migration ordering, broker identities, SignalR proxy, resource/profile gates and explicit operator scripts |

Profile JSON is source content and provenance. It never substitutes for the
embedding model. Runtime embeddings are real API outputs stored in typed SQL
arrays. The tracked example profile remains a schema/test input; production
preflight rejects it and requires the approved private runtime mount.

## Executed checks

| Check | Evidence |
| --- | --- |
| Python fast suite, Python 3.13 on WSL | **817 passed, 12 skipped**; paid/network checks explicitly disabled |
| Real Python PostgreSQL storage | **3 passed**; complete Alembic upgrade, `0006 -> 0005 -> 0006`, persistent tombstone/restart and vector-dimension constraint checks |
| .NET Release compilation | Passed; environment-specific appsettings excluded from publish; base appsettings retained |
| .NET brokerless suite | **259 passed** |
| Real .NET PostgreSQL checks | **21 passed**; administrator creation/preservation/concurrency/SQLSTATE 40001 retry, startup outbox commit and existing content guards |
| Frontend | **164 tests passed**, TypeScript check passed and production Next.js build passed |
| Deployment and profile gates | **13 passed**, including rendering actual Compose with nonsecret values; no Docker daemon or containers used |
| Operational scripts | Bash/workflow/Python syntax and PowerShell AST/public-input checks passed |
| Actual private bundle | Original bytes preserved; generic validator, exact Python reader/owner route and exact API reader CLI all passed without logging personal contents |
| Privacy/source checks | Private files remain ignored/untracked; real owner identity absent from tracked diffs and unignored new files; private paths excluded from build contexts |

Disposable PostgreSQL clusters were shut down after each run. During this local
preparation validation no application stack, EC2 deployment, image publication
or model API request was made. Subsequent GitHub publication and PR checks are
a separately authorized phase; they do not authorize application deployment.

## Explicit limits and later acceptance

- Docker Desktop's daemon was unavailable. Container image builds, Nginx runtime
  validation and a full container-stack smoke test were **not executed**.
- Actual OpenAI credentials, paid embedding quality, browser SignalR delivery,
  broker interruption recovery and EC2 workload acceptance remain later operator
  checks. The paid retrieval test is guarded by `AGENT_RUN_PAID_TESTS=1` and an
  isolated migrated test database; normal CI cannot trigger it.
- A t3.micro has 1 GiB RAM. The configured steady-service memory ceilings total
  1424 MiB, excluding the host and migration spikes. Preflight requires at least
  2 GiB encrypted-EBS-backed swap for this host class. Swap and offline checks do
  not prove acceptable latency or freedom from memory pressure; follow the real
  resource/CPU-credit acceptance gates in the runbook.
- Existing ImageSharp 3.1.12 produces five unique NuGet security advisories.
  They are not suppressed or represented as remediated. The repository's
  licensing hold is preserved: the vendor's patched
  [3.2.0 release](https://github.com/SixLabors/ImageSharp/releases/tag/v3.2.0)
  introduces license enforcement. Review that dependency decision separately
  before external production acceptance. PKCS was updated to the patched 9.0.21
  line and its prior warnings no longer appear.

Read `PRODUCTION_DEPLOYMENT.md` for the later operator sequence, including private
bundle transfer, UID/GID 1001 permissions, TLS, credentials, backups and acceptance.
Run `deploy.sh --check` for validation; applying or publishing is a separate,
explicit action.
