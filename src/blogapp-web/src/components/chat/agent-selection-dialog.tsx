'use client';

import { FileText, Globe, MessageSquare, X } from 'lucide-react';
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
    cmd: 'chat --mode normal',
    title: 'Normal Sohbet',
    description: 'Makale içeriğini kullanarak sorularınızı cevaplar',
    color: 'text-ide-primary border-ide-primary/30 hover:border-ide-primary/60 hover:bg-ide-primary/5',
    iconColor: 'text-ide-primary',
  },
  {
    type: 'summary' as AgentType,
    icon: FileText,
    cmd: 'summarize --brief',
    title: 'AI ile Özet Çıkar',
    description: 'Makalenin kısa ve öz bir özetini oluşturur',
    color: 'text-purple-400 border-purple-500/30 hover:border-purple-500/60 hover:bg-purple-500/5',
    iconColor: 'text-purple-400',
  },
  {
    type: 'web-search' as AgentType,
    icon: Globe,
    cmd: 'search --engine web',
    title: 'Web Araştırmacısı',
    description: 'Web araması ile derinlemesine cevaplar verir',
    color: 'text-blue-400 border-blue-500/30 hover:border-blue-500/60 hover:bg-blue-500/5',
    iconColor: 'text-blue-400',
  },
];

export function AgentSelectionDialog({ open, onOpenChange, onSelectAgent }: AgentSelectionDialogProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md bg-ide-bg border-ide-border text-gray-400 font-mono p-0 gap-0">
        {/* Terminal title bar */}
        <div className="h-10 bg-ide-sidebar border-b border-ide-border flex items-center justify-between px-4 rounded-t-lg">
          <div className="flex items-center gap-3">
            <div className="flex space-x-1.5">
              <div className="w-3 h-3 rounded-full bg-red-500/80" />
              <div className="w-3 h-3 rounded-full bg-yellow-500/80" />
              <div className="w-3 h-3 rounded-full bg-green-500/80" />
            </div>
            <DialogTitle className="text-xs text-gray-400 font-mono font-normal">
              ai-agent — ajan seç
            </DialogTitle>
          </div>
          <button
            onClick={() => onOpenChange(false)}
            className="p-1 text-gray-500 hover:text-red-400 transition-colors"
          >
            <X className="w-3.5 h-3.5" />
          </button>
        </div>

        <DialogHeader className="px-4 pt-4 pb-2">
          <p className="text-[10px] text-gray-600">
            $ select-agent --list
          </p>
          <DialogDescription className="text-xs text-gray-500">
            Size nasıl yardımcı olmamı istersiniz?
          </DialogDescription>
        </DialogHeader>

        {/* Agent list */}
        <div className="grid gap-2 px-4 pb-4">
          {AGENTS.map((agent) => {
            const Icon = agent.icon;
            return (
              <button
                key={agent.type}
                onClick={() => {
                  onSelectAgent(agent.type);
                  onOpenChange(false);
                }}
                className={`w-full flex items-start gap-3 p-3 rounded border transition-all text-left ${agent.color}`}
              >
                <Icon className={`w-4 h-4 mt-0.5 shrink-0 ${agent.iconColor}`} />
                <div className="min-w-0">
                  <div className="text-xs font-bold mb-0.5">
                    <span className="text-gray-600 mr-1">$</span>
                    {agent.cmd}
                  </div>
                  <div className="text-[10px] text-gray-500 leading-relaxed">
                    {agent.description}
                  </div>
                </div>
              </button>
            );
          })}
        </div>
      </DialogContent>
    </Dialog>
  );
}
