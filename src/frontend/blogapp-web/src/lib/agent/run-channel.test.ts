import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { AgentRunNotification } from '@/types/agent';
import { openRunChannel, type RunHubConnection } from './run-channel';

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => { resolve = done; });
  return { promise, resolve };
}

class Connection implements RunHubConnection {
  notification?: (payload: AgentRunNotification) => void;
  reconnected?: () => void;
  reconnecting?: () => void;
  closed?: () => void;
  start = vi.fn(async () => {});
  invoke = vi.fn<RunHubConnection['invoke']>(async () => undefined);
  stop = vi.fn(async () => {});
  on(_name: string, handler: (payload: AgentRunNotification) => void) { this.notification = handler; }
  onreconnected(handler: () => void) { this.reconnected = handler; }
  onreconnecting(handler: () => void) { this.reconnecting = handler; }
  onclose(handler: () => void) { this.closed = handler; }
}

function open(connection = new Connection()) {
  const ingest = vi.fn(async () => {});
  const refresh = vi.fn(async () => {});
  const setChannel = vi.fn();
  const dispose = openRunChannel({ connection, runId: 'run-1', getLastSequence: () => 4,
    ingest, refresh, setChannel, pollMs: 4000 });
  return { connection, ingest, refresh, setChannel, dispose };
}

