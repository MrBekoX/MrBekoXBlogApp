'use client';

import { useState } from 'react';
import { Button } from '@/components/ui/button';
import { Sparkles, Loader2 } from 'lucide-react';
import { postsApi } from '@/lib/api';
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
  onSummaryGenerated
}: AISummaryButtonProps) {
  const [loading, setLoading] = useState(false);
  const [summary, setSummary] = useState<string | null>(null);
  const [showSummary, setShowSummary] = useState(false);

  const handleGenerateSummary = async () => {
    setLoading(true);
    try {
      const response = await postsApi.generateAiSummary(postId, maxSentences, language);

      if (response.success && response.data) {
        const generatedSummary = response.data.summary;
        setSummary(generatedSummary);
        setShowSummary(true);

        // Callback to parent
        if (onSummaryGenerated) {
          onSummaryGenerated(generatedSummary);
        }

        toast.success('AI özeti başarıyla oluşturuldu');
      } else {
        toast.error(response.message || 'AI özeti oluşturulamadı');
      }
    } catch {
      toast.error('AI özeti oluşturulurken bir hata oluştu');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="my-6 rounded-lg border border-primary/20 bg-primary/5 p-6">
      <div className="flex items-center justify-between mb-3">
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
                Özeti Göster
              </>
            )}
          </Button>
        )}
      </div>

      {showSummary && summary && (
        <>
          <p className="text-muted-foreground leading-relaxed mb-2">
            {summary}
          </p>
          <p className="text-xs text-muted-foreground">
            🤖 Bu özet yapay zeka tarafından otomatik olarak oluşturulmuştur.
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
