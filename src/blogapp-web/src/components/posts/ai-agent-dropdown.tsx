'use client';

import { useState, useEffect } from 'react';
import { Button } from '@/components/ui/button';
import { Sparkles, Loader2, FileText } from 'lucide-react';
import { toast } from 'sonner';
import { useAiAnalysis, AiAnalysisResult } from '@/hooks/use-ai-analysis';

interface AISummaryButtonProps {
  postId: string;
  content: string;
  onSummaryReceived?: (summary: string) => void;
}

/**
 * AI Summary button for article readers.
 * Uses RabbitMQ event-driven architecture via Backend API.
 * Results arrive via SignalR.
 */
export function AIAgentDropdown({
  postId,
  content,
  onSummaryReceived,
}: AISummaryButtonProps) {
  const [displayResult, setDisplayResult] = useState<string | null>(null);
  
  // Use the RabbitMQ-based AI analysis hook
  const { 
    requestAnalysis, 
    isLoading, 
    result, 
    error,
    reset 
  } = useAiAnalysis(postId, {
    onComplete: (analysisResult: AiAnalysisResult) => {
      toast.success('Özet oluşturuldu');
      if (analysisResult.summary) {
        setDisplayResult(analysisResult.summary);
        onSummaryReceived?.(analysisResult.summary);
      }
    },
    onError: (errorMsg: string) => {
      toast.error(`Özet oluşturulamadı: ${errorMsg}`);
    },
    debug: false,
  });

  // When result comes via SignalR, show summary
  useEffect(() => {
    if (result?.summary) {
      setDisplayResult(result.summary);
    }
  }, [result]);

  const handleClick = async () => {
    reset();
    setDisplayResult(null);
    await requestAnalysis('tr', 'TR');
    toast.info('Özet oluşturuluyor...');
  };

  return (
    <div className="my-6">
      <Button 
        variant="outline" 
        onClick={handleClick}
        disabled={isLoading}
      >
        {isLoading ? (
          <>
            <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            Özet oluşturuluyor...
          </>
        ) : (
          <>
            <Sparkles className="mr-2 h-4 w-4" />
            <FileText className="mr-2 h-4 w-4" />
            AI ile Özet Oluştur
          </>
        )}
      </Button>
      
      {error && (
        <p className="text-sm text-red-500 mt-2">{error}</p>
      )}

      {displayResult && (
        <div className="mt-4 rounded-lg border border-primary/20 bg-primary/5 p-4">
          <div className="flex items-center gap-2 mb-3">
            <Sparkles className="h-4 w-4 text-primary" />
            <span className="font-semibold text-primary text-sm">AI Özet</span>
          </div>
          <p className="text-sm text-muted-foreground">{displayResult}</p>
          <Button
            variant="ghost"
            size="sm"
            className="mt-3"
            onClick={() => {
              setDisplayResult(null);
              reset();
            }}
          >
            Kapat
          </Button>
        </div>
      )}
    </div>
  );
}
