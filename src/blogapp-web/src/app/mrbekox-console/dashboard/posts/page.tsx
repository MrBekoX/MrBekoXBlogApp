'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { postsApi } from '@/lib/api';
import { getImageUrl } from '@/lib/utils';
import { Card, CardContent } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Skeleton } from '@/components/ui/skeleton';
import { toast } from 'sonner';
import { Plus, FileText, Eye, Calendar, MoreHorizontal, Pencil, Trash2, Send, EyeOff } from 'lucide-react';
import type { BlogPost, PaginatedResult } from '@/types';
import { usePostsStore } from '@/stores/posts-store';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';

export default function PostsPage() {
  const [posts, setPosts] = useState<BlogPost[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [totalCount, setTotalCount] = useState(0);
  const [pendingActionKey, setPendingActionKey] = useState<string | null>(null);
  const invalidatePublicPostsCache = usePostsStore((state) => state.invalidateCache);

  const fetchPosts = async () => {
    try {
      const response = await postsApi.getMyPosts({ pageSize: 50 });
      if (response.success && response.data) {
        const data = response.data as PaginatedResult<BlogPost>;
        setPosts(data.items);
        setTotalCount(data.totalCount);
      }
    } catch {
      toast.error('Yazılar yüklenemedi');
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    let cancelled = false;
    postsApi.getMyPosts({ pageSize: 50 })
      .then((response) => {
        if (cancelled) return;
        if (response.success && response.data) {
          const data = response.data as PaginatedResult<BlogPost>;
          setPosts(data.items);
          setTotalCount(data.totalCount);
        }
      })
      .catch(() => {
        if (cancelled) return;
        toast.error('Yazılar yüklenemedi');
      })
      .finally(() => {
        if (!cancelled) setIsLoading(false);
      });
    return () => { cancelled = true; };
  }, []);

  const runPostAction = async (
    id: string,
    action: 'delete' | 'publish' | 'unpublish',
    handler: () => Promise<void>,
  ) => {
    const actionKey = `${id}:${action}`;
    if (pendingActionKey) {
      return;
    }

    setPendingActionKey(actionKey);
    try {
      await handler();
    } finally {
      setPendingActionKey((current) => (current === actionKey ? null : current));
    }
  };

  const handleDelete = async (id: string) => {
    if (!confirm('Bu yazıyı silmek istediğinize emin misiniz?')) return;

    await runPostAction(id, 'delete', async () => {
      try {
        const response = await postsApi.delete(id);
        if (response.success) {
          toast.success('Yazı silindi');
          invalidatePublicPostsCache();
          await fetchPosts();
        } else {
          toast.error(response.message || 'Yazı silinemedi');
        }
      } catch {
        toast.error('Yazı silinemedi');
      }
    });
  };

  const handlePublish = async (id: string) => {
    await runPostAction(id, 'publish', async () => {
      try {
        const response = await postsApi.publish(id);
        if (response.success) {
          toast.success('Yazı yayınlandı');
          invalidatePublicPostsCache();
          await fetchPosts();
        } else {
          toast.error(response.message || 'Yazı yayınlanamadı');
        }
      } catch {
        toast.error('Yazı yayınlanamadı');
      }
    });
  };

  const handleUnpublish = async (id: string) => {
    await runPostAction(id, 'unpublish', async () => {
      try {
        const response = await postsApi.unpublish(id);
        if (response.success) {
          toast.success('Yazı yayından kaldırıldı');
          invalidatePublicPostsCache();
          await fetchPosts();
        } else {
          toast.error(response.message || 'Yazı yayından kaldırılamadı');
        }
      } catch {
        toast.error('Yazı yayından kaldırılamadı');
      }
    });
  };

  const formatDate = (dateString: string | null) => {
    if (!dateString) return '-';
    return new Date(dateString).toLocaleDateString('tr-TR', {
      day: 'numeric',
      month: 'long',
      year: 'numeric',
    });
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Yazılar</h1>
          <p className="text-muted-foreground">{totalCount} yazı bulunuyor</p>
        </div>
        <Button asChild>
          <Link href="/mrbekox-console/dashboard/posts/new">
            <Plus className="mr-2 h-4 w-4" />
            Yeni Yazı
          </Link>
        </Button>
      </div>

      {isLoading ? (
        <div className="space-y-4">
          {Array.from({ length: 5 }).map((_, i) => (
            <Card key={i}>
              <CardContent className="p-6">
                <div className="flex items-center gap-4">
                  <Skeleton className="h-16 w-16 rounded" />
                  <div className="flex-1 space-y-2">
                    <Skeleton className="h-5 w-3/4" />
                    <Skeleton className="h-4 w-1/2" />
                  </div>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      ) : posts.length > 0 ? (
        <div className="space-y-4">
          {posts.map((post) => {
            const isPostPending = pendingActionKey?.startsWith(`${post.id}:`) ?? false;

            return (
              <Card key={post.id} className="transition-shadow hover:shadow-md">
                <CardContent className="p-6">
                  <div className="flex items-start gap-4">
                    {post.featuredImageUrl ? (
                      <img
                        src={getImageUrl(post.featuredImageUrl)}
                        alt={post.title}
                        className="h-16 w-16 rounded object-cover"
                      />
                    ) : (
                      <div className="flex h-16 w-16 items-center justify-center rounded bg-muted">
                        <FileText className="h-8 w-8 text-muted-foreground" />
                      </div>
                    )}
                    <div className="flex-1 min-w-0">
                      <div className="flex items-start justify-between gap-4">
                        <div>
                          <h3 className="font-semibold truncate">{post.title}</h3>
                          <p className="text-sm text-muted-foreground line-clamp-1">
                            {post.excerpt}
                          </p>
                        </div>
                        <DropdownMenu>
                          <DropdownMenuTrigger asChild>
                            <Button variant="ghost" size="icon" disabled={isPostPending}>
                              <MoreHorizontal className="h-4 w-4" />
                            </Button>
                          </DropdownMenuTrigger>
                          <DropdownMenuContent align="end">
                            <DropdownMenuItem asChild disabled={isPostPending}>
                              <Link href={`/mrbekox-console/dashboard/posts/edit?id=${post.id}`}>
                                <Pencil className="mr-2 h-4 w-4" />
                                Düzenle
                              </Link>
                            </DropdownMenuItem>
                            {post.status === 'Draft' ? (
                              <DropdownMenuItem disabled={isPostPending} onClick={() => handlePublish(post.id)}>
                                <Send className="mr-2 h-4 w-4" />
                                Yayınla
                              </DropdownMenuItem>
                            ) : (
                              <DropdownMenuItem disabled={isPostPending} onClick={() => handleUnpublish(post.id)}>
                                <EyeOff className="mr-2 h-4 w-4" />
                                Yayından Kaldır
                              </DropdownMenuItem>
                            )}
                            <DropdownMenuItem
                              className="text-destructive"
                              disabled={isPostPending}
                              onClick={() => handleDelete(post.id)}
                            >
                              <Trash2 className="mr-2 h-4 w-4" />
                              Sil
                            </DropdownMenuItem>
                          </DropdownMenuContent>
                        </DropdownMenu>
                      </div>
                      <div className="mt-2 flex flex-wrap items-center gap-3 text-sm text-muted-foreground">
                        <Badge variant={post.status === 'Published' ? 'default' : 'secondary'}>
                          {post.status === 'Published' ? 'Yayında' : 'Taslak'}
                        </Badge>
                        <span className="flex items-center gap-1">
                          <Eye className="h-3.5 w-3.5" />
                          {post.viewCount}
                        </span>
                        <span className="flex items-center gap-1">
                          <Calendar className="h-3.5 w-3.5" />
                          {formatDate(post.publishedAt || post.createdAt)}
                        </span>
                        {post.category && (
                          <Badge variant="outline">{post.category.name}</Badge>
                        )}
                      </div>
                    </div>
                  </div>
                </CardContent>
              </Card>
            );
          })}
        </div>
      ) : (
        <Card>
          <CardContent className="py-12 text-center">
            <FileText className="mx-auto h-12 w-12 text-muted-foreground" />
            <h3 className="mt-4 text-lg font-semibold">Henüz yazı yok</h3>
            <p className="mt-2 text-muted-foreground">
              İlk blog yazınızı oluşturarak başlayın
            </p>
            <Button asChild className="mt-4">
              <Link href="/mrbekox-console/dashboard/posts/new">
                <Plus className="mr-2 h-4 w-4" />
                İlk Yazıyı Oluştur
              </Link>
            </Button>
          </CardContent>
        </Card>
      )}
    </div>
  );
}

