'use client';

import { User, Bot, Globe } from 'lucide-react';
import { cn } from '@/lib/utils';
import type { ChatMessage } from '@/types';
import { WebSearchSources } from './web-search-sources';
import { MarkdownRenderer } from '@/components/markdown-renderer';

interface ChatMessageBubbleProps {
  message: ChatMessage;
}

export function ChatMessageBubble({ message }: ChatMessageBubbleProps) {
  const isUser = message.role === 'user';
  const isAssistant = message.role === 'assistant';

  return (
    <div
      className={cn(
        'flex gap-3',
        isUser && 'flex-row-reverse'
      )}
    >
      {/* Avatar */}
      <div
        className={cn(
          'flex-shrink-0 w-8 h-8 rounded-full flex items-center justify-center',
          isUser ? 'bg-primary text-primary-foreground' : 'bg-muted'
        )}
      >
        {isUser ? (
          <User className="h-4 w-4" />
        ) : message.isWebSearchResult ? (
          <Globe className="h-4 w-4" />
        ) : (
          <Bot className="h-4 w-4" />
        )}
      </div>

      {/* Message content */}
      <div
        className={cn(
          'flex flex-col gap-1 max-w-[85%]',
          isUser && 'items-end'
        )}
      >
        <div
          className={cn(
            'rounded-2xl px-4 py-3 text-sm overflow-hidden',
            isUser
              ? 'bg-primary text-primary-foreground rounded-tr-sm'
              : 'bg-muted rounded-tl-sm'
          )}
        >
          {/* Web search indicator */}
          {isAssistant && message.isWebSearchResult && (
            <div className="flex items-center gap-1 text-xs text-muted-foreground mb-2">
              <Globe className="h-3 w-3" />
              <span>Web aramasindan</span>
            </div>
          )}

          {/* Message content - Markdown rendering for assistant */}
          {isAssistant ? (
            <MarkdownRenderer
              content={message.content}
              proseSize="sm"
              forChat={true}
              className="!p-0 !m-0 !max-w-none !bg-transparent !text-current"
            />
          ) : (
            <p className="whitespace-pre-wrap break-words">{message.content}</p>
          )}
        </div>

        {/* Web search sources */}
        {isAssistant && message.isWebSearchResult && message.sources && (
          <WebSearchSources sources={message.sources} />
        )}

        {/* Timestamp */}
        <span className="text-xs text-muted-foreground px-1">
          {formatTime(message.timestamp)}
        </span>
      </div>
    </div>
  );
}

function formatTime(date: Date): string {
  return new Intl.DateTimeFormat('tr-TR', {
    hour: '2-digit',
    minute: '2-digit',
  }).format(new Date(date));
}
