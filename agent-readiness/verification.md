# Verification ledger

Date: 2026-10-25 (Europe/Istanbul). Baseline: `fca834626560829420de9320978c96ad5c71d23d`.
Commands below never authorize paid requests or production operations. Final revision is recorded after delivery.

## Final gate summary

Counts from focused suites overlap. Do not sum them into a fabricated total.

| Layer | Final actual evidence | Boundary |
| --- | --- | --- |
| .NET build/full suite | PASS: final Release build, 0 errors; **666/666 tests**, 6.63 minutes, exit 0 | Real PostgreSQL/RabbitMQ and actual HTTP/socket/projection; no Python/provider/browser chain |
| Python full suite | PASS: **1261 tests, 9 skips**, 387.09 s, exit 0 | Real DB/broker, including storage; paid/network opt-ins 0. Precedes only the model-ID metadata leaf below |
| Final metadata leaves | PASS: **54 offline/CLI tests**, 38.29 s, exit 0 | Colon/slash model IDs preserved; all other labels strict. Read-only Git probes also leave index bytes/mtime unchanged; no app/DB/broker change |
| Fresh migration/storage | PASS: **42 tests**, 25.24 s; `0009 → 0005 → 0009`, exit 0 | Brand-new embedded PostgreSQL; no production restore/downgrade claim |
| Collaboration completion recovery | PASS: **75 tests**, 23.96 s | 21 actual worker/JobStore/DB recovery cases; injected fault before terminal SQL, not an OS-crash claim |
| Retry/error/admission telemetry | PASS: **19 collector tests** / 8.30 s and **30 budget regressions** / 1.05 s | Actual SDK/OTLP protobuf collector; callback retry count differs from paid HTTP count |
| .NET focused security/telemetry | PASS: **46 tests**, 4.95 s; included in full suite | Actual JWT/HTTP/socket/collector, revocation-during-query and guest controls |
| Deployment/Compose/workflow | PASS: **22 tests**, 6.707 s | Final templates and static Docker context policy; no deployment |
| Canonical/corpus | PASS: manifest and approved 9-case corpus; 24 additional behavior cases | 0 provider calls; no semantic quality score |
| Frontend patched tooling | PASS: **272 tests /30 files**, 4.00 s; TypeScript; lint **0 errors/21 warnings** | All 9 stricter Next React lint errors repaired without rule/ignore changes; stale cache/deadline/manual-refresh regressions included |
| Production frontend build | PASS, Next 16.4.1/Turbopack, types enabled | Removed unsupported webpack-only CSS option; no source/type error ignored. Expected no-store routes remain dynamic; no production backend/provider acceptance inferred |
| Final Chrome agent fixture | PASS: **8/8** | Final source, real Chrome155, loopback API/SignalR fixtures; no live backend/provider |
| Final Chrome Mermaid | PASS | Actual component/route/document/CSP/bundle; empty/A/B/clear/same-A; source/token/opaque DOM guards; 0 external/canary/console errors. Not sanitizer-byte remediation or public deployment proof |
| Secret scan | PASS: Gitleaks 8.30.1, staged diff 673.67 KB, no leaks | No network/private-file mount; repeat after final staging; not full-history scan |
| Dependency audit | Python runtime **60/0**, dev **74/0** known vulnerabilities | Current advisory query, not proof against unknown vulnerabilities |
| .NET advisory inventory | Completed; five ImageSharp 3.1.12 warnings | Named sinks triaged against existing guards; library not called clean |

Source revision/PR and final frontend/CI results will be added at delivery. A task-owned npm process
was temporarily suspended during measured shared-host I/O pressure, then resumed and completed;
no process remains suspended. Global settings and existing virtual environment were preserved.

## Environment and ownership

| Check | Result | Evidence / boundary |
| --- | --- | --- |
| Initial Git tree | PASS | Clean tracked/untracked status; ignored private work preserved; no merge/rebase state. No AGENTS.md found in root/parent or repository search. |
| Remote/main | PASS | Authorized elevated `git fetch origin --prune`; HEAD, local main and fetched origin/main equal baseline. Feature branch created from origin/main. |
| Python Windows | BLOCKED | `py -3.13 --version` cannot find its registered executable. Existing `.venv` has Linux layout; it was not overwritten. |
| Python WSL | PASS | Existing `/mnt/d/MrBekoXBlogApp/src/services/ai-agent-service/.venv/bin/python --version`: 3.13.12. System python3 is 3.12.3 and is not used for service tests. |
| .NET / Node / npm | PASS | Actual commands: .NET SDK 10.0.400; Node v24.16.0; npm 11.13.0. |
| Docker / Compose | PASS environment | Client and daemon 29.9.2; Compose v5.6.1. Elevated access required; no running containers initially. |
| Chrome | PASS environment | Installed Chrome 155.0.8059.85; browser acceptance not inferred from version. |
| Context7 / Plan Mode | UNAVAILABLE | No matching tools. Official pages opened; written executable plan used. |
| Technical record path | PASS | `git check-ignore agent-readiness/spec.md agent-readiness/verification.md` returned no match (exit 1). No ignore rules changed. |

