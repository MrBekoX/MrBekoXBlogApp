import axios from 'axios';
import { create } from 'zustand';
import { chatApi, getErrorMessage } from '@/lib/api';
import { getClientFingerprint } from '@/lib/client-fingerprint';
import { createOperationId } from '@/lib/idempotency';
import {
  completeChatChunkTracker,
  createChatChunkTracker,
  enqueueChatChunk,
  type ChatChunkTracker,
} from '@/lib/chat-chunk-buffer';
import type { ApiResponse, ChatMessage, ChatHistoryItem, WebSearchSource } from '@/types';

export type LoadingState = 'idle' | 'analyzing' | 'web-search' | 'generating-summary';

interface PendingChallengeRequest {
  postId: string;
  content: string;
  enableWebSearch: boolean;
  operationId: string;
  conversationHistory: ChatHistoryItem[];
  loadingState: LoadingState;
}

interface ChallengePayload {
  requiresTurnstile?: boolean;
  retryAfterSeconds?: number;
}

interface ChatState {
  sessionId: string | null;
  sessionToken: string | null;
  sessionTokenExpiresAt: string | null;
  messages: ChatMessage[];
  isLoading: boolean;
  loadingState: LoadingState;
  error: string | null;
  isOpen: boolean;
  currentPostId: string | null;
  turnstileRequired: boolean;
  turnstileChallengeKey: number;
  pendingChallengeRequest: PendingChallengeRequest | null;
  _chunkTrackersByOperation: Record<string, ChatChunkTracker>;
  setSessionId: (sessionId: string) => void;
  setSessionAccess: (sessionId: string, sessionToken?: string, sessionTokenExpiresAt?: string) => void;
  setOpen: (isOpen: boolean) => void;
  setPostId: (postId: string) => void;
  sendMessage: (postId: string, content: string, enableWebSearch?: boolean, operationId?: string) => Promise<void>;
  submitTurnstileToken: (token: string) => Promise<void>;
  addMessage: (message: ChatMessage) => void;
  addAssistantMessage: (
    content: string,
    isWebSearchResult?: boolean,
    sources?: WebSearchSource[],
    operationId?: string
  ) => void;
  appendChunkToLastAssistantMessage: (operationId: string | undefined, chunk: string, sequence: number, isFinal: boolean) => void;
  markChunkStreamCompleted: (operationId?: string) => void;
  clearChat: () => void;
  setError: (error: string | null) => void;
  setLoading: (isLoading: boolean, loadingState?: LoadingState) => void;
}

const summaryTriggers = [
  'bu makalenin ozetini olustur',
  'makalenin ozetini olustur',
  'make a summary of this article',
  'summarize this article',
];

function resolveLoadingState(content: string, enableWebSearch: boolean): LoadingState {
  const normalizedContent = content.toLowerCase();
  if (summaryTriggers.some((trigger) => normalizedContent.includes(trigger))) {
    return 'generating-summary';
  }

  if (enableWebSearch) {
    return 'web-search';
  }

  return 'analyzing';
}

function extractChallenge(error: unknown): { message: string; retryAfterSeconds?: number } | null {
  if (!axios.isAxiosError(error)) {
    return null;
  }

  const payload = error.response?.data as ApiResponse<ChallengePayload> | undefined;
  if (!payload?.data?.requiresTurnstile) {
    return null;
  }

  return {
    message: payload.message || payload.errors?.[0] || 'Human verification required before continuing.',
    retryAfterSeconds: payload.data.retryAfterSeconds,
  };
}

function getChunkOperationKey(operationId?: string): string {
  return operationId || '__legacy_chat_stream__';
}

function appendChunkToMessage(messages: ChatMessage[], operationId: string | undefined, appendText: string): ChatMessage[] {
  if (!appendText) {
    return messages;
  }

  const updatedMessages = [...messages];
  const existingIndex = operationId
    ? updatedMessages.findIndex((message) => message.role === 'assistant' && message.operationId === operationId)
    : -1;

  if (existingIndex >= 0) {
    updatedMessages[existingIndex] = {
      ...updatedMessages[existingIndex],
      content: updatedMessages[existingIndex].content + appendText,
    };
    return updatedMessages;
  }

  const lastMessage = updatedMessages[updatedMessages.length - 1];
  if (lastMessage?.role === 'assistant' && !lastMessage.operationId && !operationId) {
    updatedMessages[updatedMessages.length - 1] = {
      ...lastMessage,
      content: lastMessage.content + appendText,
    };
    return updatedMessages;
  }

  updatedMessages.push({
    id: crypto.randomUUID(),
    role: 'assistant',
    content: appendText,
    operationId,
    isWebSearchResult: false,
    sources: undefined,
    timestamp: new Date(),
  });

  return updatedMessages;
}

