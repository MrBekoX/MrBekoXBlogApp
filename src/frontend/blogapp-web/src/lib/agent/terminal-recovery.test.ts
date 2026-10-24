import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { AgentRunEvent } from '@/types/agent';
import { createTerminalRecovery } from './terminal-recovery';
import { replayEventPages } from './replay';

describe('terminal result reconciliation', () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => { vi.clearAllTimers(); vi.useRealTimers(); });

  it('recovers after a transient GET failure even after replay has consumed the terminal event', async () => {
    let cursor = 0;
    const result = vi.fn();
    const getStatus = vi.fn().mockRejectedValueOnce(new Error('lost terminal GET'))
      .mockResolvedValue({ status: 'Completed', result: { answer: 'Verified answer' } });
    const recovery = createTerminalRecovery({ isCurrent: () => true, refresh: async () => {
      const status = await getStatus();
      result(status.result);
      return status.status === 'Completed';
    } });
    const terminal: AgentRunEvent = { eventSequence: 7, messageId: 'm', messageType: 'agent.run.completed',
      occurredAt: '2026-10-24T00:00:00Z' };
    const fetchPage = vi.fn(async (after: number) => ({ events: after < 7 ? [terminal] : [], hasMore: false }));
    const replay = () => replayEventPages({ fetchPage, getCursor: () => cursor, setCursor: (n) => { cursor = n; },
      isStale: () => false, maxPages: 25, onFresh: () => recovery.start() });
    await replay();
    expect(cursor).toBe(7);
    await replay();
    expect(getStatus).toHaveBeenCalledOnce();
    await vi.advanceTimersByTimeAsync(750);
    expect(result).toHaveBeenCalledWith({ answer: 'Verified answer' });
    expect(getStatus).toHaveBeenCalledTimes(2);
    await vi.advanceTimersByTimeAsync(60000);
    expect(getStatus).toHaveBeenCalledTimes(2);
  });

  it('keeps a terminal event pending if the GET still says Accepted, with one request and capped backoff', async () => {
    const refresh = vi.fn(async () => false);
    const recovery = createTerminalRecovery({ isCurrent: () => true, refresh, retryDelaysMs: [100, 300] });
    await Promise.all([recovery.start(), recovery.start()]);
    expect(refresh).toHaveBeenCalledOnce();
    await vi.advanceTimersByTimeAsync(100);
    expect(refresh).toHaveBeenCalledTimes(2);
    await vi.advanceTimersByTimeAsync(600);
    expect(refresh).toHaveBeenCalledTimes(4);
    recovery.dispose();
    await vi.advanceTimersByTimeAsync(10000);
    expect(refresh).toHaveBeenCalledTimes(4);
  });

  it('does not retry after run/scope disposal or schedule work after a stale in-flight request resolves', async () => {
    let current = true;
    let resolve!: (terminal: boolean) => void;
    const refresh = vi.fn(() => new Promise<boolean>((done) => { resolve = done; }));
    const recovery = createTerminalRecovery({ isCurrent: () => current, refresh });
    const pending = recovery.start();
    await vi.advanceTimersByTimeAsync(0);
    current = false;
    recovery.dispose();
    resolve(false);
    await pending;
    await vi.advanceTimersByTimeAsync(60000);
    expect(refresh).toHaveBeenCalledOnce();
  });
});