## Executed baseline gates

| Layer | Working directory / command | Result |
| --- | --- | --- |
| Frontend unit/fixture | `src/frontend/blogapp-web`: `npm test` | PASS, 29 files / 264 tests. |
| Frontend lint | same: `npm run lint` | FAIL baseline: 8 errors, 26 warnings; rules unchanged. |
| Frontend typecheck | same: `npx --no-install tsc --noEmit --incremental false` | PASS. |
| Python brokerless | service: existing WSL interpreter `-m pytest tests -q` with current CI infrastructure-directory exclusions, `AGENT_ENV_FILE=/dev/null`, paid/network opt-ins 0 | 988 PASS, 21 SKIP plus the newly added F01 regression failed correctly; that new test was collected during the baseline run, so this was not an immutable pristine-baseline measurement. |
| .NET build | root: `dotnet build src/backend/Presentation/Api.Tests/BlogApp.Presentation.Api.Tests.csproj -c Release --no-restore --nologo -v minimal` after fresh restore | PASS, 0 errors / 25 warnings, 55.86 s. Fresh restore confirmed existing ImageSharp warnings. |
| .NET brokerless | root: `dotnet test ... -c Release --no-build --nologo -v q --filter <exact current CI filter>` | PASS, 413 tests, 0 skipped, 46 s. |
| .NET full real infrastructure | root: `dotnet test ... -c Release --no-build --logger console;verbosity=minimal`, dedicated DB/broker | ABORTED, not PASS. 32 tests completed; then no progress. Managed stack contained async/test-runner waits. Only the verified task testhost was terminated after 11 m 13 s. Final rerun requires bounded no-dump hang diagnostics. |

## Implemented regression evidence

Counts below overlap; do not add them into a fabricated total. These are actual local runs,
not remote CI and not real-provider semantic acceptance.

| Requirement | RED | GREEN / layer |
| --- | --- | --- |
| R01 collaboration | Actual worker returned `failed/config_error` instead of `needs_input` (1 failed) | Worker/FileCheckpointStore continuation and durable-budget binding: 12 PASS. Restart, backend-result-only completion and repeated/foreign/stale approval rejection included. |
| R02 checkpoint fencing | Stale owner overwrite, then fresh critic reproduced connection-loss rollback gap | Migration 0009 stores authoritative bytes with job ownership in one transaction. Fresh 42-test storage gate covers connection termination, ordering, active guards, legacy import and missing-ID fallback denial. |
| R03 embedding admission | Reported usage absent from ledger and exhausted budget still issued HTTP (2 failed) | Reported/estimated/uncertain classification, exact cache-hit no-HTTP/no-charge and durable orphan reservation checks pass. Abrupt subprocess `os._exit(23)` leaves pending cost charged under the new fence. |
| R04 provider capabilities | Explicit output token key ignored; incompatible temperature/key accepted (3 failed) | Existing SSE/config/embedding transport suite: 82 PASS. Provider/model unchanged. |
| R05 trace propagation | Missing wire/worker parent, then retry/admission counters absent | Real SDK/OTLP collector privacy/context/failure checks pass. Current Python 19 collector +30 budget tests and .NET 46 focused tests; full live cross-service collector acceptance remains separate. |
| R06 dataset | Missing coverage, actual intent/provenance mismatch, unknown usage/overflow and model-ID rejection | Revised 53-test offline/CLI gate passes. 24 public cases/12 subsets × TR/EN; model and golden source identities bound, missing values remain unknown. Semantic quality unmeasured. |
| R11 optional sources | Missing project repository returned failed/config_error (2 failed) | Guidance/composition tests now require honest partial availability, without invented sources. Broader runtime subset: 224 PASS. |

## Additional executed gates

