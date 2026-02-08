'use client';

import { useState } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Sparkles, Loader2, FileText, Hash, Clock, Save } from 'lucide-react';
import { postsApi } from '@/lib/api';
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

  const handleGenerateAnalysis = async () => {
    setLoading(true);
    try {
      const response = await postsApi.generateAiSummary(postId, 5, 'tr');

      if (response.success && response.data) {
        setAnalysis(response.data);
        toast.success('AI analizi başarıyla oluşturuldu');
      } else {
        toast.error(response.message || 'AI analizi oluşturulamadı');
      }
    } catch {
      toast.error('AI analizi oluşturulurken bir hata oluştu');
    } finally {
      setLoading(false);
    }
  };

  const handleSaveAnalysis = async () => {
    if (!analysis) return;

    setSaving(true);
    try {
      // Update post with AI summary
      await postsApi.update(postId, {
        id: postId,
        title: '', // Will be ignored by backend if empty
        content: '',
        excerpt: '',
        status: 'Draft',
        categoryIds: [],
        tagNames: [],
        aiSummary: analysis.summary,
      });

      toast.success('AI analizi başarıyla kaydedildi');

      if (onAnalysisSaved) {
        onAnalysisSaved();
      }
    } catch {
      toast.error('AI analizi kaydedilirken bir hata oluştu');
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
                  Analiz Ediliyor...
                </>
              ) : (
                <>
                  <Sparkles className="mr-2 h-4 w-4" />
                  AI Analizi Başlat
                </>
              )}
            </Button>
          </div>
        ) : (
          <div className="space-y-4 rounded-lg border bg-muted/50 p-4">
            {/* Summary */}
            <div>
              <div className="flex items-center gap-2 mb-2">
                <FileText className="h-4 w-4 text-primary" />
                <h4 className="font-semibold text-sm">Özet</h4>
              </div>
              <p className="text-sm text-muted-foreground leading-relaxed">
                {analysis.summary}
              </p>
            </div>

            {/* Statistics */}
            <div className="flex items-center gap-4">
              <div className="flex items-center gap-2">
                <Hash className="h-4 w-4 text-muted-foreground" />
                <div>
                  <p className="text-xs text-muted-foreground">Kelime Sayısı</p>
                  <p className="text-sm font-semibold">{analysis.wordCount}</p>
                </div>
              </div>
            </div>

            {/* Actions */}
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
                    Analizi Kaydet
                  </>
                )}
              </Button>
              <Button
                onClick={() => setAnalysis(null)}
                variant="outline"
                size="sm"
              >
                Yeniden Oluştur
              </Button>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
