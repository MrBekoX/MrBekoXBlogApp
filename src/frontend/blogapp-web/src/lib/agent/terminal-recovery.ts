import type { RunChannelTimers } from './run-channel';

interface TerminalRecoveryOptions {
  /** Return true only after the authoritative GET confirms a terminal result. */
  refresh: () => Promise<boolean>;
  isCurrent: () => boolean;
  timers?: RunChannelTimers;
  retryDelaysMs?: readonly number[];
  maxAttempts?: number;
  onExhausted?: () => void;
}

/** A consumed terminal event remains pending until its guarded result is readable.
 * One request/timer at a time; backoff is capped and disposal invalidates pending work.
 */
export function createTerminalRecovery(options: TerminalRecoveryOptions) {
  const timers = options.timers ?? {
    setTimeout: (callback: () => void, ms: number) => globalThis.setTimeout(callback, ms),
    clearTimeout: (handle: unknown) => globalThis.clearTimeout(handle as ReturnType<typeof setTimeout>),
  };
  const delays = options.retryDelaysMs ?? [750, 1500, 3000, 6000, 12000, 20000];
  let disposed = false;
  let running: Promise<void> | null = null;
  let timer: unknown = null;
  let failures = 0;

  const current = () => !disposed && options.isCurrent();
  const dispose = () => {
    disposed = true;
    if (timer !== null) timers.clearTimeout(timer);
    timer = null;
  };

  const start = (): Promise<void> => {
    if (!current() || timer !== null) return Promise.resolve();
    if (running) return running;
    running = Promise.resolve()
      .then(async () => {
        if (!current()) return;
        let complete = false;
        try {
          complete = await options.refresh();
        } catch {
          // A network error must not acknowledge the terminal event.
        }
        if (!current()) return;
        if (complete) {
          dispose();
          return;
        }
        if (options.maxAttempts !== undefined && failures + 1 >= options.maxAttempts) {
          dispose();
          options.onExhausted?.();
          return;
        }
        const delay = delays[Math.min(failures++, delays.length - 1)] ?? 20000;
        timer = timers.setTimeout(() => {
          timer = null;
          void start();
        }, delay);
      })
      .finally(() => {
        running = null;
      });
    return running;
  };

  return { start, dispose };
}
