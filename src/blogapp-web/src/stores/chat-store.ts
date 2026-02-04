import { create } from 'zustand';
import type { ChatMessage, ChatHistoryItem, WebSearchSource } from '@/types';
import { chatApi, getErrorMessage } from '@/lib/api';

export type LoadingState = 'idle' | 'analyzing' | 'web-search' | 'generating-summary';

interface ChatState {
  // State
  sessionId: string | null;
  messages: ChatMessage[];
  isLoading: boolean;
  loadingState: LoadingState;
  error: string | null;
  isOpen: boolean;
  currentPostId: string | null;

  // Actions
  setSessionId: (sessionId: string) => void;
  setOpen: (isOpen: boolean) => void;
  setPostId: (postId: string) => void;
  sendMessage: (postId: string, content: string, enableWebSearch?: boolean) => Promise<void>;
  addMessage: (message: ChatMessage) => void;
  addAssistantMessage: (
    content: string,
    isWebSearchResult?: boolean,
    sources?: WebSearchSource[]
  ) => void;
  clearChat: () => void;
  setError: (error: string | null) => void;
  setLoading: (isLoading: boolean, loadingState?: LoadingState) => void;
}

export const useChatStore = create<ChatState>((set, get) => ({
  // Initial state
  sessionId: null,
  messages: [],
  isLoading: false,
  loadingState: 'idle',
  error: null,
  isOpen: false,
  currentPostId: null,

  // Actions
  setSessionId: (sessionId) => set({ sessionId }),

  setOpen: (isOpen) => set({ isOpen }),

  setPostId: (postId) => {
    const currentPostId = get().currentPostId;
    // Clear messages if switching to a different post
    if (currentPostId && currentPostId !== postId) {
      set({
        currentPostId: postId,
        messages: [],
        sessionId: null,
        error: null,
      });
    } else {
      set({ currentPostId: postId });
    }
  },

  sendMessage: async (postId, content, enableWebSearch = false) => {
    const { messages, sessionId } = get();

    // Determine loading state
    let loadingState: LoadingState = 'analyzing';

    // Check if this is a summary request
    const summaryTriggers = [
      'bu makalenin özetini oluştur',
      'makalenin özetini oluştur',
      'make a summary of this article',
      'summarize this article'
    ];
    const isSummaryRequest = summaryTriggers.some(trigger =>
      content.toLowerCase().includes(trigger)
    );

    if (isSummaryRequest) {
      loadingState = 'generating-summary';
    } else if (enableWebSearch) {
      loadingState = 'web-search';
    }

    // Add user message to state immediately
    const userMessage: ChatMessage = {
      id: crypto.randomUUID(),
      role: 'user',
      content,
      timestamp: new Date(),
    };

    set({
      messages: [...messages, userMessage],
      isLoading: true,
      loadingState,
      error: null,
    });

    try {
      // Build conversation history from existing messages
      const conversationHistory: ChatHistoryItem[] = messages.map((msg) => ({
        role: msg.role,
        content: msg.content,
      }));

      // Send to API
      const response = await chatApi.sendMessage({
        postId,
        message: content,
        sessionId: sessionId || undefined,
        conversationHistory,
        language: 'tr',
        enableWebSearch,
      });

      if (response.data?.sessionId) {
        set({ sessionId: response.data.sessionId });
      }

      // Note: The actual response will come via SignalR
      // isLoading will be set to false when we receive the response
    } catch (error) {
      const errorMessage = getErrorMessage(error, 'Mesaj gonderilemedi');
      set({
        isLoading: false,
        loadingState: 'idle',
        error: errorMessage,
      });
    }
  },

  addMessage: (message) => {
    set((state) => ({
      messages: [...state.messages, message],
    }));
  },

  addAssistantMessage: (content, isWebSearchResult = false, sources) => {
    const assistantMessage: ChatMessage = {
      id: crypto.randomUUID(),
      role: 'assistant',
      content,
      isWebSearchResult,
      sources,
      timestamp: new Date(),
    };

    set((state) => ({
      messages: [...state.messages, assistantMessage],
      isLoading: false,
      loadingState: 'idle',
    }));
  },

  clearChat: () => {
    set({
      messages: [],
      sessionId: null,
      error: null,
      isLoading: false,
      loadingState: 'idle',
    });
  },

  setError: (error) => set({ error }),

  setLoading: (isLoading, loadingState = 'idle') => set({ isLoading, loadingState }),
}));
