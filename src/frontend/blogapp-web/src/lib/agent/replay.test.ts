import { describe, expect, it, vi } from 'vitest';
import type { AgentRunEvent } from '@/types/agent';
import { replayEventPages, selectFreshEvents } from './replay';

function ev(sequence: number, kind = 'retrieval_started'): AgentRunEvent {
  return {
    eventSequence: sequence,
    messageType: 'agent.run.progressed',
    messageId: `m-${sequence}`,
    occurredAt: '2026-10-22T10:00:00Z',
    kind,
  };
}

function harness(pages: Array<{ events: AgentRunEvent[]; hasMore: boolean }>, startCursor = 0) {
  let cursor = startCursor;
  const requestedAfter: number[] = [];
  const applied: number[][] = [];
  let call = 0;
  const options = {
    fetchPage: vi.fn(async (after: number) => {
      requestedAfter.push(after);
      const page = pages[Math.min(call, pages.length - 1)];
      call += 1;
      return page;
    }),
    getCursor: () => cursor,
    setCursor: (value: number) => {
      cursor = value;
    },
    onFresh: (fresh: AgentRunEvent[]) => {
      applied.push(fresh.map((event) => event.eventSequence));
    },
    isStale: () => false,
    maxPages: 25,
  };
  return { options, requestedAfter, applied, cursor: () => cursor };
}

describe('selectFreshEvents', () => {
  it('imleçten büyük ve kesin artan olayları seçer (duplicate/geç olay yok sayılır)', () => {
    expect(selectFreshEvents([ev(1), ev(2), ev(2), ev(3)], 1).map((e) => e.eventSequence)).toEqual([2, 3]);
    expect(selectFreshEvents([ev(5), ev(4), ev(6)], 0).map((e) => e.eventSequence)).toEqual([5, 6]);
    expect(selectFreshEvents([ev(1), ev(2)], 2)).toEqual([]);
  });
});

describe('replayEventPages', () => {
  it('hasMore sürdükçe sayfaları imleçten okur ve imleci ilerletir', async () => {
    const h = harness([
      { events: [ev(1), ev(2)], hasMore: true },
      { events: [ev(3), ev(4)], hasMore: true },
      { events: [ev(5)], hasMore: false },
    ]);
    await expect(replayEventPages(h.options)).resolves.toBe('done');
    expect(h.requestedAfter).toEqual([0, 2, 4]);
    expect(h.applied).toEqual([[1, 2], [3, 4], [5]]);
    expect(h.cursor()).toBe(5);
  });

  it('duplicate ve geç replay sayfası adım/imleç geri çeviremez', async () => {
    const h = harness(
      [
        { events: [ev(3), ev(4), ev(5)], hasMore: true }, // 3-4 zaten görüldü
        { events: [ev(5), ev(2)], hasMore: false }, // tamamen bayat
      ],
      4,
    );
    await replayEventPages(h.options);
    expect(h.applied).toEqual([[5]]);
    expect(h.cursor()).toBe(5);
  });

  it('sayfa üst sınırında durur (sonraki bildirim imleçten sürer)', async () => {
    const h = harness([{ events: [ev(1)], hasMore: true }]);
    let next = 1;
    h.options.fetchPage.mockImplementation(async () => ({ events: [ev(next++)], hasMore: true }));
    await expect(replayEventPages({ ...h.options, maxPages: 3 })).resolves.toBe('page_cap');
    expect(h.options.fetchPage).toHaveBeenCalledTimes(3);
    expect(h.cursor()).toBe(3);
  });

  it('yeni run başladıysa (stale) bayat sayfa UYGULANMAZ', async () => {
    let stale = false;
    const h = harness([{ events: [ev(1), ev(2)], hasMore: true }]);
    h.options.fetchPage.mockImplementation(async () => {
      stale = true; // istek uçuştayken yeni run başladı
      return { events: [ev(1), ev(2)], hasMore: true };
    });
    await expect(replayEventPages({ ...h.options, isStale: () => stale })).resolves.toBe('stale');
    expect(h.applied).toEqual([]);
    expect(h.cursor()).toBe(0);
  });

  it('onFresh bitmeden sonraki sayfa okunmaz (terminal tazeleme sırası korunur)', async () => {
    const order: string[] = [];
    const h = harness([
      { events: [ev(1, 'completed')], hasMore: true },
      { events: [], hasMore: false },
    ]);
    h.options.fetchPage.mockImplementation(async (after: number) => {
      order.push(`fetch:${after}`);
      return after === 0 ? { events: [ev(1, 'completed')], hasMore: true } : { events: [], hasMore: false };
    });
    await replayEventPages({
      ...h.options,
      onFresh: async () => {
        order.push('apply:start');
        await Promise.resolve();
        order.push('apply:end');
      },
    });
    expect(order).toEqual(['fetch:0', 'apply:start', 'apply:end', 'fetch:1']);
  });
});
