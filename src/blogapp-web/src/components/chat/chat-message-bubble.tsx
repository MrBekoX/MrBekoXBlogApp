'use client';

import { Globe } from 'lucide-react';
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
    <div className="space-y-1">
      {isUser ? (
        /* User message — terminal input line */
        <div className="flex items-start gap-2 text-sm font-mono">
          <span className="text-ide-primary shrink-0 mt-0.5">$</span>
          <p className="text-white break-words whitespace-pre-wrap leading-relaxed">
            {message.content}
          </p>
        </div>
      ) : (
        /* AI response — terminal output */
        <div className="pl-4 border-l border-ide-border/50 space-y-1">
          {/* Web search badge */}
          {isAssistant && message.isWebSearchResult && (
            <div className="flex items-center gap-1.5 text-[10px] text-blue-400 mb-1">
              <Globe className="w-3 h-3" />
              <span>web aramasindan</span>
            </div>
          )}

          {/* AI output via MarkdownRenderer */}
          <div className="text-gray-300">
            <MarkdownRenderer
              content={message.content}
              proseSize="sm"
              forChat={true}
              className="!p-0 !m-0 !max-w-none"
            />
          </div>

          {/* Web search sources */}
          {isAssistant && message.isWebSearchResult && message.sources && (
            <WebSearchSources sources={message.sources} />
          )}
        </div>
      )}

      {/* Timestamp */}
      <div className={`text-[10px] text-gray-600 font-mono ${isUser ? 'pl-4' : 'pl-4'}`}>
        {formatTime(message.timestamp)}
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
