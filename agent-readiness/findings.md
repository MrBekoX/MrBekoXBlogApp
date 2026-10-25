# Findings and decisions

Baseline: `fca834626560829420de9320978c96ad5c71d23d`. Prior analysis is a lead; current source and tests decide status.

| ID | Classification / confidence | Current evidence and decision |
| --- | --- | --- |
| F01 | Fixed P1 correctness, high | Real worker RED reproduced missing checkpoint/config_error. Initial execution now passes the store; restart/resume/backend-only completion and replay rejection pass. |
| F02 | Fixed after independent revision, high | Fresh review and `pg_terminate_backend` reproduced the filesystem/transaction race. Migration 0009 now commits opaque checkpoint bytes and ownership in PostgreSQL; legacy latest-only import cannot override DB authority. Real storage/connection-loss tests and a fresh migration round trip pass. QA/research graph nodes may replay; no exactly-once provider-call claim. |
| F03 | Fixed accounting gap, high | Raw uncached embedding batches reserve run tokens before HTTP; indexing has a separate immutable-source owner in migration 0008. Exact/estimated/uncertain charges and orphan reservations survive restart. This is not a global monetary cap across all article revisions. |
| F04 | Fixed capability-policy gap, high | Explicit token-parameter/temperature/stream-usage capabilities preserve existing defaults. Invalid combinations fail before HTTP. Real configured model compatibility and semantics still require authorized provider acceptance. |
| F05 | Wiring and local collector acceptance implemented, high | Optional bounded OTLP exporters, validated W3C command/event context, worker/model/embedding/tool/retrieval spans and content-free counters are tested. Retry callbacks, provider-span errors and admission rejections have distinct bounded metrics. Full live cross-service trace and deployment capacity acceptance remain open. |
| F06 | Offline coverage/provenance fixed; semantic acceptance open | Added 24 public TR/EN cases while preserving the approved paid corpus/bounds. Critic issues (actual intent/context, QA/golden hash, unknown usage and numeric overflow) are fixed. A final model-ID compatibility regression also preserves colon/slash IDs without relaxing other labels. Offline fixtures are not semantic quality evidence. |
| F07 | Implemented; local gates pass | CI uses both hash locks, no extra dependency resolution for editable install, pip check and blocking lint/typecheck/runtime advisory gates. Initial 8 lint errors and 9 further stricter Next errors were fixed without rule changes; final 0 errors/21 warnings, types/build/272 tests/Chrome acceptance pass. Prior 50 Python runtime pins preserved; additive OTel packages only. |
| F08 | Confirmed acceptance boundary, high | Browser harness uses loopback fixtures; .NET E2E does not execute Python/provider. Full-service acceptance requires separate approved environment. |
| F09 | Product/operations decision pending | No universal retention period is established. Keep active/resumable data; do not add destructive cleanup or call runtime migrations a vulnerability by themselves. |
| F10 | Updated from current source | Root/service README describes active real-provider/PostgreSQL composition, capability sources, recovery limits and actual commands. Staging/deployment claims are explicitly separate. |
| F11 | Resolved as explicit optional capability, high | Default production still has no structured project repository/article catalogue; honest partial unavailability is tested through production composition. Article/profile retrieval is a distinct supported source. No sample records or parsed narrative projects were invented. |

## Review record

- Runtime specialist and its independent worker independently confirmed F01 and F02 from current code.
- Integration specialist measured frontend checks and verified owner checks, strict input bounds,
  monotonic event cursor and authoritative terminal recovery already exist; these are retained controls.
- **S01, fixed auth lifecycle issue:** generated JWTs lacked issued-at metadata needed by the
  account-wide token-invalidation check. Real token → real middleware regression returned 200
  after account revocation (expected 401); individual JTI blacklist control passed. The precise
  claim casing was investigated separately and is not asserted as the sole cause. Standard issuance
  plus a signed precise timestamp and shared current-revocation policy now cover HTTP/hub/SSE;
  valid new login in the same second and legacy token controls pass.
- **S02, fixed stale SignalR/SSE content boundary:** admission checked owner/token at connection/join,
  but an already subscribed group could receive sensitive result/message after revocation. The UI
  treats notifications as replay/GET triggers. Retain authoritative owner/publication checks, send
  metadata-only notifications and revalidate invocation/expiry. Independent postpatch review found
  the SSE sibling; real HTTP tests reproduced revocation during query await, then passed after
  query/write-boundary checks. Passive revoked sockets can receive metadata hints; sensitive data
  requires fresh authorized GET/replay. Instant physical disconnect on every revocation is not claimed.
- Fresh .NET restore and successful Release build confirmed ImageSharp 3.1.12 remains selected and
  reports three high/two moderate NuGet advisories. The manifest records a license constraint on newer
  versions; security investigation must evaluate reachable upload guards and a compatible remediation.
