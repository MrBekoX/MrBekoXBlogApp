import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { AgentRunAccepted, AgentRunEvent, AgentRunStatus } from '@/types/agent';

// This Node harness supplies hook primitives, not session behavior. Tests execute
// the production hook, replay and recovery coordinator with controlled HTTP/timers.
const hooks = vi.hoisted(() => {
  type Slot = { value: unknown; deps?: readonly unknown[]; cleanup?: () => void };
  let slots: Slot[] = [];
  let cursor = 0;
  let queued: Array<() => void> = [];
  let writes = 0;
  const changed = (a: readonly unknown[] | undefined, b: readonly unknown[] | undefined) =>
    !a || !b || a.length !== b.length || a.some((value, index) => !Object.is(value, b[index]));
  return {
    render<T>(render: () => T) { cursor = 0; return render(); },
    flushEffects() { const work = queued; queued = []; work.forEach((effect) => effect()); },
    unmount() { slots.forEach((slot) => slot.cleanup?.()); queued = []; },
    reset() { slots = []; cursor = 0; queued = []; writes = 0; },
    get writes() { return writes; },
    useState<T>(initial: T | (() => T)) {
      const index = cursor++;
      if (!slots[index]) slots[index] = { value: typeof initial === 'function' ? (initial as () => T)() : initial };
      return [slots[index].value as T, (next: T | ((value: T) => T)) => {
        writes += 1;
        slots[index].value = typeof next === 'function' ? (next as (value: T) => T)(slots[index].value as T) : next;
      }] as const;
    },
    useRef<T>(value: T) {
      const index = cursor++;
      if (!slots[index]) slots[index] = { value: { current: value } };
      return slots[index].value as { current: T };
    },
    useCallback<T>(callback: T, deps: readonly unknown[]) {
      const index = cursor++;
      if (!slots[index] || changed(slots[index].deps, deps)) slots[index] = { value: callback, deps };
      return slots[index].value as T;
    },
    useEffect(effect: () => void | (() => void), deps?: readonly unknown[]) {
      const index = cursor++;
      if (slots[index] && !changed(slots[index].deps, deps)) return;
      const slot: Slot = { value: undefined, deps, cleanup: slots[index]?.cleanup };
      slots[index] = slot;
      queued.push(() => { slot.cleanup?.(); slot.cleanup = effect() || undefined; });
    },
    useEffectEvent<T extends (...args: never[]) => unknown>(callback: T) {
      const index = cursor++;
      if (!slots[index]) {
        const holder = { callback, invoke: (...args: never[]) => holder.callback(...args) };
        slots[index] = { value: holder };
      }
      const holder = slots[index].value as { callback: T; invoke: T };
      holder.callback = callback;
      return holder.invoke;
    },
  };
});
const api = vi.hoisted(() => ({
  sendMessage: vi.fn(), startResearch: vi.fn(), getRun: vi.fn(), getEvents: vi.fn(),
  cancelRun: vi.fn(), resumeRun: vi.fn(),
}));
vi.mock('react', () => hooks);
vi.mock('@/lib/agent-api', () => ({ agentApi: api, agentErrorMessage: () => 'Request failed' }));
vi.mock('@microsoft/signalr', () => ({ HubConnectionBuilder: class {
  withUrl() { return this; }
  configureLogging() { return this; }
  withAutomaticReconnect() { return this; }
  build() { return { on() {}, onreconnected() {}, onreconnecting() {}, onclose() {},
    start: async () => {}, invoke: async () => {}, stop: async () => {} }; }
}, LogLevel: { Warning: 3 } }));

import { useAgentSession, type UseAgentSessionOptions } from './use-agent-session';
import { buildAgentRequest } from '@/lib/agent/topic';

const RUN = '11111111-1111-4111-8111-111111111111';
const accepted: AgentRunAccepted = { runId: RUN, conversationId: 'conversation', turnSequence: 1,
  replay: false, acceptedAt: '2026-10-24T00:00:00Z', deadlineAt: '2026-10-24T00:05:00Z' };
