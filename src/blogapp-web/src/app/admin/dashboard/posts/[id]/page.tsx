'use client';

import { useState, useEffect } from 'react';
import { useRouter, useParams } from 'next/navigation';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod/v4';
import { usePostsStore } from '@/stores/posts-store';
import { categoriesApi, tagsApi, postsApi } from '@/lib/api';
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
import { Loader2, X, Save, Send, ArrowLeft } from 'lucide-react';
import { MarkdownEditor } from '@/components/markdown-editor';
import type { Category, Tag, PostStatus, BlogPost } from '@/types';
import Link from 'next/link';

const postSchema = z.object({
  title: z.string().min(1, 'Başlık gerekli').max(200),
  content: z.string().min(1, 'İçerik gerekli'),
  excerpt: z.string().max(500).optional(),
  featuredImageUrl: z.string().url().optional().or(z.literal('')),
  status: z.enum(['Draft', 'Published', 'Archived']),
});

type PostFormData = z.infer<typeof postSchema>;

export default function EditPostPage() {
  const router = useRouter();
  const params = useParams();
  const postId = params.id as string;
  
  const { updatePost, isLoading } = usePostsStore();
  const [post, setPost] = useState<BlogPost | null>(null);
  const [categories, setCategories] = useState<Category[]>([]);
  const [tags, setTags] = useState<Tag[]>([]);
  const [selectedCategories, setSelectedCategories] = useState<string[]>([]);
  const [selectedTags, setSelectedTags] = useState<string[]>([]);
  const [newTag, setNewTag] = useState('');
  const [loadingPost, setLoadingPost] = useState(true);

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
        const [postRes, categoriesRes, tagsRes] = await Promise.all([
          postsApi.getById(postId),
          categoriesApi.getAll(),
          tagsApi.getAll(),
        ]);
        
        if (postRes.success && postRes.data) {
          const postData = postRes.data;
          setPost(postData);
          setValue('title', postData.title);
          setValue('content', postData.content);
          setValue('excerpt', postData.excerpt || '');
          setValue('featuredImageUrl', postData.featuredImageUrl || '');
          setValue('status', postData.status as PostStatus);
          
          if (postData.category) {
            setSelectedCategories([postData.category.id]);
          }
          if (postData.tags) {
            setSelectedTags(postData.tags.map(t => t.name));
          }
        } else {
          toast.error('Yazı bulunamadı');
          router.push('/admin/dashboard/posts');
        }
        
        if (categoriesRes.success && categoriesRes.data) {
          setCategories(categoriesRes.data);
        }
        if (tagsRes.success && tagsRes.data) {
          setTags(tagsRes.data);
        }
      } catch {
        toast.error('Yazı bulunamadı veya veri yüklenirken hata oluştu');
        router.push('/admin/dashboard/posts');
      } finally {
        setLoadingPost(false);
      }
    };
    fetchData();
  }, [postId, setValue, router]);

  const onSubmit = async (data: PostFormData) => {
    const updatedPost = await updatePost(postId, {
      id: postId,
      ...data,
      excerpt: data.excerpt || '',
      featuredImageUrl: data.featuredImageUrl || undefined,
      categoryIds: selectedCategories,
      tagNames: selectedTags,
      status: data.status as PostStatus,
    });

    if (updatedPost) {
      toast.success(data.status === 'Published' ? 'Yazı yayınlandı!' : 'Yazı güncellendi!');
      router.push('/admin/dashboard/posts');
    } else {
      const errorMsg = usePostsStore.getState().error;
      toast.error(`Yazı güncellenemedi: ${errorMsg || 'Bilinmeyen hata'}`);
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

  if (loadingPost) {
    return (
      <div className="flex items-center justify-center min-h-[400px]">
        <Loader2 className="h-8 w-8 animate-spin text-primary" />
      </div>
    );
  }

  if (!post) {
    return (
      <div className="flex flex-col items-center justify-center min-h-[400px] gap-4">
        <p className="text-muted-foreground">Yazı bulunamadı</p>
        <Link href="/admin/dashboard/posts">
          <Button variant="outline">
            <ArrowLeft className="mr-2 h-4 w-4" />
            Yazılara Dön
          </Button>
        </Link>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-4">
        <Link href="/admin/dashboard/posts">
          <Button variant="ghost" size="icon">
            <ArrowLeft className="h-4 w-4" />
          </Button>
        </Link>
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Yazıyı Düzenle</h1>
          <p className="text-muted-foreground">Blog yazınızı düzenleyin</p>
        </div>
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
                  <Label htmlFor="title">Başlık</Label>
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
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>Özet</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="space-y-2">
                  <Label htmlFor="excerpt">Kısa Açıklama</Label>
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
                <CardTitle>Yayın Durumu</CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="flex gap-2">
                  <Button
                    type="button"
                    className="flex-1"
                    disabled={isLoading}
                    onClick={() => {
                      setValue('status', 'Draft');
                      handleSubmit(onSubmit)();
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
                      handleSubmit(onSubmit)();
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
                  Mevcut durum: <Badge variant={post.status === 'Published' ? 'default' : 'secondary'}>{post.status}</Badge>
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>Kategori</CardTitle>
              </CardHeader>
              <CardContent>
                <Select
                  value={selectedCategories[0] || ''}
                  onValueChange={(value) => setSelectedCategories(value ? [value] : [])}
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
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>Etiketler</CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="flex flex-wrap gap-2">
                  {selectedTags.map((tag) => (
                    <Badge key={tag} variant="secondary" className="gap-1">
                      {tag}
                      <button
                        type="button"
                        onClick={() => handleRemoveTag(tag)}
                        className="ml-1 hover:text-destructive"
                      >
                        <X className="h-3 w-3" />
                      </button>
                    </Badge>
                  ))}
                </div>
                <div className="flex gap-2">
                  <Select
                    value=""
                    onValueChange={(value) => {
                      if (value && !selectedTags.includes(value)) {
                        setSelectedTags([...selectedTags, value]);
                      }
                    }}
                  >
                    <SelectTrigger className="flex-1">
                      <SelectValue placeholder="Etiket seçin" />
                    </SelectTrigger>
                    <SelectContent>
                      {tags
                        .filter((tag) => !selectedTags.includes(tag.name))
                        .map((tag) => (
                          <SelectItem key={tag.id} value={tag.name}>
                            {tag.name}
                          </SelectItem>
                        ))}
                    </SelectContent>
                  </Select>
                </div>
                <div className="flex gap-2">
                  <Input
                    placeholder="Yeni etiket ekle"
                    value={newTag}
                    onChange={(e) => setNewTag(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') {
                        e.preventDefault();
                        handleAddTag();
                      }
                    }}
                  />
                  <Button type="button" variant="outline" onClick={handleAddTag}>
                    Ekle
                  </Button>
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>Öne Çıkan Görsel</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="space-y-2">
                  <Input
                    placeholder="Görsel URL'si"
                    {...register('featuredImageUrl')}
                  />
                  {errors.featuredImageUrl && (
                    <p className="text-sm text-destructive">{errors.featuredImageUrl.message}</p>
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

