import { useCallback, useEffect, useRef, useState } from 'react';
import * as signalR from '@microsoft/signalr';
import { useAuthStore } from '@/stores/auth-store';
import { AUTHORING_EVENTS_HUB_URL } from '@/lib/env';
import { getErrorMessage, postsApi } from '@/lib/api';
import { createOperationId } from '@/lib/idempotency';

export interface AiAnalysisResult {
  postId: string;
  correlationId: string;
  operationId?: string;
  summary: string;
  keywords: string[];
  seoDescription: string;
  readingTime: number;
  sentiment: string;
  timestamp: string;
}

export interface AiAnalysisState {
  isLoading: boolean;
  result: AiAnalysisResult | null;
  error: string | null;
  correlationId: string | null;
  operationId: string | null;
}

interface UseAiAnalysisOptions {
  onComplete?: (result: AiAnalysisResult) => void;
  onError?: (error: string) => void;
  debug?: boolean;
}

function normalizeAnalysisEvent(event: Record<string, unknown>): AiAnalysisResult {
  const keywords = event.keywords ?? event.Keywords;

  return {
    postId: String(event.postId ?? event.PostId ?? ''),
    correlationId: String(event.correlationId ?? event.CorrelationId ?? ''),
    operationId: (event.operationId ?? event.OperationId) as string | undefined,
    summary: String(event.summary ?? event.Summary ?? ''),
    keywords: Array.isArray(keywords) ? keywords.map((item) => String(item)) : [],
    seoDescription: String(event.seoDescription ?? event.SeoDescription ?? ''),
    readingTime: Number(event.readingTime ?? event.ReadingTime ?? 0),
    sentiment: String(event.sentiment ?? event.Sentiment ?? ''),
    timestamp: String(event.timestamp ?? event.Timestamp ?? new Date().toISOString()),
  };
}