const status = (state: 'Accepted' | 'Completed'): AgentRunStatus => ({
  ...accepted, status: state, modePreference: 'auto', selectedMode: 'fast', question: 'Question',
  language: 'en', lastEventSequence: state === 'Completed' ? 2 : 1,
  result: state === 'Completed' ? { status: 'completed', answer: 'Verified answer', citations: [] } : null,
});
const terminal: AgentRunEvent = { eventSequence: 2, messageId: 'm', messageType: 'agent.run.completed',
  occurredAt: '2026-10-24T00:00:01Z' };
const options: UseAgentSessionOptions = {
  storageKey: 'test-scope', topic: 'auto', lang: 'en', streamLiveAnswer: true,
  validateRestoredRun: () => true,
  buildRequest: (input) => buildAgentRequest({ ...input, topic: 'auto', language: 'en', modePreference: input.modePreference ?? 'auto' }),
};
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => { resolve = done; });
  return { promise, resolve };
}
const render = () => hooks.render(() => useAgentSession(options));

describe('agent session request and recovery wiring', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.resetAllMocks();
    hooks.reset();
    api.sendMessage.mockResolvedValue(accepted);
    api.getRun.mockResolvedValue(status('Accepted'));
    api.getEvents.mockResolvedValue({ events: [], hasMore: false });
  });
  afterEach(() => { hooks.unmount(); vi.clearAllTimers(); vi.useRealTimers(); vi.unstubAllGlobals(); });

  it.each(['fast', 'analysis', 'deep_research'] as const)('restores and retries the original %s preference', async (mode) => {
    const storage = new Map([[options.storageKey, RUN]]);
    vi.stubGlobal('window', { localStorage: { getItem: (key: string) => storage.get(key) ?? null,
      setItem: (key: string, value: string) => storage.set(key, value), removeItem: (key: string) => storage.delete(key) } });
    api.getRun.mockResolvedValue({ ...status('Completed'), status: 'Failed', modePreference: mode,
      selectedMode: mode, question: 'Please explain this article.' });
    api.startResearch.mockResolvedValue(accepted);
    render(); hooks.flushEffects();
    await vi.advanceTimersByTimeAsync(0);
    expect(render().activeTurn?.isResearch).toBe(mode === 'deep_research');
    expect(await render().retryLast()).toBe(true);
    if (mode === 'deep_research') {
      expect(api.startResearch).toHaveBeenCalledOnce();
      expect(api.sendMessage).not.toHaveBeenCalled();
    } else {
      expect(api.sendMessage.mock.calls[0][0].modePreference).toBe(mode);
      expect(api.startResearch).not.toHaveBeenCalled();
    }
  });

  it('keeps a provisional deadline failure active until a newer worker terminal arrives', async () => {
    const completed = deferred<AgentRunStatus>();
    api.getRun.mockResolvedValueOnce({ ...status('Completed'), status: 'Failed', lastEventSequence: 3,
      isProvisionalTerminal: true, reconciliationUntil: new Date(Date.now() + 30000).toISOString() })
      .mockReturnValueOnce(completed.promise);
    api.getEvents.mockResolvedValueOnce({ events: [{ ...terminal, eventSequence: 3 }], hasMore: false });
    const session = render(); hooks.flushEffects();
    await session.submit('Question', false);
    await vi.advanceTimersByTimeAsync(0);
    const provisional = render();
    expect(provisional.activeTurn?.phase).toBe('failed');
    expect(provisional.activeIsProvisional).toBe(true);
    expect(provisional.isRunActive).toBe(true);
    expect(provisional.activeIsTerminal).toBe(false);
    expect(await provisional.retryLast()).toBe(false);
    completed.resolve({ ...status('Completed'), lastEventSequence: 4 });
    await vi.advanceTimersByTimeAsync(0);
    expect(render().activeTurn?.phase).toBe('completed');
    expect(render().activeIsProvisional).toBe(false);
    expect(render().isRunActive).toBe(false);
  });

  it('stops provisional reconciliation at the bounded grace expiry without changing the backend sequence', async () => {
    const until = Date.now() + 1000;
    api.getRun.mockImplementation(async () => ({ ...status('Completed'), status: 'Failed', lastEventSequence: 3,
      isProvisionalTerminal: Date.now() < until, reconciliationUntil: new Date(until).toISOString() }));
    const session = render(); hooks.flushEffects();
    await session.submit('Question', false);
    await vi.advanceTimersByTimeAsync(0);
    expect(render().activeIsProvisional).toBe(true);
    hooks.flushEffects();
    await vi.advanceTimersByTimeAsync(1000);
    const final = render(); hooks.flushEffects();
    expect(final.activeIsProvisional).toBe(false);
    expect(final.activeIsTerminal).toBe(true);
    expect(final.isRunActive).toBe(false);
    expect(final.activeTurn?.status?.lastEventSequence).toBe(3);
    const reads = api.getRun.mock.calls.length;
    await vi.advanceTimersByTimeAsync(60000);
    expect(api.getRun).toHaveBeenCalledTimes(reads);
  });

  it('ends terminal recovery at provisional expiry even when the final GET is offline', async () => {
    const until = Date.now() + 1000;
    const provisional = { ...status('Completed'), status: 'Failed' as const, lastEventSequence: 3,
      isProvisionalTerminal: true, reconciliationUntil: new Date(until).toISOString() };
    api.getRun.mockImplementation(async () => {
      if (Date.now() >= until) throw new Error('offline');
      return provisional;
    });
    api.getEvents.mockResolvedValueOnce({ events: [{ ...terminal, eventSequence: 3 }], hasMore: false });
    const session = render(); hooks.flushEffects();
    await session.submit('Question', false);
    await vi.advanceTimersByTimeAsync(0);
    expect(render().activeIsProvisional).toBe(true);
    hooks.flushEffects();
    await vi.advanceTimersByTimeAsync(1000);
    expect(render().activeIsProvisional).toBe(true);
    await vi.advanceTimersByTimeAsync(2250);
    expect(render().activeIsProvisional).toBe(false);
    expect(render().finalVerificationUnavailable).toBe(true);
    hooks.flushEffects();
    const reads = api.getRun.mock.calls.length;
    await vi.advanceTimersByTimeAsync(60000);
    expect(api.getRun).toHaveBeenCalledTimes(reads);
    expect(render().activeTurn?.status?.lastEventSequence).toBe(3);
  });

  it('retries a failed terminal GET after the terminal replay cursor has advanced', async () => {
    api.getRun.mockResolvedValueOnce(status('Accepted')).mockRejectedValueOnce(new Error('offline'))
      .mockResolvedValueOnce(status('Completed'));
    api.getEvents.mockImplementation(async (_runId: string, after: number) => ({
      events: after < 2 ? [terminal] : [], hasMore: false,
    }));
    const session = render();
    hooks.flushEffects();
    await session.submit('Question', false);
    await vi.advanceTimersByTimeAsync(0);
    expect(render().activeTurn?.phase).toBe('started');
    await vi.advanceTimersByTimeAsync(750);
    const recovered = render();
    expect(recovered.activeTurn?.phase).toBe('completed');
    expect(recovered.activeTurn?.status?.result?.answer).toBe('Verified answer');
    expect(recovered.isRunActive).toBe(false);
    expect(api.getRun).toHaveBeenCalledTimes(3);
  });

  it('does not let an older overlapping Accepted response erase the guarded terminal result', async () => {
    const older = deferred<AgentRunStatus>();
    api.getRun.mockReturnValueOnce(older.promise).mockResolvedValueOnce(status('Completed'));
    api.getEvents.mockResolvedValueOnce({ events: [terminal], hasMore: false });
    const session = render();
    hooks.flushEffects();
    await session.submit('Question', false);
    await vi.advanceTimersByTimeAsync(0);
    expect(render().activeTurn?.phase).toBe('completed');
    const completedAnnouncement = render().announcement;
    older.resolve(status('Accepted'));
    await vi.advanceTimersByTimeAsync(0);
    expect(render().activeTurn?.status?.result?.answer).toBe('Verified answer');
    expect(render().announcement).toBe(completedAnnouncement);
  });

  it('retains the operation key and payload after an ambiguous POST failure', async () => {
    api.sendMessage.mockRejectedValueOnce(new Error('lost 202')).mockResolvedValueOnce(accepted);
    const session = render();
    hooks.flushEffects();
    expect(await session.submit('Question', false)).toBe(false);
    expect(await render().submit('Question', false)).toBe(true);
    expect(api.sendMessage.mock.calls[0][0]).toEqual(api.sendMessage.mock.calls[1][0]);
    expect(api.sendMessage.mock.calls[0][0].idempotencyKey).not.toBe('');
  });

  it('ignores an older terminal GET after a newer worker terminal has already been applied', async () => {
    const older = deferred<AgentRunStatus>();
    api.getRun.mockReturnValueOnce(older.promise)
      .mockResolvedValueOnce({ ...status('Completed'), lastEventSequence: 4 });
    api.getEvents.mockResolvedValueOnce({ events: [{ ...terminal, eventSequence: 4 }], hasMore: false });
    const session = render();
    hooks.flushEffects();
    await session.submit('Question', false);
    await vi.advanceTimersByTimeAsync(0);
    const completed = render();
    expect(completed.activeTurn?.phase).toBe('completed');
    expect(completed.activeTurn?.status?.lastEventSequence).toBe(4);
    older.resolve({ ...status('Completed'), status: 'Failed', lastEventSequence: 3,
      result: { status: 'failed', answer: 'Earlier deadline failure', citations: [] } });
    await vi.advanceTimersByTimeAsync(0);
    const afterStale = render();
    expect(afterStale.activeTurn?.phase).toBe('completed');
    expect(afterStale.activeTurn?.status?.lastEventSequence).toBe(4);
    expect(afterStale.activeTurn?.status?.result?.answer).toBe('Verified answer');
    expect(afterStale.announcement).toBe(completed.announcement);
  });

  it('blocks a second same-tick submission before a rerender can disable the composer', async () => {
    const acceptance = deferred<AgentRunAccepted>();
    api.sendMessage.mockReturnValueOnce(acceptance.promise);
    const session = render();
    hooks.flushEffects();
    const first = session.submit('Question', false);
    expect(await session.submit('Question', false)).toBe(false);
    expect(api.sendMessage).toHaveBeenCalledOnce();
    acceptance.resolve(accepted);
    expect(await first).toBe(true);
  });

  it('allows equal-sequence authoritative refreshes to mask a published result', async () => {
    const masked = deferred<AgentRunStatus>();
    api.getRun.mockReturnValueOnce(masked.promise)
      .mockResolvedValueOnce({ ...status('Completed'), lastEventSequence: 4 });
    api.getEvents.mockResolvedValueOnce({ events: [{ ...terminal, eventSequence: 4 }], hasMore: false });
    const session = render();
    hooks.flushEffects();
    await session.submit('Question', false);
    await vi.advanceTimersByTimeAsync(0);
    expect(render().activeTurn?.status?.result?.answer).toBe('Verified answer');
    masked.resolve({ ...status('Completed'), lastEventSequence: 4,
      result: { status: 'completed', unavailableReason: 'profile_updated', citations: [] } });
    await vi.advanceTimersByTimeAsync(0);
    expect(render().activeTurn?.phase).toBe('completed');
    expect(render().activeTurn?.status?.result?.unavailableReason).toBe('profile_updated');
    expect(render().activeTurn?.status?.result?.answer).toBeUndefined();
  });

  it('ignores an accepted POST after scope disposal without storing or rendering its result', async () => {
    const acceptance = deferred<AgentRunAccepted>();
    api.sendMessage.mockReturnValueOnce(acceptance.promise);
    const session = render();
    hooks.flushEffects();
    const submission = session.submit('Question', false);
    hooks.unmount();
    const writes = hooks.writes;
    acceptance.resolve(accepted);
    expect(await submission).toBe(false);
    expect(hooks.writes).toBe(writes);
    expect(api.getRun).not.toHaveBeenCalled();
  });

  it('ignores an in-flight status response and cancels retry timers when scope is disposed', async () => {
    const pending = deferred<AgentRunStatus>();
    api.getRun.mockReturnValueOnce(pending.promise).mockRejectedValueOnce(new Error('offline'));
    api.getEvents.mockResolvedValueOnce({ events: [terminal], hasMore: false });
    const session = render();
    hooks.flushEffects();
    await session.submit('Question', false);
    await vi.advanceTimersByTimeAsync(0);
    hooks.unmount();
    const writes = hooks.writes;
    pending.resolve(status('Completed'));
    await vi.advanceTimersByTimeAsync(60000);
    expect(hooks.writes).toBe(writes);
    expect(api.getRun).toHaveBeenCalledTimes(2);
  });
});
