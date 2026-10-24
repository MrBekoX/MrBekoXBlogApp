import type { AgentRequestPlan } from './topic';
import { httpStatusOf } from './session-model';

type ReadyPlan = Extract<AgentRequestPlan, { ok: true }>;

function canonical(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(canonical);
  if (value !== null && typeof value === 'object') {
    return Object.fromEntries(Object.entries(value).sort(([a], [b]) => a.localeCompare(b))
      .map(([key, child]) => [key, canonical(child)]));
  }
  return value;
}

/** A 5xx, timeout or lost response does not prove that acceptance was rolled back. */
export function isDefinitiveSubmissionFailure(error: unknown): boolean {
  const status = httpStatusOf(error);
  return status !== undefined && status >= 400 && status < 500 && status !== 408;
}

/** Keep the exact operation in memory until its response is definitive or input changes.
 * Questions and request payloads are never persisted to browser storage.
 */
export function createSubmissionIdentity(newKey: () => string) {
  let pending: { fingerprint: string; plan: ReadyPlan } | null = null;
  return {
    prepare(candidate: ReadyPlan): ReadyPlan {
      const body = { ...candidate.body, idempotencyKey: undefined };
      const fingerprint = JSON.stringify(canonical({ endpoint: candidate.endpoint, body }));
      if (pending?.fingerprint === fingerprint) return pending.plan;
      const plan = JSON.parse(JSON.stringify({
        ...candidate,
        body: { ...candidate.body, idempotencyKey: newKey() },
      })) as ReadyPlan;
      pending = { fingerprint, plan };
      return plan;
    },
    complete(plan: ReadyPlan) {
      if (pending?.plan === plan) pending = null;
    },
    clear() {
      pending = null;
    },
  };
}
