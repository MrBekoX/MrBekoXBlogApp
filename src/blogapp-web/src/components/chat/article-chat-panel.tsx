'use client';

import { useState } from 'react';
import { MessageCircle, Trash2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
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
    sendMessage,
    toggleChat,
    clearChat,
  } = useArticleChat(postId, { debug: true });

  const handleSendMessage = async (content: string, agentType?: AgentType) => {
    // Normal chat or special commands
    if (content.trim()) {
      await sendMessage(content, agentType === 'web-search');
    }
  };

  const handleSelectAgent = (agentType: AgentType) => {
    if (agentType === 'summary') {
      // Summary uses the default message from ChatInput
      handleSendMessage('Bu makalenin özetini oluştur', 'normal');
    } else if (agentType === 'web-search') {
      // Web search uses default message
      handleSendMessage('Makale hakkında detaylı bilgi ver', 'web-search');
    }
    // Normal agent type doesn't need special handling
  };

  return (
    <Sheet open={isOpen} onOpenChange={toggleChat}>
      <SheetTrigger asChild>
        <Button
          variant="outline"
          size="lg"
          className="fixed bottom-6 right-6 rounded-full h-14 w-14 p-0 shadow-lg hover:shadow-xl transition-shadow z-50"
          aria-label="Makale hakkinda sohbet et"
        >
          <MessageCircle className="h-6 w-6" />
        </Button>
      </SheetTrigger>

      <SheetContent
        side="right"
        className="w-full sm:w-[440px] p-0 flex flex-col"
      >
        <SheetHeader className="px-4 py-3 border-b flex-shrink-0">
          <div className="flex items-center justify-between">
            <SheetTitle className="text-lg font-semibold truncate pr-4">
              Makale Asistani
            </SheetTitle>
            <div className="flex items-center gap-2">
              {messages.length > 0 && (
                <Button
                  variant="ghost"
                  size="icon"
                  onClick={clearChat}
                  title="Sohbeti temizle"
                >
                  <Trash2 className="h-4 w-4" />
                </Button>
              )}
            </div>
          </div>
          <p className="text-sm text-muted-foreground truncate">
            {postTitle}
          </p>
          <SheetDescription className="sr-only">
            Makale hakkında sorular sorabileceğiniz AI asistan paneli
          </SheetDescription>
        </SheetHeader>

        <div className="flex-1 overflow-hidden flex flex-col">
          {messages.length === 0 ? (
            <div className="flex-1 flex items-center justify-center p-6">
              <div className="text-center space-y-3">
                <MessageCircle className="h-12 w-12 mx-auto text-muted-foreground/50" />
                <div className="space-y-1">
                  <p className="text-sm font-medium">Makale hakkinda soru sorun</p>
                  <p className="text-xs text-muted-foreground">
                    AI asistanimiz makaledeki bilgileri kullanarak sorularinizi cevaplayacak.
                  </p>
                </div>
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
            <div className="px-4 py-2 bg-destructive/10 text-destructive text-sm">
              {error}
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
