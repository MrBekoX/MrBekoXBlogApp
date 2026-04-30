'use client';

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Loader2, Save, Send } from 'lucide-react';
import { toast } from 'sonner';
import type { PostStatus } from '@/types';

interface PublishStatusCardProps {
  currentStatus: string;
  isLoading: boolean;
  onSaveDraft: () => Promise<void>;
  onPublish: () => Promise<void>;
}

export function PublishStatusCard({
  currentStatus,
  isLoading,
  onSaveDraft,
  onPublish,
}: PublishStatusCardProps) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Yayın Durumu</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex gap-2">
          <Button
            type="button"
            className="flex-1"
            disabled={isLoading}
            onClick={async () => {
              try {
                await onSaveDraft();
              } catch (error) {
                toast.error(error instanceof Error ? error.message : 'Taslak kaydedilemedi');
              }
            }}
            variant="outline"
          >
            {isLoading ? (
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            ) : (
              <Save className="mr-2 h-4 w-4" />
            )}
            Taslak Kaydet
          </Button>
          <Button
            type="button"
            className="flex-1"
            disabled={isLoading}
            onClick={async () => {
              try {
                await onPublish();
              } catch (error) {
                toast.error(error instanceof Error ? error.message : 'Yayınlanamadı');
              }
            }}
          >
            {isLoading ? (
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            ) : (
              <Send className="mr-2 h-4 w-4" />
            )}
            Yayınla
          </Button>
        </div>
        <div className="text-sm text-muted-foreground">
          Mevcut durum: <Badge variant={currentStatus === 'Published' ? 'default' : 'secondary'}>{currentStatus}</Badge>
        </div>
      </CardContent>
    </Card>
  );
}
