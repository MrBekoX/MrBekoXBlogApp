/**
 * Tek run için canlı kanal yaşam döngüsü (SignalR AgentRunsHub + SON ÇARE yoklama).
 *
 * Eski ArticleAgentPanel effect'inin bağlantıdan bağımsız çekirdeği; bağlantı
 * nesnesi ve zamanlayıcılar enjekte edilir (birim test edilebilir):
 * - Bildirim TETİKLEYİCİDİR: "RunUpdated" yalnız replay (ingest) başlatır; başka
 *   run'ın ya da imleçten geride kalan (duplicate/geç) bildirim yok sayılır.
 * - start → SubscribeToRun → 'live' + aradaki olaylar için bir replay.
 * - Kanal hiç kurulamazsa ya da yeniden bağlanma denemeleri tükenirse (onclose)
 *   POLL ms aralıklı replay yoklaması ('polling').
 * - Yeniden bağlanınca grup üyeliği yenilenir, replay + durum tazelenir.
 * - dispose: yoklama durur, bağlantı kapanır, kanal 'connecting'e döner.
 */

import type { AgentRunNotification } from '@/types/agent';
import { shouldIngestNotification } from './session-model';

export type ChannelState = 'connecting' | 'live' | 'polling';

/** @microsoft/signalr HubConnection'ın kullanılan alt kümesi. */
export interface RunHubConnection {
  on(methodName: string, handler: (payload: AgentRunNotification) => void): void;
  onreconnected(callback: (connectionId?: string) => void): void;
  onreconnecting?(callback: (error?: Error) => void): void;
  onclose(callback: (error?: Error) => void): void;
  start(): Promise<void>;
  invoke(methodName: string, ...args: unknown[]): Promise<unknown>;
  stop(): Promise<void>;
}

export interface RunChannelTimers {
  setTimeout: (callback: () => void, ms: number) => unknown;
  clearTimeout: (handle: unknown) => void;
}

export interface OpenRunChannelOptions {
  runId: string;
  connection: RunHubConnection;
  getLastSequence: () => number;
  /** Commit edilmiş replay'i oku (getEvents after=imleç). */
  ingest: () => Promise<void> | void;
  /** Yetkili durum/sonuç tazeleme (GET /runs/{id}). */
  refresh: () => Promise<unknown> | void;
  setChannel: (state: ChannelState) => void;
  pollMs: number;
  timers?: RunChannelTimers;
}

const defaultTimers: RunChannelTimers = {
  setTimeout: (callback, ms) => globalThis.setTimeout(callback, ms),
  clearTimeout: (handle) => globalThis.clearTimeout(handle as ReturnType<typeof setTimeout>),
};

