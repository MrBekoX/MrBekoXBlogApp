'use client';

import { useState } from 'react';
import { Button } from '@/components/ui/button';
import { Sparkles, Loader2 } from 'lucide-react';
import { useAuthoringAiOperations } from '@/hooks/use-authoring-ai-operations';
import { toast } from 'sonner';

interface AISummaryButtonProps {
  postId: string;
  maxSentences?: number;
  language?: string;
  onSummaryGenerated?: (summary: string) => void;
}

export function AISummaryButton({
  postId,
  maxSentences = 3,
  language = 'tr',
  onSummaryGenerated,
}: AISummaryButtonProps) {
  const [loading, setLoading] = useState(false);
  const [summary, setSummary] = useState<string | null>(null);
  const [showSummary, setShowSummary] = useState(false);
  const { generateSummary } = useAuthoringAiOperations();

  const handleGenerateSummary = async () => {
    setLoading(true);
    try {
      const generatedSummary = await generateSummary(postId, maxSentences, language);
      setSummary(generatedSummary);
      setShowSummary(true);
      onSummaryGenerated?.(generatedSummary);
      toast.success('AI özeti başarıyla oluşturuldu');
    } catch {
      toast.error('AI özeti oluşturulurken bir hata oluştu');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="my-6 rounded-lg border border-primary/20 bg-primary/5 p-6">
      <div className="mb-3 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Sparkles className="h-5 w-5 text-primary" />
          <span className="font-semibold text-primary">AI Özet</span>
        </div>
        {!showSummary && (
          <Button
            onClick={handleGenerateSummary}
            disabled={loading}
            variant="outline"
            size="sm"
          >
            {loading ? (
              <>
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                Oluşturuluyor...
              </>
            ) : (
              <>
                <Sparkles className="mr-2 h-4 w-4" />
                Özeti göster
              </>
            )}
          </Button>
        )}
      </div>

      {showSummary && summary && (
        <>
          <p className="mb-2 leading-relaxed text-muted-foreground">
            {summary}
          </p>
          <p className="text-xs text-muted-foreground">
            Bu özet yapay zeka tarafından otomatik olarak oluşturulmuştur.
          </p>
          <Button
            onClick={() => setShowSummary(false)}
            variant="ghost"
            size="sm"
            className="mt-2"
          >
            Gizle
          </Button>
        </>
      )}
    </div>
  );
}