'use client';

import { useEffect, useState } from 'react';
import { categoriesApi } from '@/lib/api';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Skeleton } from '@/components/ui/skeleton';
import { toast } from 'sonner';
import { Plus, Pencil, Trash2, Folder } from 'lucide-react';
import type { Category } from '@/types';

export default function CategoriesPage() {
  const [categories, setCategories] = useState<Category[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isCreating, setIsCreating] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [formData, setFormData] = useState({ name: '', description: '' });

  const fetchCategories = async () => {
    try {
      const response = await categoriesApi.getAll();
      if (response.success && response.data) {
        setCategories(response.data);
      }
    } catch (error) {
      console.error('Failed to fetch categories:', error);
      toast.error('Kategoriler yüklenemedi');
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchCategories();
  }, []);

  const handleCreate = async () => {
    if (!formData.name.trim()) {
      toast.error('Kategori adı gerekli');
      return;
    }

    try {
      const response = await categoriesApi.create({
        name: formData.name,
        description: formData.description || undefined,
      });
      if (response.success) {
        toast.success('Kategori oluşturuldu');
        setFormData({ name: '', description: '' });
        setIsCreating(false);
        fetchCategories();
      } else {
        toast.error(response.message || 'Kategori oluşturulamadı');
      }
    } catch (error) {
      toast.error('Kategori oluşturulamadı');
    }
  };

  const handleUpdate = async (id: string) => {
    if (!formData.name.trim()) {
      toast.error('Kategori adı gerekli');
      return;
    }

    try {
      const response = await categoriesApi.update(id, {
        name: formData.name,
        description: formData.description || undefined,
      });
      if (response.success) {
        toast.success('Kategori güncellendi');
        setFormData({ name: '', description: '' });
        setEditingId(null);
        fetchCategories();
      } else {
        toast.error(response.message || 'Kategori güncellenemedi');
      }
    } catch (error) {
      toast.error('Kategori güncellenemedi');
    }
  };

  const handleDelete = async (id: string) => {
    if (!confirm('Bu kategoriyi silmek istediğinize emin misiniz?')) return;

    try {
      const response = await categoriesApi.delete(id);
      if (response.success) {
        toast.success('Kategori silindi');
        fetchCategories();
      } else {
        toast.error(response.message || 'Kategori silinemedi');
      }
    } catch (error) {
      toast.error('Kategori silinemedi');
    }
  };

  const startEdit = (category: Category) => {
    setEditingId(category.id);
    setFormData({ name: category.name, description: category.description || '' });
    setIsCreating(false);
  };

  const cancelEdit = () => {
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
          <Button onClick={() => setIsCreating(true)}>
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
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="description">Açıklama (Opsiyonel)</Label>
              <Input
                id="description"
                value={formData.description}
                onChange={(e) => setFormData({ ...formData, description: e.target.value })}
                placeholder="Kategori açıklaması"
              />
            </div>
            <div className="flex gap-2">
              <Button onClick={() => editingId ? handleUpdate(editingId) : handleCreate()}>
                {editingId ? 'Güncelle' : 'Oluştur'}
              </Button>
              <Button variant="outline" onClick={cancelEdit}>
                İptal
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
        {isLoading ? (
          Array.from({ length: 6 }).map((_, i) => (
            <Card key={i}>
              <CardHeader>
                <Skeleton className="h-5 w-32" />
                <Skeleton className="h-4 w-48" />
              </CardHeader>
            </Card>
          ))
        ) : categories.length > 0 ? (
          categories.map((category) => (
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
                      onClick={() => startEdit(category)}
                    >
                      <Pencil className="h-4 w-4" />
                    </Button>
                    <Button
                      variant="ghost"
                      size="icon"
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
          ))
        ) : (
          <Card className="col-span-full">
            <CardContent className="py-8 text-center">
              <Folder className="mx-auto h-12 w-12 text-muted-foreground" />
              <p className="mt-4 text-muted-foreground">Henüz kategori yok</p>
              <Button className="mt-4" onClick={() => setIsCreating(true)}>
                İlk kategoriyi oluşturun
              </Button>
            </CardContent>
          </Card>
        )}
      </div>
    </div>
  );
}

