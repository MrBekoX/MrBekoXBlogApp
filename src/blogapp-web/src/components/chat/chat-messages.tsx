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

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollIntoView({ behavior: 'smooth' });
    }
  }, [messages, isLoading]);

  const getLoadingInfo = () => {
    switch (loadingState) {
      case 'analyzing':
        return { icon: Brain, text: 'makale analiz ediliyor...' };
      case 'web-search':
        return { icon: Globe, text: 'web araması yapılıyor...' };
      case 'generating-summary':
        return { icon: FileText, text: 'özet oluşturuluyor...' };
      default:
        return { icon: Brain, text: 'düşünüyorum...' };
    }
  };

  return (
    <div className="flex-1 overflow-y-auto ide-scrollbar p-4 space-y-5 font-mono text-sm bg-ide-bg">
      {messages.map((message) => (
        <ChatMessageBubble key={message.id} message={message} />
      ))}

      {/* Loading indicator — terminal spinner */}
      {isLoading && (() => {
        const { icon: Icon, text } = getLoadingInfo();
        return (
          <div className="flex items-center gap-2 text-xs text-gray-500 pl-4">
            <Loader2 className="w-3 h-3 animate-spin text-ide-primary" />
            <Icon className="w-3 h-3" />
            <span>{text}</span>
            <span className="cursor-blink text-ide-primary">_</span>
          </div>
        );
      })()}

      <div ref={scrollRef} />
    </div>
  );
}