async function sendChatRequest(
  request: PendingChallengeRequest,
  sessionId: string | null,
  clientFingerprint: string,
  turnstileToken?: string,
) {
  return chatApi.sendMessage({
    postId: request.postId,
    message: request.content,
    operationId: request.operationId,
    sessionId: sessionId || undefined,
    conversationHistory: request.conversationHistory,
    language: 'tr',
    enableWebSearch: request.enableWebSearch,
    clientFingerprint,
    turnstileToken,
  });
}

export const useChatStore = create<ChatState>((set, get) => ({
  sessionId: null,
  sessionToken: null,
  sessionTokenExpiresAt: null,
  messages: [],
  isLoading: false,
  loadingState: 'idle',
  error: null,
  isOpen: false,
  currentPostId: null,
  turnstileRequired: false,
  turnstileChallengeKey: 0,
  pendingChallengeRequest: null,
  _chunkTrackersByOperation: {},

  setSessionId: (sessionId) => set({ sessionId }),

  setSessionAccess: (sessionId, sessionToken, sessionTokenExpiresAt) => set({
    sessionId,
    sessionToken: sessionToken ?? get().sessionToken,
    sessionTokenExpiresAt: sessionTokenExpiresAt ?? get().sessionTokenExpiresAt,
  }),

  setOpen: (isOpen) => set({ isOpen }),

  setPostId: (postId) => {
    const currentPostId = get().currentPostId;
    if (currentPostId && currentPostId !== postId) {
      set({
        currentPostId: postId,
        messages: [],
        sessionId: null,
        sessionToken: null,
        sessionTokenExpiresAt: null,
        error: null,
        turnstileRequired: false,
        pendingChallengeRequest: null,
        _chunkTrackersByOperation: {},
      });
      return;
    }

    set({ currentPostId: postId });
  },

  sendMessage: async (postId, content, enableWebSearch = false, operationId) => {
    const state = get();
    if (state.turnstileRequired && state.pendingChallengeRequest) {
      set({ error: 'Complete human verification before sending another message.' });
      return;
    }

    const requestOperationId = operationId ?? createOperationId();
    const loadingState = resolveLoadingState(content, enableWebSearch);
    const userMessage: ChatMessage = {
      id: crypto.randomUUID(),
      role: 'user',
      content,
      operationId: requestOperationId,
      timestamp: new Date(),
    };

    const conversationHistory: ChatHistoryItem[] = state.messages.map((message) => ({
      role: message.role,
      content: message.content,
    }));

    const pendingRequest: PendingChallengeRequest = {
      postId,
      content,
      enableWebSearch,
      operationId: requestOperationId,
      conversationHistory,
      loadingState,
    };

    set({
      messages: [...state.messages, userMessage],
      isLoading: true,
      loadingState,
      error: null,
      turnstileRequired: false,
      pendingChallengeRequest: null,
    });

    try {
      const clientFingerprint = await getClientFingerprint();
      const response = await sendChatRequest(pendingRequest, get().sessionId, clientFingerprint);

      if (response.data?.sessionId) {
        set({
          sessionId: response.data.sessionId,
          sessionToken: response.data.sessionToken ?? get().sessionToken,
          sessionTokenExpiresAt: response.data.sessionTokenExpiresAt ?? get().sessionTokenExpiresAt,
          turnstileRequired: false,
          pendingChallengeRequest: null,
        });
      }
    } catch (error) {
      const challenge = extractChallenge(error);
      if (challenge) {
        set((currentState) => ({
          isLoading: false,
          loadingState: 'idle',
          error: challenge.message,
          turnstileRequired: true,
          turnstileChallengeKey: currentState.turnstileChallengeKey + 1,
          pendingChallengeRequest: pendingRequest,
        }));
        return;
      }

      set({
        isLoading: false,
        loadingState: 'idle',
        error: getErrorMessage(error, 'Mesaj gonderilemedi'),
      });
    }
  },

  submitTurnstileToken: async (token) => {
    const pendingRequest = get().pendingChallengeRequest;
    if (!pendingRequest) {
      set({ turnstileRequired: false, error: null });
      return;
    }

    set({
      isLoading: true,
      loadingState: pendingRequest.loadingState,
      error: null,
    });

    try {
      const clientFingerprint = await getClientFingerprint();
      const response = await sendChatRequest(pendingRequest, get().sessionId, clientFingerprint, token);

      set({
        turnstileRequired: false,
        pendingChallengeRequest: null,
      });

      if (response.data?.sessionId) {
        set({
          sessionId: response.data.sessionId,
          sessionToken: response.data.sessionToken ?? get().sessionToken,
          sessionTokenExpiresAt: response.data.sessionTokenExpiresAt ?? get().sessionTokenExpiresAt,
        });
      }
    } catch (error) {
      const challenge = extractChallenge(error);
      if (challenge) {
        set((state) => ({
          isLoading: false,
          loadingState: 'idle',
          error: challenge.message,
          turnstileRequired: true,
          turnstileChallengeKey: state.turnstileChallengeKey + 1,
        }));
        return;
      }

      set({
        isLoading: false,
        loadingState: 'idle',
        error: getErrorMessage(error, 'Mesaj gonderilemedi'),
      });
    }
  },

  addMessage: (message) => {
    set((state) => ({ messages: [...state.messages, message] }));
  },

  addAssistantMessage: (content, isWebSearchResult = false, sources, operationId) => {
    set((state) => {
      const operationKey = getChunkOperationKey(operationId);

      // Find existing assistant message with the same operationId
      const existingIndex = operationId
        ? state.messages.findIndex((message) => message.role === 'assistant' && message.operationId === operationId)
        : -1;

      if (existingIndex >= 0) {
        // Existing message found - update it if needed
        const existingMessage = state.messages[existingIndex];
        const updatedMessages = [...state.messages];

        // Only update content if existing message is empty or this is a complete non-chunk response
        // Chunk streaming populates content incrementally, so we don't want to overwrite it
        const shouldUpdateContent = !existingMessage.content || existingMessage.content.trim() === '';

        if (shouldUpdateContent && content) {
          updatedMessages[existingIndex] = {
            ...existingMessage,
            content,
            isWebSearchResult,
            sources: sources ?? existingMessage.sources,
          };
        }

        return {
          messages: updatedMessages,
          isLoading: false,
          loadingState: 'idle',
          turnstileRequired: false,
          pendingChallengeRequest: null,
          _chunkTrackersByOperation: {
            ...state._chunkTrackersByOperation,
            [operationKey]: completeChatChunkTracker(state._chunkTrackersByOperation[operationKey]),
          },
        };
      }

      // No existing message - create new one
      const assistantMessage: ChatMessage = {
        id: crypto.randomUUID(),
        role: 'assistant',
        content,
        operationId,
        isWebSearchResult,
        sources,
        timestamp: new Date(),
      };

      return {
        messages: [...state.messages, assistantMessage],
        isLoading: false,
        loadingState: 'idle',
        turnstileRequired: false,
        pendingChallengeRequest: null,
        _chunkTrackersByOperation: operationId
          ? {
              ...state._chunkTrackersByOperation,
              [operationKey]: completeChatChunkTracker(state._chunkTrackersByOperation[operationKey]),
            }
          : state._chunkTrackersByOperation,
      };
    });
  },

  appendChunkToLastAssistantMessage: (operationId, chunk, sequence, isFinal) => {
    set((state) => {
      const operationKey = getChunkOperationKey(operationId);
      const currentTracker = state._chunkTrackersByOperation[operationKey] ?? createChatChunkTracker();
      const result = enqueueChatChunk(currentTracker, sequence, chunk, isFinal);
      const nextTrackers = {
        ...state._chunkTrackersByOperation,
        [operationKey]: result.tracker,
      };

      if (result.dropped) {
        return {
          _chunkTrackersByOperation: nextTrackers,
          isLoading: result.completed ? false : state.isLoading,
          loadingState: result.completed ? 'idle' : state.loadingState,
        };
      }

      return {
        messages: appendChunkToMessage(state.messages, operationId, result.appendText),
        _chunkTrackersByOperation: nextTrackers,
        isLoading: !result.completed,
        loadingState: result.completed ? 'idle' : state.loadingState,
      };
    });
  },

  markChunkStreamCompleted: (operationId) => {
    set((state) => {
      if (!operationId) {
        return {
          isLoading: false,
          loadingState: 'idle',
        };
      }

      const operationKey = getChunkOperationKey(operationId);
      return {
        _chunkTrackersByOperation: {
          ...state._chunkTrackersByOperation,
          [operationKey]: completeChatChunkTracker(state._chunkTrackersByOperation[operationKey]),
        },
        isLoading: false,
        loadingState: 'idle',
      };
    });
  },

  clearChat: () => {
    set({
      messages: [],
      sessionId: null,
      sessionToken: null,
      sessionTokenExpiresAt: null,
      error: null,
      isLoading: false,
      loadingState: 'idle',
      turnstileRequired: false,
      pendingChallengeRequest: null,
      _chunkTrackersByOperation: {},
    });
  },

  setError: (error) => set({ error }),

  setLoading: (isLoading, loadingState = 'idle') => set({ isLoading, loadingState }),
}));
