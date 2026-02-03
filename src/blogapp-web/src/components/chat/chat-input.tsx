'use client';

import React, { useState, KeyboardEvent, useEffect } from 'react';
import { Send, FileText, Globe, Bot } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { cn } from '@/lib/utils';
import { AgentType } from '@/types';

interface ChatInputProps {
  onSend: (message: string, agentType?: AgentType) => void;
  isLoading: boolean;
  onOpenAgentDialog: () => void;
}

export function ChatInput({
  onSend,
  isLoading,
  onOpenAgentDialog,
}: ChatInputProps) {
  const [input, setInput] = useState('');
  const [agentType, setAgentType] = useState<AgentType>('normal');

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
      // AI Summary - direkt sabit mesaj gönder
      onSend('Bu makalenin özetini oluştur', 'normal');
    } else if (selectedAgentType === 'web-search' && defaultMessage) {
      if (agentType === 'web-search') {
        // Zaten aktifse pasif hale getir
        setAgentType('normal');
        // Eğer input sadece default mesaj ise temizle
        if (input === defaultMessage) {
          setInput('');
        }
      } else {
        // Aktif değilse aktif et
        setInput(defaultMessage);
        setAgentType('web-search');
      }
    }
  };

  // Placeholder'ı agent type'a göre değiştir
  const getPlaceholder = () => {
    if (agentType === 'web-search') {
      return 'Web araması için sorunuzu düzenleyin...';
    }
    return 'Bir soru sorun...';
  };

  // Input ref'i ile otomatik focus
  const textareaRef = React.useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    if (agentType === 'web-search' && input.trim()) {
      textareaRef.current?.focus();
    }
  }, [agentType, input]);

  return (
    <div className="border-t p-4 flex-shrink-0">
      {/* Quick Action Buttons */}
      <div className="flex gap-2 mb-3">
        <Button
          variant="outline"
          size="sm"
          onClick={() => handleQuickAction('summary')}
          disabled={isLoading}
          className="flex-1 h-9 text-xs"
        >
          <FileText className="h-3.5 w-3.5 mr-1.5" />
          AI Özet
        </Button>
        <Button
          variant="outline"
          size="sm"
          onClick={() => handleQuickAction('web-search', 'Makale hakkında detaylı bilgi ver')}
          disabled={isLoading}
          className={cn(
            'flex-1 h-9 text-xs',
            agentType === 'web-search' && 'bg-primary text-primary-foreground'
          )}
        >
          <Globe className="h-3.5 w-3.5 mr-1.5" />
          Web&apos;de Ara
        </Button>
        <Button
          variant="outline"
          size="sm"
          onClick={onOpenAgentDialog}
          disabled={isLoading}
          className="flex-1 h-9 text-xs"
        >
          <Bot className="h-3.5 w-3.5 mr-1.5" />
          Diğer
        </Button>
      </div>

      {/* Agent Type Indicator */}
      {agentType === 'web-search' && (
        <p className="text-xs text-blue-600 dark:text-blue-400 mb-2 flex items-center gap-1">
          <Globe className="h-3 w-3" />
          Web arama modu aktif
        </p>
      )}

      <div className="flex gap-2 items-end">
        <div className="flex-1 relative">
          <Textarea
            ref={textareaRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={getPlaceholder()}
            disabled={isLoading}
            className={cn(
              "min-h-[44px] max-h-[120px] resize-none pr-10",
              agentType === 'web-search' && 'border-blue-500 focus:border-blue-500'
            )}
            rows={1}
          />
        </div>

        <Button
          onClick={handleSend}
          disabled={!input.trim() || isLoading}
          size="icon"
          className={cn(
            "h-9 w-9",
            agentType === 'web-search' && 'bg-blue-600 hover:bg-blue-700'
          )}
        >
          <Send className="h-4 w-4" />
        </Button>
      </div>
    </div>
  );
}
