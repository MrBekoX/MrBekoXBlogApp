import { useEffect, useRef, useCallback } from 'react';
import * as signalR from '@microsoft/signalr';
import { PUBLIC_CACHE_HUB_URL } from '@/lib/env';

export type CacheInvalidationType = 'GroupRotated' | 'KeyRemoved' | 'PrefixRemoved';

export interface CacheInvalidationEvent {
  type: CacheInvalidationType;
  target: string;
  timestamp: string;
}

interface UseCacheSyncOptions {
  onInvalidate?: (event: CacheInvalidationEvent) => void;
  onReconnected?: () => void;
  groups?: string[];
  autoReconnect?: boolean;
  debug?: boolean;
}

export function useCacheSync(options: UseCacheSyncOptions = {}) {
  const { onInvalidate, onReconnected, groups = [], autoReconnect = true, debug = false } = options;

  const connectionRef = useRef<signalR.HubConnection | null>(null);
  const onInvalidateRef = useRef(onInvalidate);
  const onReconnectedRef = useRef(onReconnected);
  const groupsRef = useRef(groups);
  const hasBeenConnectedRef = useRef(false);
  const isConnectedRef = useRef(false);
  const retryCountRef = useRef(0);
  const reconnectTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const MAX_RETRIES = 3;

  useEffect(() => {
    onInvalidateRef.current = onInvalidate;
    onReconnectedRef.current = onReconnected;
    groupsRef.current = groups;
  }, [groups, onInvalidate, onReconnected]);

  const log = useCallback((..._args: unknown[]) => {
    if (debug) {
      // Debug logging intentionally muted.
    }
  }, [debug]);

  const connect = useCallback(async () => {
    if (connectionRef.current?.state === signalR.HubConnectionState.Connected) {
      return;
    }

    try {
      const connection = new signalR.HubConnectionBuilder()
        .withUrl(PUBLIC_CACHE_HUB_URL, { withCredentials: true })
        .withAutomaticReconnect({
          nextRetryDelayInMilliseconds: (retryContext) => Math.min(1000 * Math.pow(2, retryContext.previousRetryCount), 30000),
        })
        .configureLogging(signalR.LogLevel.None)
        .build();

      connection.on('CacheInvalidated', (event: CacheInvalidationEvent) => {
        onInvalidateRef.current?.(event);
      });

      connection.onreconnecting(() => {
        isConnectedRef.current = false;
      });

      connection.onreconnected(async () => {
        isConnectedRef.current = true;
        for (const group of groupsRef.current) {
          try {
            await connection.invoke('SubscribeToGroup', group);
          } catch {
            // Ignore group resubscribe errors.
          }
        }
        onReconnectedRef.current?.();
      });

      connection.onclose(() => {
        isConnectedRef.current = false;
      });

      connectionRef.current = connection;
      await connection.start();

      const wasConnectedBefore = hasBeenConnectedRef.current;
      isConnectedRef.current = true;
      hasBeenConnectedRef.current = true;

      for (const group of groupsRef.current) {
        try {
          await connection.invoke('SubscribeToGroup', group);
        } catch {
          // Ignore subscription errors.
        }
      }

      if (wasConnectedBefore) {
        onReconnectedRef.current?.();
      }
    } catch (error) {
      isConnectedRef.current = false;
      const errorMessage = error instanceof Error ? error.message : String(error);
      const isBenignError =
        errorMessage.includes('WebSocket failed') ||
        errorMessage.includes('Failed to fetch') ||
        errorMessage.includes('Failed to complete negotiation') ||
        errorMessage.includes('abort');

      if (isBenignError) {
        return;
      }

      retryCountRef.current += 1;
      if (autoReconnect && retryCountRef.current <= MAX_RETRIES) {
        const delay = Math.min(5000 * retryCountRef.current, 30000);
        if (reconnectTimeoutRef.current) {
          clearTimeout(reconnectTimeoutRef.current);
        }
        reconnectTimeoutRef.current = setTimeout(() => {
          reconnectTimeoutRef.current = null;
          void connect();
        }, delay);
      }
    }
  }, [autoReconnect, log]);

  const disconnect = useCallback(async () => {
    if (!connectionRef.current) {
      return;
    }

    try {
      for (const group of groupsRef.current) {
        try {
          await connectionRef.current.invoke('UnsubscribeFromGroup', group);
        } catch {
          // Ignore cleanup errors.
        }
      }
      await connectionRef.current.stop();
    } catch {
      // Ignore disconnect errors.
    }

    connectionRef.current = null;
    isConnectedRef.current = false;
  }, []);

  useEffect(() => {
    void connect();

    return () => {
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current);
        reconnectTimeoutRef.current = null;
      }
      void disconnect();
    };
  }, [connect, disconnect]);

  return {
    isConnected: isConnectedRef.current,
    connect,
    disconnect,
  };
}

export function useAutoCacheSync(invalidateCache: () => void, options: Omit<UseCacheSyncOptions, 'onInvalidate'> = {}) {
  return useCacheSync({
    ...options,
    onInvalidate: () => {
      invalidateCache();
    },
  });
}
