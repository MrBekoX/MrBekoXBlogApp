'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import * as signalR from '@microsoft/signalr';
import { AUTHORING_EVENTS_HUB_URL } from '@/lib/env';
import { aiApi, getErrorMessage, postsApi } from '@/lib/api';
import { createOperationId } from '@/lib/idempotency';
import { useAuthStore } from '@/stores/auth-store';
import type { AiOperationAcceptedResponse, AiOperationCompletedEvent, ApiResponse } from '@/types';

interface UseAuthoringAiOperationsOptions {
  debug?: boolean;
}

interface PendingOperation {
  timeout: ReturnType<typeof setTimeout>;
  resolve: (value: any) => void;
  reject: (reason?: unknown) => void;
  mapResult: (event: AiOperationCompletedEvent) => unknown;
}

const OPERATION_TIMEOUT_MS = 130000;

function normalizeCompletedEvent(rawEvent: Record<string, unknown>): AiOperationCompletedEvent {
  return {
    operationId: String(rawEvent.operationId ?? rawEvent.OperationId ?? ''),
    correlationId: String(rawEvent.correlationId ?? rawEvent.CorrelationId ?? ''),
    operationType: String(rawEvent.operationType ?? rawEvent.OperationType ?? ''),
    resourceId: (rawEvent.resourceId ?? rawEvent.ResourceId) as string | undefined,
    result: rawEvent.result ?? rawEvent.Result,
    timestamp: String(rawEvent.timestamp ?? rawEvent.Timestamp ?? new Date().toISOString()),
  };
}

function expectStringResult(event: AiOperationCompletedEvent, expectedOperationType: string): string {
  if (event.operationType !== expectedOperationType) {
    throw new Error(`Unexpected AI completion type: ${event.operationType}`);
  }

  if (typeof event.result !== 'string') {
    throw new Error('AI operation did not return text output.');
  }

  return event.result;
}

function expectStringArrayResult(event: AiOperationCompletedEvent, expectedOperationType: string): string[] {
  if (event.operationType !== expectedOperationType) {
    throw new Error(`Unexpected AI completion type: ${event.operationType}`);
  }

  if (!Array.isArray(event.result)) {
    throw new Error('AI operation did not return a tag list.');
  }

  return event.result.map((item) => String(item));
}

