import { useEffect, useRef, useCallback } from 'react';
import * as signalR from '@microsoft/signalr';

// Cache invalidation event types matching backend
export type CacheInvalidationType = 'GroupRotated' | 'KeyRemoved' | 'PrefixRemoved';

export interface CacheInvalidationEvent {
  type: CacheInvalidationType;
  target: string;
  timestamp: string;
}

interface UseCacheSyncOptions {
  /** Callback when cache is invalidated */
  onInvalidate?: (event: CacheInvalidationEvent) => void;
  /** Cache groups to listen for (e.g., 'posts_list', 'categories') */
  groups?: string[];
  /** Auto-reconnect on disconnect (default: true) */
  autoReconnect?: boolean;
  /** Enable debug logging (default: false) */
  debug?: boolean;
}

// Extract base URL without /api or /api/v1 suffix for SignalR hub
// SignalR hubs are not versioned, they live at /hubs/cache
const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:5116/api/v1';
const BASE_URL = API_URL.replace(/\/api(\/v\d+)?\/?$/, '');
const HUB_URL = `${BASE_URL}/hubs/cache`;

/**
 * React hook for real-time cache synchronization with backend.
 * Connects to SignalR hub and receives cache invalidation events.
 */
export function useCacheSync(options: UseCacheSyncOptions = {}) {
  const { onInvalidate, groups = [], autoReconnect = true, debug = false } = options;

  const connectionRef = useRef<signalR.HubConnection | null>(null);
  const onInvalidateRef = useRef(onInvalidate);
  const isConnectedRef = useRef(false);

  // Keep callback ref updated
  useEffect(() => {
    onInvalidateRef.current = onInvalidate;
  }, [onInvalidate]);

  const log = useCallback((...args: unknown[]) => {
    if (debug) {
      console.log('[CacheSync]', ...args);
    }
  }, [debug]);

  const connect = useCallback(async () => {
    if (connectionRef.current?.state === signalR.HubConnectionState.Connected) {
      return;
    }

    try {
      const connection = new signalR.HubConnectionBuilder()
        .withUrl(HUB_URL, {
          withCredentials: true,
        })
        .withAutomaticReconnect({
          nextRetryDelayInMilliseconds: (retryContext: signalR.RetryContext) => {
            // Exponential backoff: 0s, 2s, 4s, 8s, 16s, max 30s
            const delay = Math.min(1000 * Math.pow(2, retryContext.previousRetryCount), 30000);
            log(`Reconnecting in ${delay}ms (attempt ${retryContext.previousRetryCount + 1})`);
            return delay;
          }
        })
        .configureLogging(debug ? signalR.LogLevel.Debug : signalR.LogLevel.Warning)
        .build();

      // Handle cache invalidation events
      connection.on('CacheInvalidated', (event: CacheInvalidationEvent) => {
        log('Received cache invalidation:', event);
        onInvalidateRef.current?.(event);
      });

      // Connection state handlers
      connection.onreconnecting((error?: Error) => {
        log('Reconnecting...', error);
        isConnectedRef.current = false;
      });

      connection.onreconnected((connectionId?: string) => {
        log('Reconnected with ID:', connectionId);
        isConnectedRef.current = true;

        // Re-subscribe to groups after reconnect
        groups.forEach(async (group) => {
          try {
            await connection.invoke('SubscribeToGroup', group);
            log(`Re-subscribed to group: ${group}`);
          } catch (err) {
            console.error(`Failed to re-subscribe to group ${group}:`, err);
          }
        });
      });

      connection.onclose((error?: Error) => {
        log('Connection closed', error);
        isConnectedRef.current = false;
      });

      connectionRef.current = connection;

      await connection.start();
      log('Connected to cache sync hub');
      isConnectedRef.current = true;

      // Subscribe to specified groups
      for (const group of groups) {
        try {
          await connection.invoke('SubscribeToGroup', group);
          log(`Subscribed to group: ${group}`);
        } catch (err) {
          console.error(`Failed to subscribe to group ${group}:`, err);
        }
      }
    } catch (error) {
      console.error('Failed to connect to cache sync hub:', error);
      isConnectedRef.current = false;

      // Retry connection after delay if autoReconnect is enabled
      if (autoReconnect) {
        setTimeout(() => {
          log('Retrying initial connection...');
          connect();
        }, 5000);
      }
    }
  }, [groups, autoReconnect, debug, log]);

  const disconnect = useCallback(async () => {
    if (connectionRef.current) {
      try {
        // Unsubscribe from groups before disconnecting
        for (const group of groups) {
          try {
            await connectionRef.current.invoke('UnsubscribeFromGroup', group);
          } catch {
            // Ignore errors during cleanup
          }
        }

        await connectionRef.current.stop();
        log('Disconnected from cache sync hub');
      } catch (error) {
        console.error('Error disconnecting:', error);
      }
      connectionRef.current = null;
      isConnectedRef.current = false;
    }
  }, [groups, log]);

  useEffect(() => {
    connect();

    return () => {
      disconnect();
    };
  }, [connect, disconnect]);

  return {
    isConnected: isConnectedRef.current,
    connect,
    disconnect,
  };
}

/**
 * Simple hook that auto-connects and calls invalidateCache on any cache event.
 * Use this in components that need to refresh data when backend cache is invalidated.
 */
export function useAutoCacheSync(invalidateCache: () => void, options: Omit<UseCacheSyncOptions, 'onInvalidate'> = {}) {
  return useCacheSync({
    ...options,
    onInvalidate: (event) => {
      console.log('[CacheSync] Cache invalidated, refreshing local cache:', event.type, event.target);
      invalidateCache();
    },
  });
}
