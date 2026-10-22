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
  refresh: () => void;
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
  let pollStopped = false;
  let pollTimer: unknown = null;

  const stopPollingFallback = () => {
    pollStopped = true;
    if (pollTimer !== null) {
      timers.clearTimeout(pollTimer);
      pollTimer = null;
    }
  };

  const startPollingFallback = () => {
    if (pollTimer !== null || pollStopped) return;
    options.setChannel('polling');
    const poll = () => {
      pollTimer = timers.setTimeout(() => {
        void Promise.resolve()
          .then(() => options.ingest())
          .catch(() => undefined)
          .finally(() => {
            if (!pollStopped) poll();
          });
      }, pollMs);
    };
    poll();
  };

  // 1) Canlı kanal: AgentRunsHub (B5) — sahipliği backend doğrulayan grup üyeliği.
  connection.on('RunUpdated', (payload: AgentRunNotification) => {
    if (disposed) return;
    // Başka run / duplicate-geç bildirim: replay imlecinden geride kalmışsa yok say.
    if (!shouldIngestNotification(payload, runId, options.getLastSequence())) return;
    void options.ingest();
  });

  connection.onreconnected(() => {
    if (disposed) return;
    // Kopukluk penceresini replay ile toparla; grup üyeliği reconnect sonrası yeniden gerekir.
    void connection.invoke('SubscribeToRun', runId).catch(() => undefined);
    void options.ingest();
    options.refresh();
  });

  connection.onclose(() => {
    if (disposed) return;
    // Yeniden bağlanma denemeleri tükendi: SON ÇARE yoklama.
    stopPollingFallback();
    pollStopped = false;
    startPollingFallback();
  });

  connection
    .start()
    .then(() => connection.invoke('SubscribeToRun', runId))
    .then(() => {
      if (!disposed) {
        options.setChannel('live');
        // Bağlantı gecikmişse aradaki olayları kaçırma.
        void options.ingest();
      }
    })
    .catch(() => {
      // Canlı kanal hiç kurulamadı: SON ÇARE replay yoklaması.
      if (!disposed) startPollingFallback();
    });

  return () => {
    disposed = true;
    stopPollingFallback();
    connection.stop().catch(() => undefined);
    options.setChannel('connecting');
  };
}
