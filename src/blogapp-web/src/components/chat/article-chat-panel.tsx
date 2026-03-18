'use client';

import { useCallback, useState } from 'react';
import { Trash2, Terminal, X, ShieldAlert } from 'lucide-react';
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from '@/components/ui/sheet';
import { useArticleChat } from '@/hooks/use-article-chat';
import { ChatMessages } from './chat-messages';
import { ChatInput } from './chat-input';
import { AgentSelectionDialog } from './agent-selection-dialog';
import { TurnstileChallenge } from './turnstile-challenge';
import { AgentType } from '@/types';

interface ArticleChatPanelProps {
  postId: string;
  postTitle: string;
}

export function ArticleChatPanel({ postId, postTitle }: ArticleChatPanelProps) {
  const [agentDialogOpen, setAgentDialogOpen] = useState(false);

  const {
    messages,
    isLoading,
    loadingState,
    error,
    isOpen,
    turnstileRequired,
    turnstileChallengeKey,
    turnstileSiteKey,
    sendMessage,
    solveTurnstileChallenge,
    toggleChat,
    clearChat,
  } = useArticleChat(postId, { debug: false });

  const handleSendMessage = async (content: string, agentType?: AgentType) => {
    if (content.trim()) {
      await sendMessage(content, agentType === 'web-search');
    }
  };

  const handleSelectAgent = (agentType: AgentType) => {
    if (agentType === 'summary') {
      void handleSendMessage('Bu makalenin ozetini olustur', 'normal');
    } else if (agentType === 'web-search') {
      void handleSendMessage('Makale hakkinda detayli bilgi ver', 'web-search');
    }
  };

  const handleTurnstileSolved = useCallback(async (token: string) => {
    await solveTurnstileChallenge(token);
  }, [solveTurnstileChallenge]);

  const handleTurnstileError = useCallback(() => {
    // Backend keeps the challenge active; user can retry by solving the widget again.
  }, []);

  return (
    <Sheet open={isOpen} onOpenChange={toggleChat}>
      <SheetTrigger asChild>
        <button
          aria-label="AI terminal panelini ac"
          className="fixed bottom-6 right-6 z-50 flex items-center gap-2 px-4 py-2.5 bg-ide-bg border border-ide-primary/60 hover:border-ide-primary text-ide-primary font-mono text-xs font-bold rounded transition-all hover:bg-ide-primary/10 hover:shadow-[0_0_12px_rgba(251,191,36,0.3)] group"
        >
          <Terminal className="w-4 h-4" />
          <span className="hidden sm:inline">ai-agent</span>
          <span className="cursor-blink">_</span>
        </button>
      </SheetTrigger>

      <SheetContent
        side="right"
        className="w-full sm:w-[460px] p-0 flex flex-col bg-ide-bg border-l border-ide-border text-gray-400 font-mono [&>button]:hidden"
      >
        <SheetHeader className="shrink-0 px-0 py-0 space-y-0">
          <div className="h-10 bg-ide-sidebar border-b border-ide-border flex items-center justify-between px-4">
            <div className="flex items-center gap-3">
              <div className="flex space-x-1.5">
                <div className="w-3 h-3 rounded-full bg-red-500/80" />
                <div className="w-3 h-3 rounded-full bg-yellow-500/80" />
                <div className="w-3 h-3 rounded-full bg-green-500/80" />
              </div>
              <SheetTitle className="text-xs text-gray-400 font-mono font-normal">
                ai-agent@mrbekox - chat
              </SheetTitle>
            </div>

            <div className="flex items-center gap-1">
              {messages.length > 0 && (
                <button
                  onClick={clearChat}
                  title="Sohbeti temizle"
                  className="p-1.5 text-gray-500 hover:text-ide-primary transition-colors rounded"
                >
                  <Trash2 className="w-3.5 h-3.5" />
                </button>
              )}
              <button
                onClick={toggleChat}
                title="Kapat"
                className="p-1.5 text-gray-500 hover:text-red-400 transition-colors rounded"
              >
                <X className="w-3.5 h-3.5" />
              </button>
            </div>
          </div>

          <div className="h-7 bg-ide-bg border-b border-ide-border/50 flex items-center px-4 gap-2">
            <span className="text-[10px] text-gray-600">~/blog/</span>
            <span className="text-[10px] text-ide-primary truncate max-w-[300px]">
              {postTitle}
            </span>
          </div>

          <SheetDescription className="sr-only">
            Makale hakkinda sorular sorabileceginiz AI terminal paneli
          </SheetDescription>
        </SheetHeader>

        <div className="flex-1 overflow-hidden flex flex-col">
          {messages.length === 0 ? (
            <div className="flex-1 p-6 text-sm">
              <div className="space-y-1 mb-4">
                <p className="text-green-500 text-xs">
                  ai-agent v2.0.4
                </p>
                <p className="text-gray-600 text-xs">
                  Baglandi: {postTitle.substring(0, 40)}{postTitle.length > 40 ? '...' : ''}
                </p>
              </div>
              <div className="border-t border-ide-border/50 pt-4 space-y-1 text-xs text-gray-500">
                <p><span className="text-ide-primary">$</span> help</p>
                <p className="pl-4">AI Ozet  - makalenin kisa ozetini al</p>
                <p className="pl-4">Web Ara  - internette arastir</p>
                <p className="pl-4">soru yaz  - makale icerigi uzerine sor</p>
              </div>
              <div className="mt-6 flex items-center gap-1 text-xs text-gray-500">
                <span className="text-ide-primary">$</span>
                <span className="cursor-blink">_</span>
              </div>
            </div>
          ) : (
            <ChatMessages
              messages={messages}
              isLoading={isLoading}
              loadingState={loadingState}
            />
          )}

          {error && (
            <div className="px-4 py-2 text-xs text-red-400 border-t border-ide-border/50 font-mono">
              <span className="text-red-500">x error: </span>{error}
            </div>
          )}

          {turnstileRequired && (
            <div className="border-t border-ide-border/50 px-4 py-3 space-y-2">
              <div className="flex items-center gap-2 text-xs text-amber-300">
                <ShieldAlert className="h-4 w-4" />
                Complete human verification to continue this chat session.
              </div>
              <TurnstileChallenge
                key={turnstileChallengeKey}
                siteKey={turnstileSiteKey}
                challengeKey={turnstileChallengeKey}
                onSolved={handleTurnstileSolved}
                onError={handleTurnstileError}
              />
            </div>
          )}

          <ChatInput
            onSend={handleSendMessage}
            isLoading={isLoading}
            onOpenAgentDialog={() => setAgentDialogOpen(true)}
          />
        </div>
      </SheetContent>

      <AgentSelectionDialog
        open={agentDialogOpen}
        onOpenChange={setAgentDialogOpen}
        onSelectAgent={handleSelectAgent}
      />
    </Sheet>
  );
}
