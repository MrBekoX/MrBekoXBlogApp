'use client';

import { FileText, Globe, MessageSquare } from 'lucide-react';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { AgentType } from '@/types';

interface AgentSelectionDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSelectAgent: (agent: AgentType) => void;
}

const AGENTS = [
  {
    type: 'normal' as AgentType,
    icon: MessageSquare,
    title: 'Normal Sohbet',
    description: 'Makale içeriğini kullanarak sorularınızı cevaplar',
    color: 'text-blue-500',
  },
  {
    type: 'summary' as AgentType,
    icon: FileText,
    title: 'AI ile Özet Çıkar',
    description: 'Makalenin kısa ve öz bir özetini oluşturur',
    color: 'text-purple-500',
  },
  {
    type: 'web-search' as AgentType,
    icon: Globe,
    title: 'Web Araştırmacısı',
    description: 'Web araması ile derinlemesine cevaplar verir',
    color: 'text-green-500',
  },
];

export function AgentSelectionDialog({
  open,
  onOpenChange,
  onSelectAgent,
}: AgentSelectionDialogProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Ajan Seçin</DialogTitle>
          <DialogDescription>
            Size nasıl yardımcı olmamı istersiniz?
          </DialogDescription>
        </DialogHeader>

        <div className="grid gap-3 py-4">
          {AGENTS.map((agent) => {
            const Icon = agent.icon;
            return (
              <Button
                key={agent.type}
                variant="outline"
                className="h-auto p-4 justify-start hover:bg-accent"
                onClick={() => {
                  onSelectAgent(agent.type);
                  onOpenChange(false);
                }}
              >
                <Icon className={`h-5 w-5 mr-3 ${agent.color}`} />
                <div className="text-left">
                  <div className="font-medium">{agent.title}</div>
                  <div className="text-xs text-muted-foreground mt-1">
                    {agent.description}
                  </div>
                </div>
              </Button>
            );
          })}
        </div>
      </DialogContent>
    </Dialog>
  );
}
