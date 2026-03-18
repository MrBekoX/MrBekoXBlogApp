'use client';

import { useState } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Sparkles, Loader2, FileText, Hash, Save } from 'lucide-react';
import { postsApi } from '@/lib/api';
import { useAuthoringAiOperations } from '@/hooks/use-authoring-ai-operations';
import { toast } from 'sonner';

interface AIAnalysisData {
  summary: string;
  wordCount: number;
}

interface AIAnalysisCardProps {
  postId: string;
  onAnalysisSaved?: () => void;
}

export function AIAnalysisCard({ postId, onAnalysisSaved }: AIAnalysisCardProps) {
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [analysis, setAnalysis] = useState<AIAnalysisData | null>(null);
  const { generateSummary } = useAuthoringAiOperations();

  const handleGenerateAnalysis = async () => {
    setLoading(true);
    try {
      const summary = await generateSummary(postId, 5, 'tr');
      setAnalysis({
        summary,
        wordCount: summary.split(/\s+/).filter(Boolean).length,
      });
      toast.success('AI analizi basariyla olusturuldu');
    } catch {
      toast.error('AI analizi olusturulurken bir hata olustu');
    } finally {
      setLoading(false);
    }
  };

  const handleSaveAnalysis = async () => {
    if (!analysis) {
      return;
    }

    setSaving(true);
    try {
      await postsApi.update(postId, {
        id: postId,
        title: '',
        content: '',
        excerpt: '',
        status: 'Draft',
        categoryIds: [],
        tagNames: [],
        aiSummary: analysis.summary,
      });

      toast.success('AI analizi basariyla kaydedildi');
      onAnalysisSaved?.();
    } catch {
      toast.error('AI analizi kaydedilirken bir hata olustu');
    } finally {
      setSaving(false);
    }
  };

  return (
    <Card className="mt-6">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Sparkles className="h-5 w-5 text-primary" />
          AI Asistan
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        {!analysis ? (
          <div className="flex justify-center">
            <Button
              onClick={handleGenerateAnalysis}
              disabled={loading}
              className="w-full max-w-sm"
            >
              {loading ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  Analiz ediliyor...
                </>
              ) : (
                <>
                  <Sparkles className="mr-2 h-4 w-4" />
                  AI analizi baslat
                </>
              )}
            </Button>
          </div>
        ) : (
          <div className="space-y-4 rounded-lg border bg-muted/50 p-4">
            <div>
              <div className="mb-2 flex items-center gap-2">
                <FileText className="h-4 w-4 text-primary" />
                <h4 className="text-sm font-semibold">Ozet</h4>
              </div>
              <p className="text-sm leading-relaxed text-muted-foreground">
                {analysis.summary}
              </p>
            </div>

            <div className="flex items-center gap-4">
              <div className="flex items-center gap-2">
                <Hash className="h-4 w-4 text-muted-foreground" />
                <div>
                  <p className="text-xs text-muted-foreground">Kelime sayisi</p>
                  <p className="text-sm font-semibold">{analysis.wordCount}</p>
                </div>
              </div>
            </div>

            <div className="flex gap-2 pt-2">
              <Button
                onClick={handleSaveAnalysis}
                disabled={saving}
                size="sm"
                className="flex-1"
              >
                {saving ? (
                  <>
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    Kaydediliyor...
                  </>
                ) : (
                  <>
                    <Save className="mr-2 h-4 w-4" />
                    Analizi kaydet
                  </>
                )}
              </Button>
              <Button
                onClick={() => setAnalysis(null)}
                variant="outline"
                size="sm"
              >
                Yeniden olustur
              </Button>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}