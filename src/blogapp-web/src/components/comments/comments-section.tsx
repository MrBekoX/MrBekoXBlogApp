'use client';

import { MessageSquare, Clock } from 'lucide-react';
import { Card, CardContent } from '@/components/ui/card';

interface CommentsSectionProps {
  postId: string;
}

// Temporarily disabled until backend Comments API is implemented
export function CommentsSection({ postId }: CommentsSectionProps) {
  return (
    <section className="space-y-8">
      <div className="flex items-center gap-2">
        <MessageSquare className="h-6 w-6" />
        <h2 className="text-2xl font-bold">Yorumlar</h2>
      </div>

      <Card className="border-dashed">
        <CardContent className="py-12 text-center">
          <div className="flex items-center justify-center gap-2 mb-4">
            <Clock className="h-8 w-8 text-primary/60" />
          </div>
          <h3 className="text-lg font-semibold text-foreground mb-2">
            Yakında Geliyor
          </h3>
          <p className="text-muted-foreground max-w-md mx-auto">
            Yorum sistemi üzerinde çalışıyoruz. Kısa süre içinde düşüncelerinizi paylaşabileceksiniz!
          </p>
        </CardContent>
      </Card>
    </section>
  );
}

