'use client';

import React, { useState, KeyboardEvent, useEffect } from 'react';
import { Send, FileText, Globe, Bot, Loader2 } from 'lucide-react';
import { cn } from '@/lib/utils';
import { AgentType } from '@/types';

interface ChatInputProps {
  onSend: (message: string, agentType?: AgentType) => void;
  isLoading: boolean;
  onOpenAgentDialog: () => void;
}

export function ChatInput({ onSend, isLoading, onOpenAgentDialog }: ChatInputProps) {
  const [input, setInput] = useState('');
  const [agentType, setAgentType] = useState<AgentType>('normal');
  const textareaRef = React.useRef<HTMLTextAreaElement>(null);

  const handleSend = () => {
    if (!input.trim() || isLoading) return;
    onSend(input.trim(), agentType);
    setInput('');
    setAgentType('normal');
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const handleQuickAction = (selectedAgentType: AgentType, defaultMessage?: string) => {
    if (isLoading) return;
    if (selectedAgentType === 'summary') {
      onSend('Bu makalenin özetini oluştur', 'normal');
    } else if (selectedAgentType === 'web-search' && defaultMessage) {
      if (agentType === 'web-search') {
        setAgentType('normal');
        if (input === defaultMessage) setInput('');
      } else {
        setInput(defaultMessage);
        setAgentType('web-search');
      }
    }
  };

  useEffect(() => {
    if (agentType === 'web-search' && input.trim()) {
      textareaRef.current?.focus();
    }
  }, [agentType, input]);

  const isWebSearch = agentType === 'web-search';

  return (
    <div className="shrink-0 border-t border-ide-border bg-ide-sidebar font-mono">
      {/* Quick action buttons */}
      <div className="flex gap-1 px-3 pt-2.5 pb-1">
        <button
          onClick={() => handleQuickAction('summary')}
          disabled={isLoading}
          className="flex-1 flex items-center justify-center gap-1.5 text-[10px] py-1.5 rounded border border-ide-border text-gray-500 hover:border-ide-primary/50 hover:text-ide-primary transition-colors disabled:opacity-40"
        >
          <FileText className="w-3 h-3" />
          AI Özet
        </button>
        <button
          onClick={() => handleQuickAction('web-search', 'Makale hakkında detaylı bilgi ver')}
          disabled={isLoading}
          className={cn(
            'flex-1 flex items-center justify-center gap-1.5 text-[10px] py-1.5 rounded border transition-colors disabled:opacity-40',
            isWebSearch
              ? 'border-blue-500/70 text-blue-400 bg-blue-500/10'
              : 'border-ide-border text-gray-500 hover:border-blue-500/50 hover:text-blue-400'
          )}
        >
          <Globe className="w-3 h-3" />
          Web Ara
        </button>
        <button
          onClick={onOpenAgentDialog}
          disabled={isLoading}
          className="flex-1 flex items-center justify-center gap-1.5 text-[10px] py-1.5 rounded border border-ide-border text-gray-500 hover:border-ide-primary/50 hover:text-ide-primary transition-colors disabled:opacity-40"
        >
          <Bot className="w-3 h-3" />
          Diğer
        </button>
      </div>

      {/* Web search active indicator */}
      {isWebSearch && (
        <p className="px-3 text-[10px] text-blue-400 flex items-center gap-1 pb-1">
          <Globe className="w-2.5 h-2.5" />
          web arama modu aktif
        </p>
      )}

      {/* Terminal input row */}
      <div className="flex items-end gap-2 px-3 pb-3 pt-1">
        {/* Prompt symbol */}
        <span
          className={cn(
            'text-sm pb-1.5 shrink-0 font-bold',
            isWebSearch ? 'text-blue-400' : 'text-ide-primary'
          )}
        >
          $
        </span>

        {/* Textarea */}
        <textarea
          ref={textareaRef}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={isWebSearch ? 'Web araması için sorunuzu düzenleyin...' : 'Bir soru sorun...'}
          disabled={isLoading}
          rows={1}
          className={cn(
            'flex-1 resize-none bg-transparent text-sm text-white placeholder:text-gray-600 outline-none border-b focus:border-b transition-colors min-h-[28px] max-h-[100px]',
            isWebSearch
              ? 'border-blue-500/50 focus:border-blue-400'
              : 'border-ide-border focus:border-ide-primary/60'
          )}
          style={{ fieldSizing: 'content' } as React.CSSProperties}
        />

        {/* Send button */}
        <button
          onClick={handleSend}
          disabled={!input.trim() || isLoading}
          className={cn(
            'shrink-0 w-7 h-7 flex items-center justify-center rounded transition-colors',
            !input.trim() || isLoading
              ? 'text-gray-600 cursor-not-allowed'
              : isWebSearch
                ? 'text-blue-400 hover:bg-blue-500/20'
                : 'text-ide-primary hover:bg-ide-primary/10'
          )}
        >
          {isLoading ? (
            <Loader2 className="w-3.5 h-3.5 animate-spin" />
          ) : (
            <Send className="w-3.5 h-3.5" />
          )}
        </button>
      </div>
    </div>
  );
}