export function useAuthoringAiOperations(options: UseAuthoringAiOperationsOptions = {}) {
  const { debug = false } = options;
  const { user } = useAuthStore();

  const connectionRef = useRef<signalR.HubConnection | null>(null);
  const connectionPromiseRef = useRef<Promise<void> | null>(null);
  const pendingRef = useRef<Map<string, PendingOperation>>(new Map());
  const userIdRef = useRef<string | null>(user?.id ?? null);
  const [isBackpressured, setIsBackpressured] = useState(false);
  const backpressureTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    userIdRef.current = user?.id ?? null;
  }, [user?.id]);

  const log = useCallback((...args: unknown[]) => {
    if (debug) {
      console.debug('[useAuthoringAiOperations]', ...args);
    }
  }, [debug]);

  const clearPending = useCallback((operationId: string) => {
    const pending = pendingRef.current.get(operationId);
    if (!pending) {
      return null;
    }

    clearTimeout(pending.timeout);
    pendingRef.current.delete(operationId);
    return pending;
  }, []);

  const ensureConnected = useCallback(async () => {
    const currentUserId = userIdRef.current;
    if (!currentUserId) {
      throw new Error('Authentication required for AI authoring operations.');
    }

    if (connectionRef.current?.state === signalR.HubConnectionState.Connected) {
      return;
    }

    if (connectionPromiseRef.current) {
      await connectionPromiseRef.current;
      return;
    }

    connectionPromiseRef.current = (async () => {
      let connection = connectionRef.current;

      // Define handler function once, outside the connection creation
      const handleCompleted = (rawEvent: Record<string, unknown>) => {
        const event = normalizeCompletedEvent(rawEvent);
        const pending = clearPending(event.operationId);
        if (!pending) {
          return;
        }

        try {
          pending.resolve(pending.mapResult(event));
        } catch (error) {
          pending.reject(error);
        }
      };

      if (!connection) {
        connection = new signalR.HubConnectionBuilder()
          .withUrl(AUTHORING_EVENTS_HUB_URL, {
            withCredentials: true,
            skipNegotiation: true,
            transport: signalR.HttpTransportType.WebSockets,
          })
          .withAutomaticReconnect()
          .configureLogging(signalR.LogLevel.None)
          .build();

        connection.on('AiOperationCompleted', handleCompleted);
        connection.on('aiOperationCompleted', handleCompleted);
        connection.onreconnected(async () => {
          const reconnectedUserId = userIdRef.current;
          if (!reconnectedUserId) {
            return;
          }

          try {
            await connection?.invoke('JoinUserGroup', reconnectedUserId);
          } catch (error) {
            log('Failed to rejoin authoring user group', error);
          }
        });

        connectionRef.current = connection;
      }

      // Ensure connection is started - handle race conditions gracefully
      try {
        if (connection.state === signalR.HubConnectionState.Disconnected) {
          await connection.start();
        }
      } catch (error) {
        // If start fails, try to stop and recreate the connection
        log('SignalR connection failed, attempting to reconnect...', error);
        try {
          await connection.stop();
        } catch {
          // Ignore stop errors
        }
        connectionRef.current = null;

        // Try one more time with a fresh connection
        connection = new signalR.HubConnectionBuilder()
          .withUrl(AUTHORING_EVENTS_HUB_URL, {
            withCredentials: true,
            skipNegotiation: true,
            transport: signalR.HttpTransportType.WebSockets,
          })
          .withAutomaticReconnect()
          .configureLogging(signalR.LogLevel.None)
          .build();

        connection.on('AiOperationCompleted', handleCompleted);
        connection.on('aiOperationCompleted', handleCompleted);
        connection.onreconnected(async () => {
          const reconnectedUserId = userIdRef.current;
          if (!reconnectedUserId) {
            return;
          }
          try {
            await connection?.invoke('JoinUserGroup', reconnectedUserId);
          } catch (error) {
            log('Failed to rejoin authoring user group', error);
          }
        });

        connectionRef.current = connection;
        await connection.start();
      }

      await connection.invoke('JoinUserGroup', currentUserId);
    })();

    try {
      await connectionPromiseRef.current;
    } finally {
      connectionPromiseRef.current = null;
    }
  }, [clearPending, log]);

  useEffect(() => {
    if (!user?.id) {
      return;
    }

    void ensureConnected();

    return () => {
      const connection = connectionRef.current;
      connectionRef.current = null;
      connectionPromiseRef.current = null;

      if (backpressureTimerRef.current) {
        clearTimeout(backpressureTimerRef.current);
        backpressureTimerRef.current = null;
      }

      pendingRef.current.forEach((pending) => {
        clearTimeout(pending.timeout);
        pending.reject(new Error('AI authoring connection closed.'));
      });
      pendingRef.current.clear();

      if (connection) {
        connection.stop().catch(() => undefined);
      }
    };
  }, [ensureConnected, user?.id]);

  const requestOperation = useCallback(async <T>(
    sendRequest: (operationId: string) => Promise<ApiResponse<AiOperationAcceptedResponse>>,
    mapResult: (event: AiOperationCompletedEvent) => T,
    timeoutMessage: string,
  ): Promise<T> => {
    await ensureConnected();

    const operationId = createOperationId();

    return await new Promise<T>((resolve, reject) => {
      const timeout = setTimeout(() => {
        pendingRef.current.delete(operationId);
        reject(new Error(timeoutMessage));
      }, OPERATION_TIMEOUT_MS);

      pendingRef.current.set(operationId, {
        timeout,
        resolve,
        reject,
        mapResult,
      });

      void sendRequest(operationId)
        .then((response) => {
          if (!response.success || !response.data) {
            const pending = clearPending(operationId);
            pending?.reject(new Error(response.message ?? 'AI operation request failed.'));
            return;
          }

          // Check for backpressure signal from the backend
          const rawData = response.data as Record<string, unknown>;
          if (rawData.isBackpressured) {
            log('[AI] Backpressure warning: AI is currently under heavy load');
            if (backpressureTimerRef.current) {
              clearTimeout(backpressureTimerRef.current);
            }
            setIsBackpressured(true);
            backpressureTimerRef.current = setTimeout(() => {
              backpressureTimerRef.current = null;
              setIsBackpressured(false);
            }, 10_000);
          }

          const actualOperationId = response.data.operationId || operationId;
          if (actualOperationId !== operationId) {
            const pending = pendingRef.current.get(operationId);
            if (pending) {
              pendingRef.current.delete(operationId);
              pendingRef.current.set(actualOperationId, pending);
            }
          }
        })
        .catch((error) => {
          const pending = clearPending(operationId);
          pending?.reject(new Error(getErrorMessage(error, 'AI operation request failed.')));
        });
    });
  }, [clearPending, ensureConnected, log]);

  const generateTitle = useCallback((content: string, signal?: AbortSignal) =>
    requestOperation(
      (operationId) => aiApi.generateTitle(content, signal, operationId),
      (event) => expectStringResult(event, 'ai.title.generation.completed'),
      'AI title generation timed out.',
    ),
  [requestOperation]);

  const generateExcerpt = useCallback((content: string, signal?: AbortSignal) =>
    requestOperation(
      (operationId) => aiApi.generateExcerpt(content, signal, operationId),
      (event) => expectStringResult(event, 'ai.excerpt.generation.completed'),
      'AI excerpt generation timed out.',
    ),
  [requestOperation]);

  const generateTags = useCallback((content: string, signal?: AbortSignal) =>
    requestOperation(
      (operationId) => aiApi.generateTags(content, signal, operationId),
      (event) => expectStringArrayResult(event, 'ai.tags.generation.completed'),
      'AI tag generation timed out.',
    ),
  [requestOperation]);

  const generateSummary = useCallback((postId: string, maxSentences = 3, language = 'tr') =>
    requestOperation(
      (operationId) => postsApi.generateAiSummary(postId, maxSentences, language, operationId),
      (event) => expectStringResult(event, 'ai.summarize.completed'),
      'AI summary generation timed out.',
    ),
  [requestOperation]);

  return {
    generateTitle,
    generateExcerpt,
    generateTags,
    generateSummary,
    isBackpressured,
  };
}
