# Execution plan

Baseline: `fca834626560829420de9320978c96ad5c71d23d`; branch `codex/agent-industry-readiness`.
Scope and Given/When/Then acceptance are in [spec.md](spec.md).

## Order and file ownership

1. **Phase 0:** root owns Git and environment evidence. Preserve all local/ignored user files;
   fetch, compare main and create a feature branch. Run safe baselines before fixes.
2. **Phase 1:** root owns the five `agent-readiness/` records. Runtime specialist maps
   worker/provider/checkpoint/budget/composition. Integration specialist maps API/contracts/UI/CI.
   Specialists dispatch bounded worker and independent critic roles in waves: four total slots.
3. **Phase 2:** runtime specialist owns `app/messaging/worker.py` and collaboration regression tests.
   Record genuine behavioral RED through the worker, then connect the checkpoint and verify continuation.
4. **Phase 3:** runtime specialist owns provider/budget adapters and focused tests. Lock capability,
   uncertain-usage and cache/retry policy before changes. Preserve durable ledger and terminal fencing.
   Add migration `0008` for content-indexing budget ownership/reservations, separate from run-job
   fencing. The runtime specialist is its only writer. Key ownership to the actual article revision,
   content/model identity; preserve unresolved charges across retries/restart. Limits derive from
   existing bounded input/request policies and are documented as engineering bounds, not money SLOs.
   Final independent review reproduced a second checkpoint race: terminating the guard's PostgreSQL
   backend releases its row lock before a paused filesystem write ends. A file write cannot roll back
   with its database transaction. Replace production write authority with an additive `0009` job
   checkpoint table (opaque payloads, job FK, ordered write version and latest lookup). Keep the
   custom checkpoint port and existing volume as a legacy import source. New writes and ownership
   checks commit in one PostgreSQL transaction; after import, legacy files cannot override DB state.
   The runtime specialist assigns one writer for store/migration/tests; independent design review,
   the connection-loss RED/GREEN, legacy import and downgrade/upgrade are required before acceptance.
   Root coordinates disposable PostgreSQL/RabbitMQ, with infrastructure suites run sequentially.
5. **Phase 4:** quality specialist/worker extends the existing corpus and evaluator, preserving paid opt-ins.
   A critic checks corpus independence, metric definitions and limits. No paid call is authorized.
6. **Phase 5:** security specialist performs bounded source-to-sink review and a separate independent critic.
   Root records retention ownership and unresolved product policy. Fix only verified reachable issues;
   use appropriate security skills rather than describing routine review as a formal scan.
7. **Phase 6:** integration specialist owns frontend and API/contract changes only after an explicit file
   handoff. Verify existing owner, publication, replay, approval and recovery protections.
8. **Phase 7:** operations specialist owns trace propagation and operations checks after runtime file handoff.
   New dependencies/lock changes have one writer, the integration specialist, until handed back.
9. **Phase 8:** integration specialist owns `.github/workflows/ai-agent-ci.yml`, separate dev hash lock,
   dependency installation parity and the measured frontend lint debt. Keep action SHAs and least privilege.
10. **Phase 9:** root updates README from final composition, runs required gates and reviews the exact diff.
    Commit task files only. Push the feature branch; use the GitHub connector for a PR when gates allow.
    Environment-only live gaps permit a draft PR; a failing executed test does not.

Each behavior change follows spec → independent critic → RED → smallest fix → GREEN → independent
review. Record actual commands and counts in [verification.md](verification.md). Do not manufacture
tests for documentation or claim environment failures as behavioral RED.

## Compatibility and recovery

Changes preserve public APIs and active wire schema versions. Migration `0008` is additive and does
not rewrite run ledgers or existing checkpoints. Test upgrade from the prior head, constraints,
duplicate/concurrent reservations and downgrade/upgrade on disposable PostgreSQL before accepting it.
An older application can run with the added tables left in place; prefer application rollback with
schema retained. A schema downgrade deletes indexing accounting, so it is a disposable-test operation
only unless an operator explicitly approves a backed-up data-loss plan. Existing stored checkpoints
remain readable. Revert an application commit to roll back additive wiring/CI changes;
redeploy through the normal reviewed process, never from this task without authorization. Budget
accounting changes must preserve reservations on uncertain outcomes; do not delete ledger rows to recover.
If a schema change becomes necessary, revise this section before implementation and test roll-forward
as well as downgrade on disposable PostgreSQL.

Migration `0009` moves production continuation authority into the database. An old application cannot
resume newer DB-only state from a stale file volume. Prefer roll-forward, retain the new checkpoint
adapter when rolling back unrelated application changes, or drain/quiesce runs and use an explicitly
approved backup/export/recovery procedure. Never automatically downgrade/drop DB checkpoints or
represent a disposable schema round trip as production continuation rollback validation.

## Exit gates

- Unit/contract/fixture tests, frontend lint/typecheck/build, .NET build and brokerless tests.
- Real PostgreSQL migration/storage checks and dedicated real broker suites when available.
- Real browser fixture acceptance identified separately from real full-service acceptance.
- Canonical manifest, offline dataset validation, deployment/workflow checks, diff check and review.
- Secret scan, dependency audit/SAST and independent final security review with real tool results.
- Real provider/full-service/deployment acceptance remain open without explicit permission/budget/target.
- Check CI/review against the pushed PR HEAD. Human merge approval is required; local main stays unchanged
  until a merge is both approved and completed.