describe('run channel recovery', () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => { vi.clearAllTimers(); vi.useRealTimers(); });

  it('does not report live before group membership succeeds, and catches the gap with replay and status', async () => {
    const connection = new Connection();
    const subscription = deferred<unknown>();
    connection.invoke.mockReturnValueOnce(subscription.promise);
    const channel = open(connection);
    await vi.advanceTimersByTimeAsync(0);
    expect(channel.setChannel).not.toHaveBeenCalledWith('live');
    subscription.resolve(undefined);
    await vi.advanceTimersByTimeAsync(0);
    expect(channel.setChannel).toHaveBeenLastCalledWith('live');
    expect(channel.ingest).toHaveBeenCalledOnce();
    expect(channel.refresh).toHaveBeenCalledOnce();
    channel.dispose();
  });

  it('polls authoritative status after failed reconnect subscription, then stops polling on successful retry', async () => {
    const channel = open();
    await vi.advanceTimersByTimeAsync(0);
    channel.connection.invoke.mockRejectedValueOnce(new Error('lost subscription response'))
      .mockRejectedValueOnce(new Error('still unavailable'));
    channel.connection.reconnected?.();
    await vi.advanceTimersByTimeAsync(0);
    expect(channel.setChannel).toHaveBeenLastCalledWith('polling');
    await vi.advanceTimersByTimeAsync(1000);
    expect(channel.setChannel).toHaveBeenLastCalledWith('polling');
    await vi.advanceTimersByTimeAsync(3000);
    expect(channel.refresh.mock.calls.length).toBeGreaterThan(1);
    expect(channel.setChannel).toHaveBeenLastCalledWith('live');
    const reads = channel.refresh.mock.calls.length;
    await vi.advanceTimersByTimeAsync(12000);
    expect(channel.refresh).toHaveBeenCalledTimes(reads);
    channel.dispose();
  });

  it('bounds subscription attempts and keeps polling status even when replay fails', async () => {
    const connection = new Connection();
    connection.invoke.mockRejectedValue(new Error('group unavailable'));
    const channel = open(connection);
    channel.ingest.mockRejectedValue(new Error('replay unavailable'));
    await vi.advanceTimersByTimeAsync(12000);
    expect(connection.invoke).toHaveBeenCalledTimes(3);
    expect(channel.refresh).toHaveBeenCalledTimes(3);
    expect(channel.setChannel).toHaveBeenLastCalledWith('polling');
    channel.dispose();
    const reads = channel.refresh.mock.calls.length;
    await vi.advanceTimersByTimeAsync(10000);
    expect(channel.refresh).toHaveBeenCalledTimes(reads);
  });

  it('polls during transport reconnect and falls back when the initial start fails', async () => {
    const channel = open();
    await vi.advanceTimersByTimeAsync(0);
    channel.connection.reconnecting?.();
    await vi.advanceTimersByTimeAsync(4000);
    expect(channel.setChannel).toHaveBeenLastCalledWith('polling');
    expect(channel.refresh).toHaveBeenCalledTimes(2);
    channel.dispose();
    const connection = new Connection();
    connection.start.mockRejectedValueOnce(new Error('offline'));
    const fallback = open(connection);
    await vi.advanceTimersByTimeAsync(4000);
    expect(fallback.refresh).toHaveBeenCalledOnce();
    expect(connection.invoke).not.toHaveBeenCalled();
    fallback.dispose();
  });

  it('does not apply a late subscription after disposal or resubscribe after a late start', async () => {
    const connection = new Connection();
    const start = deferred<void>();
    connection.start.mockReturnValueOnce(start.promise);
    const channel = open(connection);
    channel.dispose();
    start.resolve();
    await vi.advanceTimersByTimeAsync(0);
    expect(connection.invoke).not.toHaveBeenCalled();

    const late = new Connection();
    const subscription = deferred<unknown>();
    late.invoke.mockReturnValueOnce(subscription.promise);
    const disposed = open(late);
    await vi.advanceTimersByTimeAsync(0);
    disposed.dispose();
    subscription.resolve(undefined);
    await vi.advanceTimersByTimeAsync(10000);
    expect(disposed.setChannel).not.toHaveBeenCalledWith('live');
    expect(disposed.refresh).not.toHaveBeenCalled();
  });

  it('ignores other runs and duplicate notifications', async () => {
    const channel = open();
    await vi.advanceTimersByTimeAsync(0);
    const notification = { run_id: 'other', event_sequence: 5 } as AgentRunNotification;
    channel.connection.notification?.(notification);
    channel.connection.notification?.({ ...notification, run_id: 'run-1', event_sequence: 4 });
    await vi.advanceTimersByTimeAsync(0);
    expect(channel.ingest).toHaveBeenCalledOnce();
    channel.connection.notification?.({ ...notification, run_id: 'run-1' });
    await vi.advanceTimersByTimeAsync(0);
    expect(channel.ingest).toHaveBeenCalledTimes(2);
    channel.dispose();
  });

  it('does not let an old in-flight poll create a second poll loop after another reconnect', async () => {
    const channel = open();
    await vi.advanceTimersByTimeAsync(0);
    const oldPoll = deferred<void>();
    channel.refresh.mockReturnValueOnce(oldPoll.promise);
    channel.connection.reconnecting?.();
    await vi.advanceTimersByTimeAsync(4000);
    channel.connection.reconnected?.();
    await vi.advanceTimersByTimeAsync(0);
    expect(channel.setChannel).toHaveBeenLastCalledWith('live');
    channel.connection.reconnecting?.();
    oldPoll.resolve();
    await vi.advanceTimersByTimeAsync(0);
    expect(vi.getTimerCount()).toBe(1);
    channel.dispose();
  });

  it('reconciles a backend-only terminal status while the live connection receives no event', async () => {
    const channel = open();
    await vi.advanceTimersByTimeAsync(0);
    expect(channel.refresh).toHaveBeenCalledOnce();
    let terminal = false;
    channel.refresh.mockImplementation(async () => { terminal = true; });
    await vi.advanceTimersByTimeAsync(15999);
    expect(terminal).toBe(false);
    await vi.advanceTimersByTimeAsync(1);
    expect(terminal).toBe(true);
    expect(channel.ingest).toHaveBeenCalledOnce();
    expect(channel.setChannel).toHaveBeenLastCalledWith('live');
    channel.dispose();
    const reads = channel.refresh.mock.calls.length;
    await vi.advanceTimersByTimeAsync(60000);
    expect(channel.refresh).toHaveBeenCalledTimes(reads);
  });
});