- No formal repository-wide security scan has completed at this point. Focused security reviews, tools and
  coverage will be recorded explicitly.
- **F12, confirmed acceptance-tool defect:** authorized full-pipeline/all acceptance passes an injected
  HTTP client to the embedding adapter, whose constructor did not accept it. A focused actual acceptance
  path regression reproduced `TypeError`. The adapter now accepts a borrowed client, preserves its
  request-limit hooks, retains production budget-scope checks and leaves closing borrowed clients to
  their caller. The owning-client default remains unchanged; focused transport/eval checks: 106 PASS.
- **F13, fixed collaboration completion recovery:** a real worker/JobStore fault after a resolved
  checkpoint but before terminal SQL returned failed after reclaim. A typed local receipt is now
  retained only after backend-result validation. Inputless internal recovery rechecks claim, proposal,
  context, publication, deadline/cancel and receipt binding; normal public duplicate resume remains
  rejected. Real worker/DB recovery cases and existing collaboration/guidance controls pass.
- **F14, build-context hardening:** local ignored evidence/cache under `out/` was outside the Docker
  deny lists. The existing static context-policy test first failed, then passed after all three
  Dockerfile ignore files denied `**/out`. This is static policy evidence, not a live image scan.

## Evidence classification and rejected claims

- SignalR `access_token` query authentication was not present in the checked application; cookie
  authentication is the actual client/server path. That hypothesized credential-to-query-log chain
  was rejected. Raw query capture at Information logging was independently reproduced and removed
  from both rendered and structured logging; production default Warning is a separate boundary.
- ImageSharp advisories are package warnings, not proof that the named TIFF/ICC/histogram sinks are
  reachable through this application's admitted formats. Existing guards and regression tests remain.
- Node recovery, fixture browser acceptance, SDK collector tests and a successful migration round trip
  do not establish semantic quality, full-service approval behavior or production rollback/restore.
- Migration 0009 initially broke five fixture reset inventories: `TRUNCATE jobs` omitted its new FK
  child. Actual setup errors led to explicit `job_checkpoints` inclusion; no constraint/CASCADE/test
  waiver was used. The complete .NET suite passed 666 tests; final Python source passed 1261 with
  9 skips before the final metadata leaves, which have their own complete 54-test offline gate.

## Dependency review

- Python runtime advisory audit: 60 packages, no known vulnerabilities at query time.
- Frontend audit identified 16 affected production packages. Independent pre-patch review confirmed
  exposed App Router/Server Actions and current CSP/proxy paths. Selected compatible updates include
  Next 16.4.1, Axios 1.20.0, Zod 4.6.6 and Mermaid 12.2.0, with aligned Next ESLint and targeted transitive
  patches. Production framework/provider/database components are retained; package updates are targeted.
- Development tooling separately required Vitest 4.1.12: vendor documentation explicitly excludes
  3.x backports and its pinned internals could not accept compatible security patches. Independent
  review confirmed the node test configuration/API usage and direct Vite harness dependency; Vite
  7.3.7 is explicit, keeping the existing Vite major. The 272-test final gate passes on this graph.
  Final production and full/dev advisory inventories each retain only two moderate trusted-build
  selector-parser warnings; there are no current high/critical entries in those npm inventories.
- Current Next `images.unoptimized=true` blocks the image optimizer paths under the checked source
  configuration; it does not justify ignoring the other Next advisories or deployment drift.
- **Sanitizer artifact caveat:** both the old Mermaid bundle and inspected 12.2.0 release bundle embed
  DOMPurify 3.4.12. Updating the npm DOMPurify dependency alone does not patch those served bytes.
  Existing strict Mermaid mode, opaque-origin sandbox, token/source message checks and SVG-as-image
  sink prevent the investigated parent-DOM XSS paths; no exploitation of this concrete boundary was
  established. Keep these controls and record the embedded residue; do not claim it was fixed by a lock pin.
  A fresh final reviewer independently confirmed the same artifact identity. Parent disposition:
  retained affected library bytes are a documented maintenance warning; an application exploit was
  not validated under the current configuration/containment. No sanitizer-byte remediation or
  dependency-clean claim is made. A future rebuilt/upstream-patched browser asset needs its own
  provenance and both-delivery-mode browser acceptance; this draft is not production merge approval.
- Existing ImageSharp 3.1.12 library warnings remain visible. Independent investigation found the high
  TIFF encoder/HistogramEqualization paths outside the admitted PNG/JPEG/WebP processing path;
  medium BigTIFF/ICC advisories are checked against existing format/profile stripping guards. Do not
  suppress warnings or migrate to a license-enforced major without a product decision.
- The production image's existing isolated PEP517 backend can still resolve `setuptools>=68` during
  image build. Runtime pins and CI dev tooling are locked; full bitwise image/build-backend
  determinism was not certified. No image was published or production deployment validated here.
