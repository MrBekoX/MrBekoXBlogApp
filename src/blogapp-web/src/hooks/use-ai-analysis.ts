import { useEffect, useRef, useCallback, useState } from 'react';
import * as signalR from '@microsoft/signalr';
import { useAuthStore } from '@/stores/auth-store';
import { API_BASE_URL, HUB_URL } from '@/lib/env';

/**
 * AI Analysis result from SignalR notification
 */
export interface AiAnalysisResult {
  postId: string;
  correlationId: string;
  summary: string;
  keywords: string[];
  seoDescription: string;
  readingTime: number;
  sentiment: string;
  timestamp: string;
}

/**
 * State for AI analysis request
 */
export interface AiAnalysisState {
  isLoading: boolean;
  result: AiAnalysisResult | null;
  error: string | null;
  correlationId: string | null;
}

interface UseAiAnalysisOptions {
  /** Callback when analysis completes */
  onComplete?: (result: AiAnalysisResult) => void;
  /** Callback when an error occurs */
  onError?: (error: string) => void;
  /** Enable debug logging */
  debug?: boolean;
}

/**
 * React hook for requesting and receiving AI analysis via SignalR.
 *
 * Usage:
 * ```tsx
 * const { requestAnalysis, isLoading, result, error } = useAiAnalysis(postId);
 *
 * // Request analysis
 * await requestAnalysis();
 *
 * // Result will be set automatically when AI Agent completes
 * ```
 */
export function useAiAnalysis(postId: string, options: UseAiAnalysisOptions = {}) {
  const { onComplete, onError, debug = false } = options;

  const [state, setState] = useState<AiAnalysisState>({
    isLoading: false,
    result: null,
    error: null,
    correlationId: null,
  });

  const connectionRef = useRef<signalR.HubConnection | null>(null);
  const onCompleteRef = useRef(onComplete);
  const onErrorRef = useRef(onError);
  const { user } = useAuthStore();

  // Keep callback refs updated
  useEffect(() => {
    onCompleteRef.current = onComplete;
    onErrorRef.current = onError;
  }, [onComplete, onError]);

  const log = useCallback((..._args: unknown[]) => {
    // logging disabled
  }, []);

  // Connect to SignalR hub
  useEffect(() => {
    // Don't connect if not logged in
    if (!user) return;

    let connection: signalR.HubConnection | null = null;
    let isMounted = true;

    const connect = async () => {
      try {
        log('Connecting to SignalR hub for AI analysis notifications...');

        connection = new signalR.HubConnectionBuilder()
          .withUrl(HUB_URL, {
            withCredentials: true,
            skipNegotiation: true,
            transport: signalR.HttpTransportType.WebSockets,
          })
          .withAutomaticReconnect()
          .configureLogging(debug ? signalR.LogLevel.Debug : signalR.LogLevel.None)
          .build();

        // Listen for AI analysis completed events
        connection.on('AiAnalysisCompleted', (event: AiAnalysisResult) => {
          if (!isMounted) return;
          log('Received AiAnalysisCompleted event:', event);

          if (event.postId === postId) {
            log('Event matches our postId, updating state');
            setState(prev => ({
              ...prev,
              isLoading: false,
              result: event,
              error: null,
            }));
            onCompleteRef.current?.(event);
          }
        });

        connection.onreconnecting(() => log('SignalR reconnecting...'));
        connection.onreconnected(() => log('SignalR reconnected'));
        connection.onclose((error) => log('SignalR connection closed', error));

        connectionRef.current = connection;

        await connection.start();

        if (isMounted) {
          log('Connected to SignalR hub');

          // Join post group for targeted notifications
          try {
            await connection.invoke('JoinPostGroup', postId);
            log(`Joined post group: ${postId}`);
          } catch (err) {
            log('Failed to join post group:', err);
          }
        }

      } catch (error) {
        if (!isMounted) return;

        const errorMessage = error instanceof Error ? error.message : String(error);
        const isBenignError = 
           errorMessage.includes('stop()') || 
           errorMessage.includes('HttpConnection') || 
           errorMessage.includes('abort');

        if (isBenignError) {
           return;
        }
      }
    };

    connect();

    return () => {
      isMounted = false;
      if (connection) {
        connection.stop().catch((err) => { if (process.env.NODE_ENV === 'development') console.error(err); });
      }
      connectionRef.current = null;
    };
  }, [postId, debug, log, user]);

  /**
   * Request AI analysis for the post.
   * Result will be delivered via SignalR when ready.
   */
  const requestAnalysis = useCallback(async (language = 'tr', targetRegion = 'TR') => {
    if (!postId) {
      const errorMsg = 'Post ID is required';
      setState(prev => ({ ...prev, error: errorMsg }));
      onErrorRef.current?.(errorMsg);
      return;
    }

    setState(prev => ({
      ...prev,
      isLoading: true,
      error: null,
      result: null,
    }));

    try {
      log(`Requesting AI analysis for post ${postId}...`);

      const response = await fetch(`${API_BASE_URL}/posts/${postId}/request-ai-analysis`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        credentials: 'include',
        body: JSON.stringify({ language, targetRegion }),
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        const errorMsg = errorData.message || `Request failed with status ${response.status}`;
        throw new Error(errorMsg);
      }

      const data = await response.json();
      log('AI analysis request accepted:', data);

      // Store correlation ID for tracking
      if (data.data?.correlationId) {
        setState(prev => ({
          ...prev,
          correlationId: data.data.correlationId,
        }));
      }

      // Now waiting for SignalR notification...
      // isLoading stays true until we receive the result

    } catch (error) {
      const errorMsg = error instanceof Error ? error.message : 'Failed to request AI analysis';
      setState(prev => ({
        ...prev,
        isLoading: false,
        error: errorMsg,
      }));

      onErrorRef.current?.(errorMsg);
    }
  }, [postId, log]);

  /**
   * Clear the current result and error state
   */
  const reset = useCallback(() => {
    setState({
      isLoading: false,
      result: null,
      error: null,
      correlationId: null,
    });
  }, []);

  return {
    requestAnalysis,
    reset,
    isLoading: state.isLoading,
    result: state.result,
    error: state.error,
    correlationId: state.correlationId,
  };
}

/**
 * Simpler hook that just requests analysis without SignalR.
 * Use this when you don't need real-time updates.
 */
export function useRequestAiAnalysis() {
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  
  const requestAnalysis = useCallback(async (
    postId: string,
    language = 'tr',
    targetRegion = 'TR'
  ) => {
    setIsLoading(true);
    setError(null);

    try {
      const response = await fetch(`${API_BASE_URL}/posts/${postId}/request-ai-analysis`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        credentials: 'include',
        body: JSON.stringify({ language, targetRegion }),
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        throw new Error(errorData.message || `Request failed with status ${response.status}`);
      }

      const data = await response.json();
      return data.data;

    } catch (err) {
      const errorMsg = err instanceof Error ? err.message : 'Failed to request AI analysis';
      setError(errorMsg);
      throw err;

    } finally {
      setIsLoading(false);
    }
  }, []);

  return { requestAnalysis, isLoading, error };
}
