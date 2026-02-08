import { useEffect, useRef, useCallback } from 'react';
import * as signalR from '@microsoft/signalr';
import { useChatStore } from '@/stores/chat-store';
import type { ChatMessageReceivedEvent, WebSearchSource } from '@/types';
import { HUB_URL } from '@/lib/env';

interface UseArticleChatOptions {
  /** Enable debug logging */
  debug?: boolean;
  /** Callback when a message is received */
  onMessageReceived?: (message: ChatMessageReceivedEvent) => void;
}

/**
 * React hook for article chat with SignalR integration.
 *
 * Manages:
 * - SignalR connection for real-time chat responses
 * - Session management
 * - Message sending and receiving
 *
 * Usage:
 * ```tsx
 * const { sendMessage, isLoading, messages, isConnected } = useArticleChat(postId);
 * ```
 */
export function useArticleChat(postId: string, options: UseArticleChatOptions = {}) {
  const { debug = false, onMessageReceived } = options;

  const connectionRef = useRef<signalR.HubConnection | null>(null);
  const onMessageReceivedRef = useRef(onMessageReceived);
  
  // Use ref for addAssistantMessage to avoid reconnection when store updates
  const addAssistantMessageRef = useRef<typeof addAssistantMessage | null>(null);

  const {
    sessionId,
    messages,
    isLoading,
    loadingState,
    error,
    isOpen,
    setOpen,
    setPostId,
    sendMessage: storeSendMessage,
    addAssistantMessage,
    clearChat,
    setLoading,
  } = useChatStore();

  // Keep refs updated
  useEffect(() => {
    onMessageReceivedRef.current = onMessageReceived;
  }, [onMessageReceived]);

  useEffect(() => {
    addAssistantMessageRef.current = addAssistantMessage;
  }, [addAssistantMessage]);

  const log = useCallback(
    (..._args: unknown[]) => {
      // logging disabled
    },
    []
  );

  // Set post ID when component mounts
  useEffect(() => {
    if (postId) {
      setPostId(postId);
    }
  }, [postId, setPostId]);

  // Connect to SignalR hub
  useEffect(() => {
    let connection: signalR.HubConnection | null = null;
    let isMounted = true;

    const connect = async () => {
      try {
        log('Connecting to SignalR hub for chat...');

        connection = new signalR.HubConnectionBuilder()
          .withUrl(HUB_URL, {
            withCredentials: true,
          })
          .withAutomaticReconnect()
          .configureLogging(debug ? signalR.LogLevel.Debug : signalR.LogLevel.None)
          .build();

        // Listen for chat message received events
        // Note: SignalR may use either PascalCase or camelCase depending on configuration
        const handleChatMessage = (event: Record<string, unknown>) => {
          if (!isMounted) return;
          log('📨 Received chat message event:', event);

          // Handle both PascalCase and camelCase property names from backend
          const eventSessionId = (event.sessionId || event.SessionId) as string | undefined;
          const eventResponse = (event.response || event.Response) as string | undefined;
          const eventIsWebSearch = (event.isWebSearchResult ?? event.IsWebSearchResult ?? false) as boolean;
          const eventSources = (event.sources || event.Sources) as WebSearchSource[] | undefined;

          // Check if this message is for our session
          const currentSessionId = useChatStore.getState().sessionId;

          // If currentSessionId is null (first message), we should accept if it matches the one we just got from API
          // But since we can't easily know that here without passing it, let's trust the event for now if we don't have a session yet
          // OR if it matches exactly

          if (eventSessionId && (eventSessionId === currentSessionId || !currentSessionId)) {
            log('✅ Event matches or new session, updating state');

            // If we don't have a session ID yet, set it now
            if (!currentSessionId && eventSessionId) {
                useChatStore.getState().setSessionId(eventSessionId);
            }

            addAssistantMessageRef.current?.(
              eventResponse || '',
              eventIsWebSearch,
              eventSources
            );

            onMessageReceivedRef.current?.(event as unknown as ChatMessageReceivedEvent);
          }
        };

        // Listen on all casing variants (SignalR can lowercase method names)
        connection.on('ChatMessageReceived', handleChatMessage);
        connection.on('chatMessageReceived', handleChatMessage);
        connection.on('chatmessagereceived', handleChatMessage);
        
        // Also listen for AI analysis completed events
        const handleAIAnalysis = (event: Record<string, unknown>) => {
          if (!isMounted) return;
          log('Received AI analysis event:', event);
          // Handle AI analysis events if needed
        };
        
        connection.on('AIAnalysisCompleted', handleAIAnalysis);
        connection.on('aiAnalysisCompleted', handleAIAnalysis);
        connection.on('aianalysiscompleted', handleAIAnalysis);

        connection.onreconnecting(() => log('SignalR reconnecting...'));
        connection.onreconnected(() => log('SignalR reconnected'));
        connection.onclose((error) => log('SignalR connection closed', error));

        connectionRef.current = connection;

        await connection.start();

        if (isMounted) {
          log('Connected to SignalR hub');

          // Join chat session group for targeted notifications
          const currentSessionId = useChatStore.getState().sessionId;
          if (currentSessionId) {
            try {
              await connection.invoke('JoinChatSessionGroup', currentSessionId);
              log(`Joined chat session group: ${currentSessionId}`);
            } catch (err) {
              log('Failed to join chat session group:', err);
            }
          }
        }
      } catch (error) {
        if (!isMounted) return;

        const errorMessage = error instanceof Error ? error.message : String(error);

        // Suppress common benign errors (connection issues when backend is not running)
        const isBenignError =
          errorMessage.includes('stop()') ||
          errorMessage.includes('HttpConnection') ||
          errorMessage.includes('abort') ||
          errorMessage.includes('WebSocket failed') ||
          errorMessage.includes('Failed to fetch') ||
          errorMessage.includes('Failed to complete negotiation');

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
  }, [debug, log]);

  /**
   * Send a message to the chat
   */
  const sendMessage = useCallback(
    async (content: string, enableWebSearch = false) => {
      if (!postId) {
        return;
      }

      await storeSendMessage(postId, content, enableWebSearch);
    },
    [postId, storeSendMessage]
  );

  /**
   * Open the chat panel
   */
  const openChat = useCallback(() => {
    setOpen(true);
  }, [setOpen]);

  /**
   * Close the chat panel
   */
  const closeChat = useCallback(() => {
    setOpen(false);
  }, [setOpen]);

  /**
   * Toggle the chat panel
   */
  const toggleChat = useCallback(() => {
    setOpen(!isOpen);
  }, [isOpen, setOpen]);

  /**
   * Check if SignalR is connected
   */
  const isConnected = connectionRef.current?.state === signalR.HubConnectionState.Connected;

  return {
    // State
    sessionId,
    messages,
    isLoading,
    loadingState,
    error,
    isOpen,
    isConnected,

    // Actions
    sendMessage,
    openChat,
    closeChat,
    toggleChat,
    clearChat,
    setLoading,
  };
}
