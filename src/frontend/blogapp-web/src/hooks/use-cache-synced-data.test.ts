import { beforeEach, describe, expect, it, vi } from 'vitest';

// These primitives drive the actual hook. Assertions concern its public data,
// loading and request behavior, not a particular slot layout or implementation.
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
  };
});
vi.mock('react', () => hooks);
import { useCacheSyncedData } from './use-cache-synced-data';

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => { resolve = done; });
  return { promise, resolve };
}
const settle = async () => { for (let turn = 0; turn < 4; turn += 1) await Promise.resolve(); };
const render = (version: number, fetchFn: () => Promise<string | null>, initialData = 'server') =>
  hooks.render(() => useCacheSyncedData({ initialData, cacheVersion: version, fetchFn }));

describe('cache invalidation data lifecycle', () => {
  beforeEach(() => hooks.reset());

  it('keeps server data without an initial fetch when no invalidation exists', async () => {
    const fetch = vi.fn(async () => 'fresh');
    expect(render(0, fetch)).toMatchObject({ data: 'server', isLoading: false });
    hooks.flushEffects(); await settle();
    expect(fetch).not.toHaveBeenCalled();
  });

  it('represents an invalidation before mount as loading until the fresh result settles', async () => {
    const request = deferred<string | null>();
    const fetch = vi.fn(() => request.promise);
    expect(render(2, fetch)).toMatchObject({ data: 'server', isLoading: true });
    hooks.flushEffects();
    request.resolve('fresh'); await settle();
    expect(render(2, fetch)).toMatchObject({ data: 'fresh', isLoading: false });
  });

  it('never lets a superseded cache version overwrite a newer response', async () => {
    const older = deferred<string | null>();
    const newer = deferred<string | null>();
    const fetch = vi.fn().mockReturnValueOnce(older.promise).mockReturnValueOnce(newer.promise);
    render(1, fetch); hooks.flushEffects();
    render(2, fetch); hooks.flushEffects();
    newer.resolve('new-version'); await settle();
    expect(render(2, fetch).data).toBe('new-version');
    older.resolve('old-version'); await settle();
    expect(render(2, fetch)).toMatchObject({ data: 'new-version', isLoading: false });
  });

  it('retains fresh data on a null result or fetch error and settles a reset to zero', async () => {
    const fetch = vi.fn().mockResolvedValueOnce('fresh').mockResolvedValueOnce(null)
      .mockRejectedValueOnce(new Error('offline'));
    render(1, fetch); hooks.flushEffects(); await settle();
    expect(render(1, fetch).data).toBe('fresh');
    render(2, fetch); hooks.flushEffects(); await settle();
    expect(render(2, fetch)).toMatchObject({ data: 'fresh', isLoading: false });
    render(0, fetch); hooks.flushEffects(); await settle();
    expect(render(0, fetch)).toMatchObject({ data: 'fresh', isLoading: false });
    expect(fetch).toHaveBeenCalledTimes(3);
  });

  it('manual refresh uses the latest committed fetch function and preserves its promise', async () => {
    const previous = vi.fn(async () => 'previous');
    const latest = vi.fn(async () => 'latest');
    render(0, previous); hooks.flushEffects();
    const session = render(0, latest); hooks.flushEffects();
    const pending = session.refresh();
    expect(render(0, latest).isLoading).toBe(true);
    await pending;
    expect(render(0, latest)).toMatchObject({ data: 'latest', isLoading: false });
    expect(previous).not.toHaveBeenCalled();
  });

  it('does not write state when an unmounted invalidation request completes', async () => {
    const request = deferred<string | null>();
    render(1, () => request.promise); hooks.flushEffects();
    hooks.unmount();
    const writes = hooks.writes;
    request.resolve('late'); await settle();
    expect(hooks.writes).toBe(writes);
  });

  it('settles manual loading after an overlapping invalidation returns to a completed version', async () => {
    const manual = deferred<string | null>();
    const invalidation = deferred<string | null>();
    const fetch = vi.fn().mockReturnValueOnce(manual.promise).mockReturnValueOnce(invalidation.promise);
    const session = render(0, fetch); hooks.flushEffects();
    const pending = session.refresh();
    render(1, fetch); hooks.flushEffects();
    render(0, fetch); hooks.flushEffects();
    invalidation.resolve('superseded');
    manual.resolve('manual');
    await pending; await settle();
    expect(render(0, fetch).isLoading).toBe(false);
  });
});
