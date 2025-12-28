'use client';

import { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod/v4';
import { usePostsStore } from '@/stores/posts-store';
import { categoriesApi, tagsApi, aiApi } from '@/lib/api';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Badge } from '@/components/ui/badge';
import { toast } from 'sonner';
import { Loader2, Sparkles, X, Save, Send } from 'lucide-react';
import { MarkdownEditor } from '@/components/markdown-editor';
import { ImageUpload } from '@/components/image-upload';
import type { Category, Tag, PostStatus } from '@/types';

const postSchema = z.object({
  title: z.string().min(1, 'Başlık gerekli').max(200),
  content: z.string().min(1, 'İçerik gerekli'),
  excerpt: z.string().max(500).optional(),
  featuredImageUrl: z.string().url().optional().or(z.literal('')),
  status: z.enum(['Draft', 'Published']),
});

type PostFormData = z.infer<typeof postSchema>;

export default function NewPostPage() {
  const router = useRouter();
  const { createPost, isLoading, error: storeError } = usePostsStore();
  const [categories, setCategories] = useState<Category[]>([]);
  const [tags, setTags] = useState<Tag[]>([]);
  const [selectedCategories, setSelectedCategories] = useState<string[]>([]);
  const [selectedTags, setSelectedTags] = useState<string[]>([]);
  const [newTag, setNewTag] = useState('');
  const [aiLoading, setAiLoading] = useState<string | null>(null);

  const {
    register,
    handleSubmit,
    setValue,
    watch,
    formState: { errors },
  } = useForm<PostFormData>({
    resolver: zodResolver(postSchema),
    defaultValues: {
      status: 'Draft',
    },
  });

  const content = watch('content');

  useEffect(() => {
    const fetchData = async () => {
      try {
        const [categoriesRes, tagsRes] = await Promise.all([
          categoriesApi.getAll(),
          tagsApi.getAll(),
        ]);
        if (categoriesRes.success && categoriesRes.data) {
          setCategories(categoriesRes.data);
        }
        if (tagsRes.success && tagsRes.data) {
          setTags(tagsRes.data);
        }
      } catch (error) {
        console.error('Failed to fetch data:', error);
      }
    };
    fetchData();
  }, []);

  const onInvalid = (errors: Record<string, unknown>) => {
    console.log('Form validation errors:', errors);
    const errorMessages = Object.entries(errors)
      .map(([field, error]) => `${field}: ${(error as { message?: string })?.message || 'Geçersiz'}`)
      .join(', ');
    toast.error(`Doğrulama hatası: ${errorMessages}`);
  };

  const onSubmit = async (data: PostFormData) => {
    console.log('Form submitted with data:', data);
    const post = await createPost({
      ...data,
      excerpt: data.excerpt || '',
      featuredImageUrl: data.featuredImageUrl || undefined,
      categoryIds: selectedCategories,
      tagNames: selectedTags,
      status: data.status as PostStatus,
    });

    if (post) {
      toast.success(data.status === 'Published' ? 'Yazı yayınlandı!' : 'Taslak kaydedildi!');
      router.push('/admin/dashboard/posts');
    } else {
      const errorMsg = usePostsStore.getState().error;
      console.error('Post creation failed. Store error:', errorMsg);
      toast.error(`Yazı oluşturulamadı: ${errorMsg || 'Bilinmeyen hata'}`);
    }
  };

  const handleAddTag = () => {
    if (newTag && !selectedTags.includes(newTag)) {
      setSelectedTags([...selectedTags, newTag]);
      setNewTag('');
    }
  };

  const handleRemoveTag = (tag: string) => {
    setSelectedTags(selectedTags.filter((t) => t !== tag));
  };

  const handleAiGenerateTitle = async () => {
    if (!content) {
      toast.error('Önce içerik yazın');
      return;
    }
    setAiLoading('title');
    try {
      const result = await aiApi.generateTitle(content);
      setValue('title', result.title);
      toast.success('Başlık oluşturuldu!');
    } catch {
      toast.error('Başlık oluşturulamadı');
    } finally {
      setAiLoading(null);
    }
  };

  const handleAiGenerateExcerpt = async () => {
    if (!content) {
      toast.error('Önce içerik yazın');
      return;
    }
    setAiLoading('excerpt');
    try {
      const result = await aiApi.generateExcerpt(content);
      setValue('excerpt', result.excerpt);
      toast.success('Özet oluşturuldu!');
    } catch {
      toast.error('Özet oluşturulamadı');
    } finally {
      setAiLoading(null);
    }
  };

  const handleAiGenerateTags = async () => {
    if (!content) {
      toast.error('Önce içerik yazın');
      return;
    }
    setAiLoading('tags');
    try {
      const result = await aiApi.generateTags(content);
      setSelectedTags([...new Set([...selectedTags, ...result.tags])]);
      toast.success('Etiketler oluşturuldu!');
    } catch {
      toast.error('Etiketler oluşturulamadı');
    } finally {
      setAiLoading(null);
    }
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Yeni Yazı Oluştur</h1>
        <p className="text-muted-foreground">Blog yazınızı yazın ve yayınlayın</p>
      </div>

      <form onSubmit={handleSubmit(onSubmit)} className="space-y-6">
        <div className="grid gap-6 lg:grid-cols-3">
          <div className="lg:col-span-2 space-y-6">
            <Card>
              <CardHeader>
                <CardTitle>İçerik</CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="space-y-2">
                  <div className="flex items-center justify-between">
                    <Label htmlFor="title">Başlık</Label>
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      onClick={handleAiGenerateTitle}
                      disabled={!!aiLoading}
                    >
                      {aiLoading === 'title' ? (
                        <Loader2 className="mr-1 h-3 w-3 animate-spin" />
                      ) : (
                        <Sparkles className="mr-1 h-3 w-3" />
                      )}
                      AI ile Oluştur
                    </Button>
                  </div>
                  <Input
                    id="title"
                    placeholder="Yazınızın başlığını girin"
                    {...register('title')}
                  />
                  {errors.title && (
                    <p className="text-sm text-destructive">{errors.title.message}</p>
                  )}
                </div>

                <div className="space-y-2">
                  <Label htmlFor="content">İçerik</Label>
                  <MarkdownEditor
                    value={content || ''}
                    onChange={(value) => setValue('content', value)}
                    placeholder="Yazı içeriğinizi Markdown formatında yazın..."
                    height={500}
                  />
                  {errors.content && (
                    <p className="text-sm text-destructive">{errors.content.message}</p>
                  )}
                </div>

                <div className="space-y-2">
                  <div className="flex items-center justify-between">
                    <Label htmlFor="excerpt">Özet</Label>
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      onClick={handleAiGenerateExcerpt}
                      disabled={!!aiLoading}
                    >
                      {aiLoading === 'excerpt' ? (
                        <Loader2 className="mr-1 h-3 w-3 animate-spin" />
                      ) : (
                        <Sparkles className="mr-1 h-3 w-3" />
                      )}
                      AI ile Oluştur
                    </Button>
                  </div>
                  <Textarea
                    id="excerpt"
                    placeholder="Yazınızın kısa açıklaması"
                    className="min-h-[100px]"
                    {...register('excerpt')}
                  />
                  {errors.excerpt && (
                    <p className="text-sm text-destructive">{errors.excerpt.message}</p>
                  )}
                </div>
              </CardContent>
            </Card>
          </div>

          <div className="space-y-6">
            <Card>
              <CardHeader>
                <CardTitle>Yayınla</CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="space-y-2">
                  <Label>Durum</Label>
                  <Select
                    defaultValue="Draft"
                    onValueChange={(value) => setValue('status', value as 'Draft' | 'Published')}
                  >
                    <SelectTrigger>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="Draft">Taslak</SelectItem>
                      <SelectItem value="Published">Yayınla</SelectItem>
                    </SelectContent>
                  </Select>
                </div>

                <div className="flex gap-2">
                  <Button
                    type="button"
                    className="flex-1"
                    disabled={isLoading}
                    onClick={() => {
                      setValue('status', 'Draft');
                      handleSubmit(onSubmit, onInvalid)();
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
                    onClick={() => {
                      setValue('status', 'Published');
                      handleSubmit(onSubmit, onInvalid)();
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
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>Öne Çıkan Görsel</CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                <ImageUpload
                  value={watch('featuredImageUrl') || undefined}
                  onChange={(url) => setValue('featuredImageUrl', url || '')}
                  disabled={isLoading}
                />
                <div className="relative">
                  <div className="absolute inset-0 flex items-center">
                    <span className="w-full border-t" />
                  </div>
                  <div className="relative flex justify-center text-xs uppercase">
                    <span className="bg-card px-2 text-muted-foreground">veya URL girin</span>
                  </div>
                </div>
                <Input
                  placeholder="Görsel URL'si"
                  {...register('featuredImageUrl')}
                />
                {errors.featuredImageUrl && (
                  <p className="text-sm text-destructive">{errors.featuredImageUrl.message}</p>
                )}
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>Kategoriler</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="space-y-2">
                  <Select
                    onValueChange={(value) => {
                      if (!selectedCategories.includes(value)) {
                        setSelectedCategories([...selectedCategories, value]);
                      }
                    }}
                  >
                    <SelectTrigger>
                      <SelectValue placeholder="Kategori seçin" />
                    </SelectTrigger>
                    <SelectContent>
                      {categories.map((category) => (
                        <SelectItem key={category.id} value={category.id}>
                          {category.name}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>

                  <div className="flex flex-wrap gap-2">
                    {selectedCategories.map((id) => {
                      const category = categories.find((c) => c.id === id);
                      return category ? (
                        <Badge key={id} variant="secondary">
                          {category.name}
                          <button
                            type="button"
                            onClick={() =>
                              setSelectedCategories(selectedCategories.filter((c) => c !== id))
                            }
                            className="ml-1"
                          >
                            <X className="h-3 w-3" />
                          </button>
                        </Badge>
                      ) : null;
                    })}
                  </div>
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <div className="flex items-center justify-between">
                  <CardTitle>Etiketler</CardTitle>
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    onClick={handleAiGenerateTags}
                    disabled={!!aiLoading}
                  >
                    {aiLoading === 'tags' ? (
                      <Loader2 className="mr-1 h-3 w-3 animate-spin" />
                    ) : (
                      <Sparkles className="mr-1 h-3 w-3" />
                    )}
                    AI Öner
                  </Button>
                </div>
              </CardHeader>
              <CardContent>
                <div className="space-y-2">
                  <div className="flex gap-2">
                    <Input
                      placeholder="Etiket ekle"
                      value={newTag}
                      onChange={(e) => setNewTag(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter') {
                          e.preventDefault();
                          handleAddTag();
                        }
                      }}
                    />
                    <Button type="button" onClick={handleAddTag} variant="outline">
                      Ekle
                    </Button>
                  </div>

                  <div className="flex flex-wrap gap-2">
                    {selectedTags.map((tag) => (
                      <Badge key={tag} variant="outline">
                        #{tag}
                        <button
                          type="button"
                          onClick={() => handleRemoveTag(tag)}
                          className="ml-1"
                        >
                          <X className="h-3 w-3" />
                        </button>
                      </Badge>
                    ))}
                  </div>

                  {tags.length > 0 && (
                    <div className="mt-4">
                      <p className="text-sm text-muted-foreground mb-2">Mevcut etiketler:</p>
                      <div className="flex flex-wrap gap-1">
                        {tags.slice(0, 10).map((tag) => (
                          <Badge
                            key={tag.id}
                            variant="secondary"
                            className="cursor-pointer"
                            onClick={() => {
                              if (!selectedTags.includes(tag.name)) {
                                setSelectedTags([...selectedTags, tag.name]);
                              }
                            }}
                          >
                            #{tag.name}
                          </Badge>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              </CardContent>
            </Card>
          </div>
        </div>
      </form>
    </div>
  );
}