/** Kanalı açar; dönen fonksiyon kanalı kapatır (effect cleanup). */
export function openRunChannel(options: OpenRunChannelOptions): () => void {
  const { runId, connection, pollMs } = options;
  const timers = options.timers ?? defaultTimers;

  let disposed = false;
  let polling = false;
  let pollingEpoch = 0;
  let pollTimer: unknown = null;
  let subscriptionTimer: unknown = null;
  let subscriptionEpoch = 0;
  let liveStatusTimer: unknown = null;
  let liveStatusEpoch = 0;

  const stopLiveStatusRefresh = () => {
    liveStatusEpoch += 1;
    if (liveStatusTimer !== null) timers.clearTimeout(liveStatusTimer);
    liveStatusTimer = null;
  };

  const startLiveStatusRefresh = () => {
    stopLiveStatusRefresh();
    const epoch = liveStatusEpoch;
    const interval = Math.max(pollMs * 4, 10000);
    const schedule = () => {
      liveStatusTimer = timers.setTimeout(() => {
        liveStatusTimer = null;
        if (disposed || liveStatusEpoch !== epoch) return;
        // Backend deadline closure and lost notifications may have no replay
        // event. Reconcile status slowly even while group membership is healthy.
        void Promise.resolve().then(() => {
          if (!disposed && liveStatusEpoch === epoch) return options.refresh();
        }).catch(() => undefined)
          .finally(() => {
            if (!disposed && liveStatusEpoch === epoch) schedule();
          });
      }, interval);
    };
    schedule();
  };

  const reconcile = () => Promise.allSettled([
    Promise.resolve().then(() => options.ingest()),
    Promise.resolve().then(() => options.refresh()),
  ]);

  const stopPollingFallback = () => {
    polling = false;
    pollingEpoch += 1;
    if (pollTimer !== null) {
      timers.clearTimeout(pollTimer);
      pollTimer = null;
    }
  };

  const startPollingFallback = () => {
    if (disposed || polling) return;
    stopLiveStatusRefresh();
    polling = true;
    const epoch = ++pollingEpoch;
    options.setChannel('polling');
    const poll = () => {
      pollTimer = timers.setTimeout(() => {
        pollTimer = null;
        if (disposed || !polling || pollingEpoch !== epoch) return;
        // Status remains authoritative even when terminal replay was already consumed.
        void reconcile()
          .finally(() => {
            if (!disposed && polling && pollingEpoch === epoch) poll();
          });
      }, pollMs);
    };
    poll();
  };

  const invalidateSubscription = () => {
    subscriptionEpoch += 1;
    if (subscriptionTimer !== null) timers.clearTimeout(subscriptionTimer);
    subscriptionTimer = null;
  };

  const subscribe = () => {
    invalidateSubscription();
    stopLiveStatusRefresh();
    const epoch = subscriptionEpoch;
    let attempts = 0;
    const isCurrent = () => !disposed && subscriptionEpoch === epoch;
    options.setChannel('connecting');
    const attempt = async () => {
      if (!isCurrent()) return;
      try {
        await connection.invoke('SubscribeToRun', runId);
        if (!isCurrent()) return;
        stopPollingFallback();
        options.setChannel('live');
        startLiveStatusRefresh();
        await reconcile();
      } catch {
        if (!isCurrent()) return;
        // A transport connection without group membership cannot deliver this run.
        startPollingFallback();
        const retryDelay = [1000, 3000][attempts++];
        if (retryDelay !== undefined) {
          subscriptionTimer = timers.setTimeout(() => {
            subscriptionTimer = null;
            void attempt();
          }, retryDelay);
        }
      }
    };
    void attempt();
  };

  // 1) Canlı kanal: AgentRunsHub (B5) — sahipliği backend doğrulayan grup üyeliği.
  connection.on('RunUpdated', (payload: AgentRunNotification) => {
    if (disposed) return;
    // Başka run / duplicate-geç bildirim: replay imlecinden geride kalmışsa yok say.
    if (!shouldIngestNotification(payload, runId, options.getLastSequence())) return;
    void Promise.resolve().then(() => options.ingest()).catch(() => undefined);
  });

  connection.onreconnected(() => {
    if (disposed) return;
    // A new connection loses its old groups. Only successful membership is live.
    subscribe();
  });

  connection.onreconnecting?.(() => {
    if (disposed) return;
    invalidateSubscription();
    startPollingFallback();
  });

  connection.onclose(() => {
    if (disposed) return;
    // Yeniden bağlanma denemeleri tükendi: SON ÇARE yoklama.
    invalidateSubscription();
    startPollingFallback();
  });

  connection
    .start()
    .then(() => {
      if (!disposed) subscribe();
    })
    .catch(() => {
      // Canlı kanal hiç kurulamadı: SON ÇARE replay yoklaması.
      if (!disposed) startPollingFallback();
    });

  return () => {
    disposed = true;
    invalidateSubscription();
    stopPollingFallback();
    stopLiveStatusRefresh();
    connection.stop().catch(() => undefined);
    options.setChannel('connecting');
  };
}
