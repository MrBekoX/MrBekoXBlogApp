'use client';

import { useEffect, useRef } from 'react';
import { Loader2, Globe, FileText, Brain } from 'lucide-react';
import type { ChatMessage } from '@/types';
import { ChatMessageBubble } from './chat-message-bubble';
import type { LoadingState } from '@/stores/chat-store';

interface ChatMessagesProps {
  messages: ChatMessage[];
  isLoading: boolean;
  loadingState: LoadingState;
}

export function ChatMessages({ messages, isLoading, loadingState }: ChatMessagesProps) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  // Auto-scroll to bottom when new messages arrive
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollIntoView({ behavior: 'smooth' });
    }
  }, [messages, isLoading]);

  const getLoadingMessage = () => {
    switch (loadingState) {
      case 'analyzing':
        return {
          icon: Brain,
          text: 'Makale analiz ediliyor...',
        };
      case 'web-search':
        return {
          icon: Globe,
          text: 'Web araması yapılıyor...',
        };
      case 'generating-summary':
        return {
          icon: FileText,
          text: 'Özet oluşturuluyor...',
        };
      default:
        return {
          icon: Brain,
          text: 'Düşünüyorum...',
        };
    }
  };

  return (
    <div
      ref={containerRef}
      className="flex-1 overflow-y-auto p-4 space-y-4"
    >
      {messages.map((message) => (
        <ChatMessageBubble key={message.id} message={message} />
      ))}

      {isLoading && (() => {
        const { icon: Icon, text } = getLoadingMessage();
        return (
          <div className="flex items-center gap-2 text-muted-foreground">
            <div className="flex items-center justify-center w-8 h-8 rounded-full bg-primary/10">
              <Loader2 className="h-4 w-4 animate-spin" />
            </div>
            <Icon className="h-4 w-4" />
            <span className="text-sm">{text}</span>
          </div>
        );
      })()}

      {/* Scroll anchor */}
      <div ref={scrollRef} />
    </div>
  );
}