export function useAiAnalysis(postId: string, options: UseAiAnalysisOptions = {}) {
  const { onComplete, onError, debug = false } = options;
  const [state, setState] = useState<AiAnalysisState>({
    isLoading: false,
    result: null,
    error: null,
    correlationId: null,
    operationId: null,
  });

  const connectionRef = useRef<signalR.HubConnection | null>(null);
  const onCompleteRef = useRef(onComplete);
  const onErrorRef = useRef(onError);
  const postIdRef = useRef(postId);
  const activeOperationIdRef = useRef<string | null>(null);
  const completedOperationIdsRef = useRef<Set<string>>(new Set());
  const { user } = useAuthStore();

  useEffect(() => {
    postIdRef.current = postId;
    onCompleteRef.current = onComplete;
    onErrorRef.current = onError;
  }, [onComplete, onError, postId]);

  const log = useCallback((...args: unknown[]) => {
    if (debug) {
      console.debug('[useAiAnalysis]', ...args);
    }
  }, [debug]);

  useEffect(() => {
    if (!user) {
      return;
    }

    let connection: signalR.HubConnection | null = null;
    let isMounted = true;

    const handleAiAnalysisCompleted = (rawEvent: Record<string, unknown>) => {
      if (!isMounted) return;
      const event = normalizeAnalysisEvent(rawEvent);
      if (event.postId !== postIdRef.current) return;

      const activeOperationId = activeOperationIdRef.current;
      if (activeOperationId && event.operationId && event.operationId !== activeOperationId) {
        return;
      }

      if (event.operationId && completedOperationIdsRef.current.has(event.operationId)) {
        return;
      }

      if (event.operationId) {
        completedOperationIdsRef.current.add(event.operationId);
      }

      activeOperationIdRef.current = null;
      setState({
        isLoading: false,
        result: event,
        error: null,
        correlationId: event.correlationId || null,
        operationId: event.operationId ?? null,
      });
      onCompleteRef.current?.(event);
    };

    const connect = async () => {
      try {
        connection = new signalR.HubConnectionBuilder()
          .withUrl(AUTHORING_EVENTS_HUB_URL, {
            withCredentials: true,
            skipNegotiation: true,
            transport: signalR.HttpTransportType.WebSockets,
          })
          .withAutomaticReconnect()
          .configureLogging(signalR.LogLevel.None)
          .build();

        connection.on('AiAnalysisCompleted', handleAiAnalysisCompleted);
        connection.on('aiAnalysisCompleted', handleAiAnalysisCompleted);
        connection.onreconnected(async () => {
          try {
            await connection?.invoke('JoinPostGroup', postIdRef.current);
          } catch {
            // Ignore rejoin failures.
          }
        });

        await connection.start();
        if (!isMounted) {
          await connection.stop();
          return;
        }

        connectionRef.current = connection;
        await connection.invoke('JoinPostGroup', postIdRef.current);
      } catch (error) {
        if (isMounted) {
          log('SignalR connection failed', error);
        }
      }
    };

    void connect();

    return () => {
      isMounted = false;
      completedOperationIdsRef.current.clear();
      if (connection) {
        connection.off('AiAnalysisCompleted', handleAiAnalysisCompleted);
        connection.off('aiAnalysisCompleted', handleAiAnalysisCompleted);
        connection.stop().catch(() => undefined);
      }
      connectionRef.current = null;
    };
  }, [debug, log, user]);

  const requestAnalysis = useCallback(async (language = 'tr', targetRegion = 'TR') => {
    if (!postId) {
      const errorMessage = 'Post ID is required';
      setState((prev) => ({ ...prev, error: errorMessage }));
      onErrorRef.current?.(errorMessage);
      return;
    }

    const requestOperationId = createOperationId();
    activeOperationIdRef.current = requestOperationId;
    completedOperationIdsRef.current.delete(requestOperationId);

    setState({
      isLoading: true,
      result: null,
      error: null,
      correlationId: null,
      operationId: requestOperationId,
    });

    try {
      const response = await postsApi.requestAiAnalysis(postId, {
        language,
        targetRegion,
        operationId: requestOperationId,
      });

      if (!response.success) {
        throw new Error(response.message ?? 'AI analysis request failed');
      }

      const acceptedOperationId = response.data?.operationId ?? requestOperationId;
      activeOperationIdRef.current = acceptedOperationId;
      setState((prev) => ({
        ...prev,
        correlationId: response.data?.correlationId ?? null,
        operationId: acceptedOperationId,
      }));
    } catch (error) {
      activeOperationIdRef.current = null;
      const errorMessage = getErrorMessage(error, 'Failed to request AI analysis');
      setState({
        isLoading: false,
        result: null,
        error: errorMessage,
        correlationId: null,
        operationId: null,
      });
      onErrorRef.current?.(errorMessage);
    }
  }, [postId]);

  const reset = useCallback(() => {
    activeOperationIdRef.current = null;
    completedOperationIdsRef.current.clear();
    setState({
      isLoading: false,
      result: null,
      error: null,
      correlationId: null,
      operationId: null,
    });
  }, []);

  return {
    requestAnalysis,
    reset,
    isLoading: state.isLoading,
    result: state.result,
    error: state.error,
    correlationId: state.correlationId,
    operationId: state.operationId,
  };
}

export function useRequestAiAnalysis() {
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const requestAnalysis = useCallback(async (
    postId: string,
    language = 'tr',
    targetRegion = 'TR',
  ) => {
    setIsLoading(true);
    setError(null);

    try {
      const operationId = createOperationId();
      const response = await postsApi.requestAiAnalysis(postId, {
        language,
        targetRegion,
        operationId,
      });

      if (!response.success) {
        throw new Error(response.message ?? 'AI analysis request failed');
      }

      return response.data;
    } catch (err) {
      setError(getErrorMessage(err, 'Failed to request AI analysis'));
      throw err;
    } finally {
      setIsLoading(false);
    }
  }, []);

  return { requestAnalysis, isLoading, error };
}
