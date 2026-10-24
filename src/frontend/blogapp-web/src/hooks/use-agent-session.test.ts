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
vi.mock('@microsoft/signalr', () => ({ HubConnectionBuilder: class {}, LogLevel: { Warning: 3 } }));

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
  buildRequest: (input) => buildAgentRequest({ ...input, topic: 'auto', language: 'en', modePreference: 'auto' }),
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
  afterEach(() => { hooks.unmount(); vi.clearAllTimers(); vi.useRealTimers(); });

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
