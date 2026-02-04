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
  const retryCountRef = useRef(0);
  const isRateLimitedRef = useRef(false);
  const rateLimitTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const reconnectTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const MAX_RETRIES = 3;

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
      log(`Attempting to connect to SignalR hub at: ${HUB_URL}`);
      
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
        .configureLogging(debug ? signalR.LogLevel.Debug : signalR.LogLevel.None)
        .build();

      // Handle cache invalidation events
      connection.on('CacheInvalidated', (event: CacheInvalidationEvent) => {
        log('Received cache invalidation:', event);
        onInvalidateRef.current?.(event);
      });

      // Register no-op handlers for events broadcast to all clients
      // These prevent "No client method found" warnings in the console
      // The actual handling is done by use-article-chat.ts
      const noop = () => {};
      connection.on('ChatMessageReceived', noop);
      connection.on('chatMessageReceived', noop);
      connection.on('chatmessagereceived', noop);
      connection.on('AIAnalysisCompleted', noop);
      connection.on('aiAnalysisCompleted', noop);
      connection.on('aianalysiscompleted', noop);

      // Connection state handlers
      connection.onreconnecting((error?: Error) => {
        log('Reconnecting...', error);
        isConnectedRef.current = false;
      });

      connection.onreconnected(async (connectionId?: string) => {
        log('Reconnected with ID:', connectionId);
        isConnectedRef.current = true;

        // Re-subscribe to groups after reconnect - use for...of for proper async handling
        for (const group of groups) {
          try {
            await connection.invoke('SubscribeToGroup', group);
            log(`Re-subscribed to group: ${group}`);
          } catch (err) {
            console.error(`Failed to re-subscribe to group ${group}:`, err);
          }
        }
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
      isConnectedRef.current = false;

      // Suppress benign errors (backend not running)
      const errorMessage = error instanceof Error ? error.message : String(error);
      const isBenignError =
        errorMessage.includes('WebSocket failed') ||
        errorMessage.includes('Failed to fetch') ||
        errorMessage.includes('Failed to complete negotiation') ||
        errorMessage.includes('abort');

      if (isBenignError) {
        if (debug) console.debug('[CacheSync] Backend not available');
        return;
      }

      console.error('Failed to connect to cache sync hub:', error);

      // Check if this is a rate limit error (429)
      const isRateLimitError = error instanceof Error && 
        (error.message.includes('429') || error.message.includes('quota exceeded'));
      
      if (isRateLimitError) {
        isRateLimitedRef.current = true;
        console.warn('[CacheSync] Rate limited - stopping reconnection attempts for 60 seconds');

        // Clear any existing timeout before setting new one
        if (rateLimitTimeoutRef.current) {
          clearTimeout(rateLimitTimeoutRef.current);
        }

        // Reset rate limit flag after 60 seconds
        rateLimitTimeoutRef.current = setTimeout(() => {
          isRateLimitedRef.current = false;
          retryCountRef.current = 0;
          rateLimitTimeoutRef.current = null;
          log('Rate limit cooldown finished, reconnection attempts enabled');
        }, 60000);

        return; // Don't retry immediately
      }

      // Retry connection with limits
      retryCountRef.current++;

      if (autoReconnect && retryCountRef.current <= MAX_RETRIES && !isRateLimitedRef.current) {
        const delay = Math.min(5000 * retryCountRef.current, 30000); // Exponential backoff
        log(`Retrying connection in ${delay}ms (attempt ${retryCountRef.current}/${MAX_RETRIES})...`);

        // Clear any existing reconnect timeout before setting new one
        if (reconnectTimeoutRef.current) {
          clearTimeout(reconnectTimeoutRef.current);
        }

        reconnectTimeoutRef.current = setTimeout(() => {
          reconnectTimeoutRef.current = null;
          // void operator explicitly marks this as fire-and-forget
          void connect();
        }, delay);
      } else if (retryCountRef.current > MAX_RETRIES) {
        console.warn('[CacheSync] Max retries reached, stopping reconnection attempts');
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
      // Clear any pending timers to prevent memory leaks
      if (rateLimitTimeoutRef.current) {
        clearTimeout(rateLimitTimeoutRef.current);
        rateLimitTimeoutRef.current = null;
      }
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current);
        reconnectTimeoutRef.current = null;
      }
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
      invalidateCache();
    },
  });
}
