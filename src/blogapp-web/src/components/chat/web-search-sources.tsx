'use client';

import { useState } from 'react';
import { ExternalLink, ChevronDown, ChevronUp } from 'lucide-react';
import type { WebSearchSource } from '@/types';
import { Button } from '@/components/ui/button';
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible';

interface WebSearchSourcesProps {
  sources: WebSearchSource[];
}

export function WebSearchSources({ sources }: WebSearchSourcesProps) {
  const [isOpen, setIsOpen] = useState(false);

  if (!sources || sources.length === 0) return null;

  const displayedSources = isOpen ? sources : sources.slice(0, 3);
  const hasMore = sources.length > 3;

  return (
    <div className="mt-2 space-y-2">
      <div className="flex items-center justify-between">
        <p className="text-xs font-medium text-muted-foreground">Kaynaklar ({sources.length})</p>
        
        {hasMore && (
           <Button 
            variant="ghost" 
            size="sm" 
            className="h-6 px-2 text-xs text-muted-foreground hover:text-foreground"
            onClick={() => setIsOpen(!isOpen)}
          >
            {isOpen ? 'Daha az goster' : 'Tumunu goster'}
            {isOpen ? <ChevronUp className="ml-1 h-3 w-3" /> : <ChevronDown className="ml-1 h-3 w-3" />}
          </Button>
        )}
      </div>

      <div className="space-y-1">
        {displayedSources.map((source, index) => (
          <a
            key={index}
            href={source.url}
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-start gap-2 p-2 rounded-lg bg-background/50 hover:bg-background/80 transition-colors text-xs group border border-transparent hover:border-border/50"
          >
            <ExternalLink className="h-3 w-3 mt-0.5 flex-shrink-0 text-muted-foreground group-hover:text-primary" />
            <div className="min-w-0 flex-1">
              <p className="font-medium truncate group-hover:text-primary">
                {source.title}
              </p>
              {source.snippet && (
                <p className="text-muted-foreground line-clamp-2 mt-0.5 opacity-80">
                  {source.snippet}
                </p>
              )}
            </div>
          </a>
        ))}
      </div>
    </div>
  );
}
