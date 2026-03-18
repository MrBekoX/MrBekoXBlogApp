'use client';

import { useEffect, useState } from 'react';
import { useTagsStore } from '@/stores/tags-store';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Skeleton } from '@/components/ui/skeleton';
import { toast } from 'sonner';
import { Plus, Trash2, Tag } from 'lucide-react';

export default function TagsPage() {
  const {
    tags,
    isLoading,
    fetchTags,
    createTag,
    deleteTag,
    cacheVersion,
  } = useTagsStore();

  const [isCreating, setIsCreating] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [pendingTagId, setPendingTagId] = useState<string | null>(null);
  const [newTagName, setNewTagName] = useState('');

  useEffect(() => {
    // Admin panel needs to see all tags, including those without published posts
    fetchTags(false, true);
  }, [fetchTags, cacheVersion]);

  const handleCreate = async () => {
    if (!newTagName.trim() || isSubmitting) {
      if (!newTagName.trim()) {
        toast.error('Etiket adı gerekli');
      }
      return;
    }

    setIsSubmitting(true);
    try {
      const result = await createTag({ name: newTagName });
      if (result) {
        toast.success('Etiket oluşturuldu');
        setNewTagName('');
        setIsCreating(false);
      } else {
        toast.error('Etiket oluşturulamadı');
      }
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleDelete = async (id: string) => {
    if (!confirm('Bu etiketi silmek istediğinize emin misiniz?') || isSubmitting || pendingTagId === id) {
      return;
    }

    setPendingTagId(id);
    try {
      const success = await deleteTag(id);
      if (success) {
        toast.success('Etiket silindi');
      } else {
        toast.error('Etiket silinemedi');
      }
    } finally {
      setPendingTagId(null);
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Etiketler</h1>
          <p className="text-muted-foreground">Blog yazılarınız için etiketleri yönetin</p>
        </div>
        {!isCreating && (
          <Button disabled={isSubmitting || Boolean(pendingTagId)} onClick={() => setIsCreating(true)}>
            <Plus className="mr-2 h-4 w-4" />
            Yeni Etiket
          </Button>
        )}
      </div>

      {isCreating && (
        <Card>
          <CardHeader>
            <CardTitle>Yeni Etiket</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="name">Ad</Label>
              <Input
                id="name"
                value={newTagName}
                onChange={(e) => setNewTagName(e.target.value)}
                placeholder="Etiket adı"
                disabled={isSubmitting}
                onKeyDown={(e) => e.key === 'Enter' && handleCreate()}
              />
            </div>
            <div className="flex gap-2">
              <Button disabled={isSubmitting} onClick={handleCreate}>Oluştur</Button>
              <Button variant="outline" disabled={isSubmitting} onClick={() => { setIsCreating(false); setNewTagName(''); }}>
                İptal
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      <Card>
        <CardHeader>
          <CardTitle>Tüm Etiketler</CardTitle>
          <CardDescription>
            {tags.length} etiket bulunuyor
          </CardDescription>
        </CardHeader>
        <CardContent>
          {isLoading && tags.length === 0 ? (
            <div className="flex flex-wrap gap-2">
              {Array.from({ length: 12 }).map((_, i) => (
                <Skeleton key={i} className="h-8 w-24" />
              ))}
            </div>
          ) : tags.length > 0 ? (
            <div className="flex flex-wrap gap-2">
              {tags.map((tag) => {
                const isPending = pendingTagId === tag.id;

                return (
                  <div
                    key={tag.id}
                    className="group flex items-center gap-1 rounded-full border bg-background px-3 py-1.5 text-sm transition-colors hover:bg-muted"
                  >
                    <Tag className="h-3 w-3 text-primary" />
                    <span>{tag.name}</span>
                    <button
                      disabled={isSubmitting || isPending}
                      onClick={() => handleDelete(tag.id)}
                      className="ml-1 opacity-0 transition-opacity group-hover:opacity-100 disabled:pointer-events-none disabled:opacity-40"
                    >
                      <Trash2 className="h-3 w-3 text-destructive hover:text-destructive/80" />
                    </button>
                  </div>
                );
              })}
            </div>
          ) : (
            <div className="py-8 text-center">
              <Tag className="mx-auto h-12 w-12 text-muted-foreground" />
              <p className="mt-4 text-muted-foreground">Henüz etiket yok</p>
              <Button className="mt-4" disabled={isSubmitting || Boolean(pendingTagId)} onClick={() => setIsCreating(true)}>
                İlk etiketi oluşturun
              </Button>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
