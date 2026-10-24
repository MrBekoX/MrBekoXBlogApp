import { describe, expect, it, vi } from 'vitest';
import type { AgentRunEvent } from '@/types/agent';
import { replayEventPages } from './replay';

const event = (sequence: number): AgentRunEvent => ({ eventSequence: sequence, messageType: 'agent.run.progressed',
  messageId: `m-${sequence}`, occurredAt: '2026-10-24T00:00:00Z' });

describe('committed event replay', () => {
  it('resumes after the page cap without duplicating already committed events', async () => {
    let cursor = 0;
    const applied: number[] = [];
    const fetchPage = vi.fn(async (after: number) => ({
      events: after === 0 ? [event(1), event(1), event(2)] : [event(2), event(3)], hasMore: after === 0,
    }));
    const options = { fetchPage, getCursor: () => cursor, setCursor: (n: number) => { cursor = n; },
      onFresh: (events: AgentRunEvent[]) => { applied.push(...events.map((e) => e.eventSequence)); },
      isStale: () => false, maxPages: 1 };
    expect(await replayEventPages(options)).toBe('page_cap');
    expect(await replayEventPages(options)).toBe('done');
    expect(applied).toEqual([1, 2, 3]);
    expect(fetchPage.mock.calls.map(([after]) => after)).toEqual([0, 2]);
  });

  it('discards a response that arrives after a run/scope switch', async () => {
    let stale = false;
    const setCursor = vi.fn();
    const onFresh = vi.fn();
    const outcome = await replayEventPages({ fetchPage: async () => {
      stale = true;
      return { events: [event(1)], hasMore: false };
    }, getCursor: () => 0, setCursor, onFresh, isStale: () => stale, maxPages: 25 });
    expect(outcome).toBe('stale');
    expect(setCursor).not.toHaveBeenCalled();
    expect(onFresh).not.toHaveBeenCalled();
  });
});
