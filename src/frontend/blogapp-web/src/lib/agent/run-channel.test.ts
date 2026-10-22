import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { AgentRunNotification } from '@/types/agent';
import { openRunChannel, type ChannelState, type RunHubConnection } from './run-channel';

const RUN = '11111111-1111-4111-8111-111111111111';

class FakeConnection implements RunHubConnection {
  handlers = new Map<string, (payload: AgentRunNotification) => void>();
  reconnected: Array<() => void> = [];
  closed: Array<() => void> = [];
  invoked: Array<[string, unknown[]]> = [];
  stopped = 0;
  startResult: Promise<void>;
  private rejectStart?: (error: Error) => void;
  private resolveStart?: () => void;

  constructor() {
    this.startResult = new Promise<void>((resolve, reject) => {
      this.resolveStart = resolve;
      this.rejectStart = reject;
    });
  }

  on(methodName: string, handler: (payload: AgentRunNotification) => void): void {
    this.handlers.set(methodName, handler);
  }
  onreconnected(callback: () => void): void {
    this.reconnected.push(callback);
  }
  onclose(callback: () => void): void {
    this.closed.push(callback);
  }
  start(): Promise<void> {
    return this.startResult;
  }
  invoke(methodName: string, ...args: unknown[]): Promise<unknown> {
    this.invoked.push([methodName, args]);
    return Promise.resolve();
  }
  stop(): Promise<void> {
    this.stopped += 1;
    return Promise.resolve();
  }
  succeed() {
    this.resolveStart?.();
  }
  fail() {
    this.rejectStart?.(new Error('negotiate failed'));
  }
  notify(payload: Partial<AgentRunNotification>) {
    this.handlers.get('RunUpdated')?.(payload as AgentRunNotification);
  }
}

function setup(lastSequence = 0) {
  const connection = new FakeConnection();
  const channelStates: ChannelState[] = [];
  const ingest = vi.fn(async () => undefined);
  const refresh = vi.fn();
  let sequence = lastSequence;
  const dispose = openRunChannel({
    runId: RUN,
    connection,
    getLastSequence: () => sequence,
    ingest,
    refresh,
    setChannel: (state) => channelStates.push(state),
    pollMs: 4000,
  });
  return {
    connection,
    channelStates,
    ingest,
    refresh,
    dispose,
    setSequence: (value: number) => {
      sequence = value;
    },
  };
}

async function flush() {
  for (let i = 0; i < 5; i += 1) await Promise.resolve();
}

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
});

describe('openRunChannel — SignalR canlı kanal', () => {
  it('start → SubscribeToRun → live + aradaki olaylar için replay', async () => {
    const h = setup();
    h.connection.succeed();
    await flush();
    expect(h.connection.invoked).toEqual([['SubscribeToRun', [RUN]]]);
    expect(h.channelStates).toEqual(['live']);
    expect(h.ingest).toHaveBeenCalledTimes(1);
  });

  it('bildirim yalnız tetikleyicidir: başka run ve duplicate/geç bildirim yok sayılır', async () => {
    const h = setup(5);
    h.connection.succeed();
    await flush();
    h.ingest.mockClear();

    h.connection.notify({ run_id: 'other-run', event_sequence: 9 });
    h.connection.notify({ run_id: RUN, event_sequence: 5 });
    h.connection.notify({ run_id: RUN, event_sequence: 4 });
    expect(h.ingest).not.toHaveBeenCalled();

    h.connection.notify({ run_id: RUN, event_sequence: 6 });
    expect(h.ingest).toHaveBeenCalledTimes(1);
  });

  it('yeniden bağlanınca grup üyeliği yenilenir, replay + durum tazelenir', async () => {
    const h = setup();
    h.connection.succeed();
    await flush();
    h.ingest.mockClear();
    h.connection.invoked = [];

    h.connection.reconnected.forEach((callback) => callback());
    expect(h.connection.invoked).toEqual([['SubscribeToRun', [RUN]]]);
    expect(h.ingest).toHaveBeenCalledTimes(1);
    expect(h.refresh).toHaveBeenCalledTimes(1);
  });
});

describe('openRunChannel — SON ÇARE yoklama', () => {
  it('kanal hiç kurulamazsa 4 sn aralıklı replay yoklaması başlar', async () => {
    const h = setup();
    h.connection.fail();
    await flush();
    expect(h.channelStates).toEqual(['polling']);
    expect(h.ingest).not.toHaveBeenCalled();

    await vi.advanceTimersByTimeAsync(4000);
    expect(h.ingest).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(4000);
    expect(h.ingest).toHaveBeenCalledTimes(2);
  });

  it('yeniden bağlanma tükenince (onclose) yoklamaya düşer', async () => {
    const h = setup();
    h.connection.succeed();
    await flush();
    h.ingest.mockClear();

    h.connection.closed.forEach((callback) => callback());
    expect(h.channelStates).toEqual(['live', 'polling']);
    await vi.advanceTimersByTimeAsync(4000);
    expect(h.ingest).toHaveBeenCalledTimes(1);
  });

  it('ingest hata verse de yoklama sürer', async () => {
    const h = setup();
    h.ingest.mockRejectedValueOnce(new Error('network'));
    h.connection.fail();
    await flush();
    await vi.advanceTimersByTimeAsync(4000);
    await vi.advanceTimersByTimeAsync(4000);
    expect(h.ingest).toHaveBeenCalledTimes(2);
  });

  it('dispose yoklamayı durdurur, bağlantıyı kapatır ve kanalı connecting yapar', async () => {
    const h = setup();
    h.connection.fail();
    await flush();
    h.dispose();
    expect(h.connection.stopped).toBe(1);
    expect(h.channelStates[h.channelStates.length - 1]).toBe('connecting');

    await vi.advanceTimersByTimeAsync(12000);
    expect(h.ingest).not.toHaveBeenCalled();

    // dispose sonrası gelen bildirim/reconnect/close etkisizdir
    h.connection.notify({ run_id: RUN, event_sequence: 99 });
    h.connection.reconnected.forEach((callback) => callback());
    h.connection.closed.forEach((callback) => callback());
    expect(h.ingest).not.toHaveBeenCalled();
    expect(h.refresh).not.toHaveBeenCalled();
  });

  it('dispose başlatma tamamlanmadan olursa live/ingest uygulanmaz', async () => {
    const h = setup();
    h.dispose();
    h.connection.succeed();
    await flush();
    expect(h.channelStates).toEqual(['connecting']);
    expect(h.ingest).not.toHaveBeenCalled();
  });
});
