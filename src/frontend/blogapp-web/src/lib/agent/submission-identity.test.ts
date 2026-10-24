import { AxiosError, AxiosHeaders, type AxiosResponse, type InternalAxiosRequestConfig } from 'axios';
import { describe, expect, it, vi } from 'vitest';
import { createSubmissionIdentity, isDefinitiveSubmissionFailure } from './submission-identity';
import type { AgentRequestPlan } from './topic';

type ReadyPlan = Extract<AgentRequestPlan, { ok: true }>;
const request = (): ReadyPlan => ({ ok: true, endpoint: 'messages', body: {
  question: 'Question', language: 'en', modePreference: 'auto', conversationTopic: 'auto', idempotencyKey: '',
} });
function httpError(status: number) {
  const config = { headers: new AxiosHeaders() } as InternalAxiosRequestConfig;
  const response = { status, config } as AxiosResponse;
  return new AxiosError('HTTP error', undefined, config, undefined, response);
}

describe('submission identity across ambiguous acceptance', () => {
  it('reuses the exact key and payload when a committed acceptance loses its response', async () => {
    let key = 0;
    const identity = createSubmissionIdentity(() => `operation-${++key}`);
    const accepted = new Map<string, string>();
    const send = vi.fn(async (plan: ReadyPlan) => {
      const key = plan.body.idempotencyKey;
      if (!accepted.has(key)) {
        accepted.set(key, 'existing-run');
        throw new Error('202 response lost after commit');
      }
      return accepted.get(key);
    });
    const first = identity.prepare(request());
    await expect(send(first)).rejects.toThrow('202 response lost');
    const retry = identity.prepare(request());
    expect(retry).toEqual(first);
    await expect(send(retry)).resolves.toBe('existing-run');
    expect(accepted.size).toBe(1);
    identity.complete(retry);
    expect(identity.prepare(request()).body.idempotencyKey).not.toBe(first.body.idempotencyKey);
  });

  it('changes identity when request scope, endpoint or payload changes; clearing a stale operation cannot drop the new one', () => {
    let key = 0;
    const identity = createSubmissionIdentity(() => `operation-${++key}`);
    const candidate = request();
    const first = identity.prepare(candidate);
    candidate.body.question = 'Changed question';
    expect(first.body.question).toBe('Question');
    const changed = identity.prepare(candidate);
    expect(changed.body.idempotencyKey).not.toBe(first.body.idempotencyKey);
    identity.complete(first);
    expect(identity.prepare(candidate)).toBe(changed);
    identity.clear();
    expect(identity.prepare(candidate).body.idempotencyKey).not.toBe(changed.body.idempotencyKey);
    const research = identity.prepare({ ...request(), endpoint: 'research' });
    expect(research.body.idempotencyKey).not.toBe(first.body.idempotencyKey);
  });

  it.each([undefined, 408, 500, 502, 503, 504])('retains identity for an ambiguous response (%s)', (status) => {
    expect(isDefinitiveSubmissionFailure(status === undefined ? new Error('network') : httpError(status))).toBe(false);
  });

  it.each([400, 401, 403, 409, 422, 429])('allows a fresh operation after definitive rejection (%s)', (status) => {
    expect(isDefinitiveSubmissionFailure(httpError(status))).toBe(true);
  });
});
