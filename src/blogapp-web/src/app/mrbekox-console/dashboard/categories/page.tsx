'use client';

import { useEffect, useState } from 'react';
import { useCategoriesStore } from '@/stores/categories-store';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Skeleton } from '@/components/ui/skeleton';
import { toast } from 'sonner';
import { Plus, Pencil, Trash2, Folder } from 'lucide-react';
import type { Category } from '@/types';

export default function CategoriesPage() {
  const {
    categories,
    isLoading,
    fetchCategories,
    createCategory,
    updateCategory,
    deleteCategory,
    cacheVersion,
  } = useCategoriesStore();

  const [isCreating, setIsCreating] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [pendingCategoryId, setPendingCategoryId] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [formData, setFormData] = useState({ name: '', description: '' });

  useEffect(() => {
    // Dashboard'da tüm kategorileri göster (boş olanlar dahil)
    // forceRefresh = true: Cache farklı parametrelerle doldurulmuş olabilir
    fetchCategories(true, false);
  }, [fetchCategories, cacheVersion]);

  const handleCreate = async () => {
    if (!formData.name.trim() || isSubmitting) {
      if (!formData.name.trim()) {
        toast.error('Kategori adı gerekli');
      }
      return;
    }

    setIsSubmitting(true);
    try {
      const result = await createCategory({
        name: formData.name,
        description: formData.description || undefined,
      });

      if (result) {
        toast.success('Kategori oluşturuldu');
        setFormData({ name: '', description: '' });
        setIsCreating(false);
      } else {
        toast.error('Kategori oluşturulamadı');
      }
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleUpdate = async (id: string) => {
    if (!formData.name.trim() || isSubmitting) {
      if (!formData.name.trim()) {
        toast.error('Kategori adı gerekli');
      }
      return;
    }

    setIsSubmitting(true);
    setPendingCategoryId(id);
    try {
      const result = await updateCategory(id, {
        name: formData.name,
        description: formData.description || undefined,
      });

      if (result) {
        toast.success('Kategori güncellendi');
        setFormData({ name: '', description: '' });
        setEditingId(null);
      } else {
        toast.error('Kategori güncellenemedi');
      }
    } finally {
      setPendingCategoryId(null);
      setIsSubmitting(false);
    }
  };

  const handleDelete = async (id: string) => {
    if (!confirm('Bu kategoriyi silmek istediğinize emin misiniz?') || pendingCategoryId === id || isSubmitting) {
      return;
    }

    setPendingCategoryId(id);
    try {
      const success = await deleteCategory(id);
      if (success) {
        toast.success('Kategori silindi');
      } else {
        toast.error('Kategori silinemedi');
      }
    } finally {
      setPendingCategoryId(null);
    }
  };

  const startEdit = (category: Category) => {
    if (isSubmitting || pendingCategoryId) {
      return;
    }

    setEditingId(category.id);
    setFormData({ name: category.name, description: category.description || '' });
    setIsCreating(false);
  };

  const cancelEdit = () => {
    if (isSubmitting) {
      return;
    }

    setEditingId(null);
    setIsCreating(false);
    setFormData({ name: '', description: '' });
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Kategoriler</h1>
          <p className="text-muted-foreground">Blog yazılarınız için kategorileri yönetin</p>
        </div>
        {!isCreating && !editingId && (
          <Button onClick={() => setIsCreating(true)} disabled={isSubmitting || Boolean(pendingCategoryId)}>
            <Plus className="mr-2 h-4 w-4" />
            Yeni Kategori
          </Button>
        )}
      </div>

      {(isCreating || editingId) && (
        <Card>
          <CardHeader>
            <CardTitle>{editingId ? 'Kategori Düzenle' : 'Yeni Kategori'}</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="name">Ad</Label>
              <Input
                id="name"
                value={formData.name}
                onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                placeholder="Kategori adı"
                disabled={isSubmitting}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="description">Açıklama (Opsiyonel)</Label>
              <Input
                id="description"
                value={formData.description}
                onChange={(e) => setFormData({ ...formData, description: e.target.value })}
                placeholder="Kategori açıklaması"
                disabled={isSubmitting}
              />
            </div>
            <div className="flex gap-2">
              <Button disabled={isSubmitting} onClick={() => editingId ? handleUpdate(editingId) : handleCreate()}>
                {editingId ? 'Güncelle' : 'Oluştur'}
              </Button>
              <Button variant="outline" disabled={isSubmitting} onClick={cancelEdit}>
                İptal
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
        {isLoading && categories.length === 0 ? (
          Array.from({ length: 6 }).map((_, i) => (
            <Card key={i}>
              <CardHeader>
                <Skeleton className="h-5 w-32" />
                <Skeleton className="h-4 w-48" />
              </CardHeader>
            </Card>
          ))
        ) : categories.length > 0 ? (
          categories.map((category) => {
            const isPending = pendingCategoryId === category.id;

            return (
              <Card key={category.id}>
                <CardHeader>
                  <div className="flex items-start justify-between">
                    <div className="flex items-center gap-2">
                      <Folder className="h-5 w-5 text-primary" />
                      <CardTitle className="text-lg">{category.name}</CardTitle>
                    </div>
                    <div className="flex gap-1">
                      <Button
                        variant="ghost"
                        size="icon"
                        disabled={isSubmitting || Boolean(pendingCategoryId)}
                        onClick={() => startEdit(category)}
                      >
                        <Pencil className="h-4 w-4" />
                      </Button>
                      <Button
                        variant="ghost"
                        size="icon"
                        disabled={isSubmitting || isPending}
                        onClick={() => handleDelete(category.id)}
                      >
                        <Trash2 className="h-4 w-4 text-destructive" />
                      </Button>
                    </div>
                  </div>
                  {category.description && (
                    <CardDescription>{category.description}</CardDescription>
                  )}
                </CardHeader>
                <CardContent>
                  <p className="text-sm text-muted-foreground">
                    Slug: <code className="rounded bg-muted px-1">{category.slug}</code>
                  </p>
                </CardContent>
              </Card>
            );
          })
        ) : (
          <Card className="col-span-full">
            <CardContent className="py-8 text-center">
              <Folder className="mx-auto h-12 w-12 text-muted-foreground" />
              <p className="mt-4 text-muted-foreground">Henüz kategori yok</p>
              <Button className="mt-4" disabled={isSubmitting || Boolean(pendingCategoryId)} onClick={() => setIsCreating(true)}>
                İlk kategoriyi oluşturun
              </Button>
            </CardContent>
          </Card>
        )}
      </div>
    </div>
  );
}