| Layer / command | Actual result / boundary |
| --- | --- |
| Clean hash environment | WSL Python 3.13.12 at `/tmp/mrbekox-readiness-ci-20261025/bin/python`; two hash locks installed together, editable `--no-deps --no-build-isolation`, `pip check`: PASS. Previous 50 runtime pins preserved; additive OTel SDK/exporter packages only. Existing `.venv` untouched. |
| `tools/verify_storage.py`, clean interpreter | Earlier 17-test snapshot passed; final fresh cluster 42 tests and `0009 → 0005 → 0009` passed. Old venv attempt was BLOCKED by incomplete embedded-postgres, not a behavioral RED. A Docker-target downgrade was rejected by automatic review and never run; the safer brand-new embedded cluster completed the authorized migration gate instead. |
| Full Python, clean interpreter | PASS 1261/9 skips with paid/network opt-ins 0 and explicit dedicated DB/broker overrides; no `docker/.env` discovery. A prior stopped attempt exposed 72 fixture setup errors (new FK omitted from explicit reset lists); five lists were corrected without CASCADE/constraint/test changes. |
| Canonical manifest | PASS (`manifest tutarli`), no provider calls. |
| Existing grounding corpus | PASS, 9 cases, 0 provider calls; new dataset separately verified by evaluator tests. |
| Browser fixture acceptance | Final source PASS, real Chrome155, 8/8 scenarios: normal, lost terminal GET, reconnect, research restoration, provisional recovery/clock skew/expiry/final offline. Additional actual Mermaid component smoke passes. These are loopback fixtures, not live backend/provider. |
| `python -m unittest discover -s deploy/tests -v` | Final PASS, 22 tests, 6.707 s. Existing Docker context policy first failed for local `out/`; all three image deny lists now exclude it. Static policy evidence, not a live image scan. |
| Python advisory audit | `uv tool run --from pip-audit==2.10.1 pip-audit --disable-pip --no-deps -r requirements.lock --format json`: PASS, 60 dependencies, no known vulnerabilities at query time. Does not prove absence of unknown vulnerabilities. |
| Python dev advisory audit | PASS, 74 dependencies, no known vulnerabilities at query time. |
| Python SAST | Bandit 1.9.4 on `app tools`: raw exit 1, 0 high/96 medium/33 low, 27,728 LOC at the delivery scan, no skipped checks or new suppressions. Source triage: 95 SQL-template flags use validated identifiers and bound data; enum token labels are not credentials; heartbeat is container-local; assertions follow enforced invariants; telemetry exception isolation preserves outcomes; CLI subprocesses use fixed argument arrays without shell evaluation. This is scoped triage, not a clean raw scan or whole-stack certification. |
| Frontend dependency audit | Final production and all/dev graphs each show 0 high/critical, 2 moderate. Production blocking high/critical gate exits 0; full raw audit exits 1 for the trusted-build selector-parser warnings, documented with vendor reachability. Next16.4.1, Axios1.20.0, Zod4.6.6, Mermaid12.2.0, Vitest4.1.12/Vite7.3.7 and targeted compatible transitive patches installed without force/peer overrides. |

Dedicated targets: PostgreSQL 18.6 on loopback 25432. Initial Docker-backed broker vhost stopped
with `reopen_for_writes` timeout; shared-host `IO/WalSync` waits were measured. Final successful
suites used the same pinned RabbitMQ 4.3.6 on 35672/35673 with a task-owned durable WSL bind path.
No fsync/durability setting was relaxed. Images are immutable CI digests, with task labels and no production mounts.
DB/vhost fixtures are disposable; .NET and Python broker suites run serially.

Final .NET command uses Release `--no-build`, normal console + TRX output, and
`--blame-hang --blame-hang-timeout 10m --blame-hang-dump-type none`. Final Python command is
`-m pytest tests -q --maxfail=1 --durations=10 -o faulthandler_timeout=180`; an explicit storage DB URL
includes real storage tests. Fail-fast would fail the gate; the successful run executed every case.

Code review used runtime, integration and quality specialists with bounded worker/critic waves under
four slots. Fresh independent reviews found the cross-resource checkpoint race, acceptance-client
constructor mismatch and SSE sibling boundary; all were reproduced before repair. Query-token auth
support was rejected as absent, claim casing was not asserted as the sole JWT cause, and raw query
capture was fixed at its actual Information-log boundary. No formal repository-wide scan is claimed.

## Acceptance layers kept separate

Static review, unit/contract/fixture, real PostgreSQL/RabbitMQ, browser with fixtures, real provider,
full-service acceptance and deployment/capacity will each receive their own final status. No real
provider request, staging operation or deployment has been run. Paid acceptance is BLOCKED without
an explicit operation-specific budget. Deployment/capacity is BLOCKED without an approved target and scenario.
