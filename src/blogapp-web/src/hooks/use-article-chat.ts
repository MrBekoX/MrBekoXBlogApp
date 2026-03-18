import { useEffect, useRef, useCallback, useState } from 'react';
import * as signalR from '@microsoft/signalr';
import { useChatStore } from '@/stores/chat-store';
import type { ChatMessageReceivedEvent, WebSearchSource } from '@/types';
import { CHAT_EVENTS_HUB_URL, TURNSTILE_SITE_KEY } from '@/lib/env';

const CHAT_TIMEOUT_MS = 60_000;

type AddAssistantMessage = (content: string, isWebSearchResult?: boolean, sources?: WebSearchSource[], operationId?: string) => void;

interface UseArticleChatOptions {
  debug?: boolean;
  onMessageReceived?: (message: ChatMessageReceivedEvent) => void;
}

export function useArticleChat(postId: string, options: UseArticleChatOptions = {}) {
  const { debug = false, onMessageReceived } = options;

  const connectionRef = useRef<signalR.HubConnection | null>(null);
  const chatTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [isConnected, setIsConnected] = useState(false);
  const onMessageReceivedRef = useRef(onMessageReceived);
  const sessionTokenRef = useRef<string | null>(null);
  const addAssistantMessageRef = useRef<AddAssistantMessage | null>(null);

  const {
    sessionId,
    sessionToken,
    messages,
    isLoading,
    loadingState,
    error,
    isOpen,
    turnstileRequired,
    turnstileChallengeKey,
    setOpen,
    setPostId,
    sendMessage: storeSendMessage,
    addAssistantMessage,
    clearChat,
    setLoading,
    submitTurnstileToken,
  } = useChatStore();

  useEffect(() => {
    onMessageReceivedRef.current = onMessageReceived;
  }, [onMessageReceived]);

  useEffect(() => {
    addAssistantMessageRef.current = addAssistantMessage;
  }, [addAssistantMessage]);

  useEffect(() => {
    sessionTokenRef.current = sessionToken;
  }, [sessionToken]);

  useEffect(() => {
    if (postId) {
      setPostId(postId);
    }
  }, [postId, setPostId]);

  const log = useCallback((message: string) => {
    if (debug) {
      console.debug(message);
    }
  }, [debug]);

  useEffect(() => {
    if (!sessionId || !sessionToken) {
      if (connectionRef.current) {
        connectionRef.current.stop().catch(() => undefined);
        connectionRef.current = null;
      }
      return;
    }

    let connection = connectionRef.current;
    let isMounted = true;

    const handleChatMessage = (event: Record<string, unknown>) => {
      if (!isMounted) return;

      const eventSessionId = (event.sessionId || event.SessionId) as string | undefined;
      const eventResponse = (event.response || event.Response) as string | undefined;
      const eventIsWebSearch = (event.isWebSearchResult ?? event.IsWebSearchResult ?? false) as boolean;
      const eventSources = (event.sources || event.Sources) as WebSearchSource[] | undefined;
      const eventOperationId = (event.operationId || event.OperationId) as string | undefined;
      const currentSessionId = useChatStore.getState().sessionId;

      if (eventSessionId && eventSessionId === currentSessionId) {
        addAssistantMessageRef.current?.(
          eventResponse || '',
          eventIsWebSearch,
          eventSources,
          eventOperationId,
        );
        // Clear chat timeout since a complete response arrived
        if (chatTimeoutRef.current) {
          clearTimeout(chatTimeoutRef.current);
          chatTimeoutRef.current = null;
        }
        onMessageReceivedRef.current?.(event as unknown as ChatMessageReceivedEvent);
      }
    };

    const handleChatChunk = (event: Record<string, unknown>) => {
      if (!isMounted) return;
      const eventSessionId = (event.sessionId || event.SessionId) as string | undefined;
      const currentSessionId = useChatStore.getState().sessionId;
      if (eventSessionId && eventSessionId === currentSessionId) {
        // Clear chat timeout on first chunk — response has started arriving
        if (chatTimeoutRef.current) {
          clearTimeout(chatTimeoutRef.current);
          chatTimeoutRef.current = null;
        }
        useChatStore.getState().appendChunkToLastAssistantMessage(
          (event.operationId || event.OperationId) as string | undefined,
          ((event.chunk || event.Chunk) as string | undefined) || '',
          Number(event.sequence || event.Sequence || 0),
          Boolean(event.isFinal ?? event.IsFinal ?? false),
        );
      }
    };

    const handleChatCompleted = (event: Record<string, unknown>) => {
      if (!isMounted) return;
      const eventSessionId = (event.sessionId || event.SessionId) as string | undefined;
      const eventOperationId = (event.operationId || event.OperationId) as string | undefined;
      if (eventSessionId && eventSessionId === useChatStore.getState().sessionId) {
        // Clear chat timeout since stream completed
        if (chatTimeoutRef.current) {
          clearTimeout(chatTimeoutRef.current);
          chatTimeoutRef.current = null;
        }
        useChatStore.getState().markChunkStreamCompleted(eventOperationId);
      }
    };

    const ensureConnection = async () => {
      if (connectionRef.current?.state === signalR.HubConnectionState.Connected) {
        // Re-register handlers with the current closure so isMounted stays valid
        // across sessionToken refreshes that re-run this effect.
        connectionRef.current.off('ChatMessageReceived');
        connectionRef.current.off('chatMessageReceived');
        connectionRef.current.off('chatmessagereceived');
        connectionRef.current.off('ChatChunkReceived');
        connectionRef.current.off('chatChunkReceived');
        connectionRef.current.off('chatchunkreceived');
        connectionRef.current.off('ChatMessageCompleted');
        connectionRef.current.off('chatMessageCompleted');
        connectionRef.current.off('chatmessagecompleted');
        connectionRef.current.on('ChatMessageReceived', handleChatMessage);
        connectionRef.current.on('chatMessageReceived', handleChatMessage);
        connectionRef.current.on('chatmessagereceived', handleChatMessage);
        connectionRef.current.on('ChatChunkReceived', handleChatChunk);
        connectionRef.current.on('chatChunkReceived', handleChatChunk);
        connectionRef.current.on('chatchunkreceived', handleChatChunk);
        connectionRef.current.on('ChatMessageCompleted', handleChatCompleted);
        connectionRef.current.on('chatMessageCompleted', handleChatCompleted);
        connectionRef.current.on('chatmessagecompleted', handleChatCompleted);
        try {
          await connectionRef.current.invoke('JoinChatSessionGroup', sessionId);
        } catch {
          // Ignore join failures.
        }
        return;
      }

      connection = new signalR.HubConnectionBuilder()
        .withUrl(CHAT_EVENTS_HUB_URL, {
          accessTokenFactory: () => sessionTokenRef.current ?? '',
        })
        .withAutomaticReconnect()
        .configureLogging(signalR.LogLevel.None)
        .build();

      connection.on('ChatMessageReceived', handleChatMessage);
      connection.on('chatMessageReceived', handleChatMessage);
      connection.on('chatmessagereceived', handleChatMessage);
      connection.on('ChatChunkReceived', handleChatChunk);
      connection.on('chatChunkReceived', handleChatChunk);
      connection.on('chatchunkreceived', handleChatChunk);
      connection.on('ChatMessageCompleted', handleChatCompleted);
      connection.on('chatMessageCompleted', handleChatCompleted);
      connection.on('chatmessagecompleted', handleChatCompleted);
      connection.onreconnected(async () => {
        setIsConnected(true);
        try {
          const currentSessionId = useChatStore.getState().sessionId;
          if (currentSessionId) {
            await connection?.invoke('JoinChatSessionGroup', currentSessionId);
          }
        } catch {
          // Ignore rejoin failures.
        }
      });
      connection.onclose(() => {
        setIsConnected(false);
        log('SignalR connection closed');
      });

      await connection.start();
      if (!isMounted) {
        await connection.stop();
        return;
      }

      connectionRef.current = connection;
      setIsConnected(true);
      await connection.invoke('JoinChatSessionGroup', sessionId);
    };

    void ensureConnection();

    return () => {
      isMounted = false;
    };
  }, [sessionId, sessionToken, log]);

  useEffect(() => {
    return () => {
      if (chatTimeoutRef.current) {
        clearTimeout(chatTimeoutRef.current);
        chatTimeoutRef.current = null;
      }
      if (connectionRef.current) {
        connectionRef.current.stop().catch(() => undefined);
      }
      connectionRef.current = null;
    };
  }, []);

  const sendMessage = useCallback(async (content: string, enableWebSearch = false) => {
    if (!postId) {
      return;
    }

    // Clear any previous pending timeout before starting a new request
    if (chatTimeoutRef.current) {
      clearTimeout(chatTimeoutRef.current);
      chatTimeoutRef.current = null;
    }

    await storeSendMessage(postId, content, enableWebSearch);

    // Start 60s timeout — if no SignalR response arrives, show a fallback message
    chatTimeoutRef.current = setTimeout(() => {
      chatTimeoutRef.current = null;
      const state = useChatStore.getState();
      if (state.isLoading) {
        addAssistantMessage('Yanıt alınamadı, lütfen tekrar deneyin.');
        setLoading(false);
      }
    }, CHAT_TIMEOUT_MS);
  }, [postId, storeSendMessage, addAssistantMessage, setLoading]);

  const solveTurnstileChallenge = useCallback(async (token: string) => {
    await submitTurnstileToken(token);
  }, [submitTurnstileToken]);

  const openChat = useCallback(() => {
    setOpen(true);
  }, [setOpen]);

  const closeChat = useCallback(() => {
    setOpen(false);
  }, [setOpen]);

  const toggleChat = useCallback(() => {
    setOpen(!isOpen);
  }, [isOpen, setOpen]);


  return {
    sessionId,
    messages,
    isLoading,
    loadingState,
    error,
    isOpen,
    isConnected,
    turnstileRequired,
    turnstileChallengeKey,
    turnstileSiteKey: TURNSTILE_SITE_KEY,
    sendMessage,
    solveTurnstileChallenge,
    openChat,
    closeChat,
    toggleChat,
    clearChat,
    setLoading,
  };
}


