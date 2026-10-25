# Working lessons

- A visible interpreter launcher did not imply a working runtime → executed a real version command,
  found the existing WSL 3.13 environment → use the full tested interpreter path and never overwrite
  a Linux virtual environment from Windows.
- Sandbox workspace write access did not include `.git`, WSL or the Docker daemon → ordinary access
  failed, authorized elevated read/fetch operations succeeded → distinguish sandbox access from a
  missing runtime/service, and do not report a safety reviewer rejection when none occurred.
- A worker guessed `budget/ports.py`, which does not exist → located `budget/store.py` and `models.py`
  with `rg --files` → discover paths before reading; a missing file is not a behavioral test failure.
- A root `rg` invocation passed a PowerShell wildcard as a literal path → search the directory with
  `-g '*.csproj'` instead → use rg glob arguments rather than assuming shell glob expansion.
- A worker's variable-containing Windows→WSL command lost the intended temporary venv target →
  Python generated a venv in the service root and replaced its tracked `.gitignore` → stopped the
  install, restored the exact HEAD ignore content with a patch, and removed only verified new
  generated files within the resolved service boundary. Re-run with a literal absolute `/tmp` target,
  no shell variable interpolation, and inspect Git state before proceeding. Existing `.venv` was preserved.
- A proposed ignore exception was based on that generated venv `.gitignore` → independent critic
  exposed the symptom, ownership investigation identified the cause → restore source rather than
  add a rule for accidental generated state; the dev lock is naturally unignored.
- TypeScript `satisfies` inside a parent object did not isolate schema.org contextual excess-property
  checks → use an explicitly typed intermediate SearchAction value → run noEmit alongside lint.
- Child tool sessions did not survive a handoff/turn as reusable parent handles → unknown process
  IDs could not establish gate results → finish the gate before returning and also write long
  command output to a task-owned ignored log; never infer PASS from an absent process or build file.
- The browser harness was assumed to share `.next` with the production build → source review showed
  Vite and an OS-temporary output directory → read the actual harness before imposing a sequencing constraint.
- A fixed `01` trace flag expectation rejected the SDK's valid `03` flags → compare preserved SDK
  flags and test unsampled propagation separately → do not confuse test assumptions with production defects.
- A checkpoint race harness used a two-second completion watchdog → real DB latency exceeded the
  watchdog while the ordering assertions held → use ten seconds for test cleanup/completion while
  preserving the stale-writer/row-lock functional assertions.
- Readiness corpus test development initially used an overly specific availability-message assertion →
  correct it, then record RED only for the confirmed status mismatch; do not count faulty assertions as product bugs.
- Concurrent edits during a running focused suite created mixed observation-schema snapshots → freeze
  the owned files before the final run and rerun the affected suite after any revision.
- A DB row lock was assumed to fence a later filesystem write → terminating that DB connection
  released the lock while the old file write could still complete → commit authoritative checkpoint
  bytes and ownership in the same database transaction; test connection loss before and after SQL.
- Adding the checkpoint FK omitted five explicit integration-fixture reset lists → the full suite
  reported setup errors although isolated storage tests passed → inventory all `TRUNCATE`/cleanup
  dependencies with every migration and include the child table explicitly without weakening FKs.
- Minimal console output and shared-disk latency were mistaken for a proven test hang → later verbose
  runs showed slow successful topology/restart cases → diagnose the active case first, serialize heavy
  install/storage workloads, and use a bounded no-dump watchdog rather than infer PASS or deadlock.
- A completed npm install was followed by an unnecessary retry because a failed stop check was not
  used to gate the next mutation → stop the extra task-owned process and restore the exact tree from
  the completed cache → branch explicitly on each dependent command's exit before another mutation.
- A stale zero-byte Git index lock blocked staging → verified its old timestamp, absence of Git
  processes and absence of an open handle before removing only that lock → never remove an active
  lock or use reset/clean as a substitute for ownership diagnosis.
- A read-only evaluation identity probe used Git's optional index refresh → a temporary-repository
  regression proved index bytes/mtime changed after a content-preserving touch → use
  `--no-optional-locks` for both Git reads; global configuration remains unchanged.
- SDK XML documentation listed members that were not publicly callable → actual compile rejected
  them → use supported public configuration plus tested export privacy processing; documentation
  presence alone is not API availability proof.
- OTel configuration validation executes during host composition as well as startup → a negative
  test caught too narrow a boundary → cover both build/start without relaxing expected rejection.
- A Git-ignored evidence directory was still eligible for Docker context transfer → add a separate
  Docker deny rule and static context-policy regression → Git ignore is not a build-context policy.
- Updated Next tooling found additional call-graph lint violations → measure lint again after final
  dependency selection and preserve behavior with state/event boundaries, never disable the rule.
- A compiler-supported CSS option became explicitly webpack-only in the patched Next version →
  the actual production build rejected the mixed configuration → use the existing Turbopack
  default without that unsupported option and rerun the real build with type checking enabled.
- The React refactor's independent critic found manual loading stranded by a version reversal →
  reproduce the exported-hook race, settle each manual request independently, retain stale-result
  guards, then rerun all frontend tests and actual browser recovery scenarios.
- A budget regression helper opened its own loopback HTTP fixture beyond a collector-only task
  boundary → inspected and reported the actual helper scope → discover test fixture side effects
  before describing a test as network-free or dispatching it under a narrower restriction.
